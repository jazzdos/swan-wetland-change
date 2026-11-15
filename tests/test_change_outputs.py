from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path

import click
import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pandas.api.types import is_bool_dtype, is_numeric_dtype
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from typer.testing import CliRunner

from tests.test_pipeline import _config
from wetland_change import cli
from wetland_change.attribution import dea_attribution
from wetland_change.change import SCORE_COLUMNS
from wetland_change.config import WaterConfig, WaterSetting
from wetland_change.ledger import LedgerEntry, entries_to_table
from wetland_change.outputs.changes import (
    CHANGE_COLUMNS,
    change_path,
    changes_to_frame,
    write_changes,
)
from wetland_change.outputs.geoparquet import (
    OBSERVATION_COLUMNS,
    read_observations,
    write_observations,
)
from wetland_change.outputs.provenance import FOOTER_KEYS, footer_metadata
from wetland_change.pipeline import score_changes
from wetland_change.sentinel_notice import copernicus_notice
from wetland_change.stats import ObservationRow
from wetland_change.store import OutputStore

WHEN = datetime(2026, 10, 27, 2, 26, 46, tzinfo=UTC)
WATER = WaterConfig(method="mndwi", threshold=-0.1)
OPERATION_EPSG = 32750
ITEM = "S2C_T50HLK_20261027T022351_L2A"
GEOMETRIES: dict[str, BaseGeometry] = {
    "ramsar-52": box(115.82, -32.16, 115.83, -32.15),
    "ramsar-56": box(115.93, -32.16, 115.94, -32.15),
}


def _score(polygon_id: str, metric: str, item_id: str = ITEM) -> dict[str, object]:
    return {
        "polygon_id": polygon_id,
        "acquisition_date": WHEN.date(),
        "month": 10,
        "datetime": WHEN,
        "item_id": item_id,
        "item_ids": item_id,
        "tile": "50HLK",
        "n_scenes": 1,
        "scene_coverage": 1.0,
        "n_clear": 90,
        "valid_fraction": 0.9,
        "metric": metric,
        "value": 0.7,
        "baseline_median": 0.2,
        "baseline_mad": 0.05,
        "baseline_n": 12,
        "z": 6.0,
        "flagged": True,
        "reason": None,
    }


def _scores(item_id: str = ITEM) -> pd.DataFrame:
    records = [
        _score("ramsar-56", "ndvi_median", item_id),
        _score("ramsar-52", "water_ha_index", item_id),
        _score("ramsar-52", "ndvi_median", item_id),
    ]
    return pd.DataFrame.from_records(records, columns=list(SCORE_COLUMNS))


def _obs(
    polygon_id: str, minx: float, item_id: str, when: datetime = WHEN
) -> ObservationRow:
    return ObservationRow(
        polygon_id=polygon_id,
        site="Forrestdale & Thomsons Lakes",
        aoi_layer="ramsar",
        item_id=item_id,
        product_uri="S2C_MSIL2A_x.SAFE",
        datetime=when,
        tile="50HLK",
        processing_baseline="05.13",
        scene_coverage=1.0,
        n_pixels=100,
        n_clear=90,
        valid_fraction=0.9,
        cloud_fraction=0.05,
        water_ha_index=0.5,
        water_ha_scl=0.6,
        ndwi_median=0.2,
        mndwi_median=0.3,
        ndvi_median=-0.1,
        dea_wo_agreement=None,
        geometry_4326=box(minx, -32.16, minx + 0.01, -32.15),
        run_id="run-1",
    )


def test_store_delete(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    store.write_bytes("a/b.txt", b"x")
    assert store.delete("a/b.txt") is True
    assert not store.exists("a/b.txt")
    assert store.delete("a/b.txt") is False
    assert store.delete("never/there.txt") is False


def test_read_observations_round_trip(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    later = datetime(2026, 10, 29, 2, 26, 46, tzinfo=UTC)
    write_observations(
        [
            _obs("ramsar-56", 115.93, "item-b", later),
            _obs("ramsar-52", 115.82, "item-b", later),
        ],
        store,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    write_observations(
        [_obs("ramsar-56", 115.93, "item-a"), _obs("ramsar-52", 115.82, "item-a")],
        store,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    frame = read_observations(store)
    assert list(frame["item_id"]) == ["item-a", "item-a", "item-b", "item-b"]
    assert list(frame["polygon_id"]) == ["ramsar-52", "ramsar-56"] * 2
    assert list(frame.index) == [0, 1, 2, 3]
    assert list(frame.columns) == [*OBSERVATION_COLUMNS, "geometry"]
    assert frame.crs.to_epsg() == 4326
    assert str(frame["datetime"].dtype).endswith("UTC]")
    assert frame.geometry.iloc[0].bounds == pytest.approx(
        (115.82, -32.16, 115.83, -32.15)
    )


def test_read_observations_empty_store(tmp_path: Path) -> None:
    frame = read_observations(OutputStore(str(tmp_path)))
    assert isinstance(frame, gpd.GeoDataFrame)
    assert frame.empty
    assert list(frame.columns) == [*OBSERVATION_COLUMNS, "geometry"]
    assert str(frame["datetime"].dtype).endswith("UTC]")
    assert frame.crs.to_epsg() == 4326


def test_change_path() -> None:
    assert (
        change_path(2026, "50HLK", ITEM)
        == f"changes/year=2026/tile=50HLK/chg_{ITEM}.parquet"
    )


def test_frame_columns_dtypes_and_order() -> None:
    frame = changes_to_frame(_scores(), GEOMETRIES)
    assert list(frame.columns) == [*CHANGE_COLUMNS, "geometry"]
    assert "run_id" not in frame.columns
    assert list(zip(frame["polygon_id"], frame["metric"], strict=True)) == [
        ("ramsar-52", "ndvi_median"),
        ("ramsar-52", "water_ha_index"),
        ("ramsar-56", "ndvi_median"),
    ]
    assert str(frame["datetime"].dtype).endswith("UTC]")
    assert frame["month"].dtype == "int64"
    assert frame["baseline_n"].dtype == "int64"
    assert frame["n_scenes"].dtype == "int64"
    for col in ("scene_coverage", "valid_fraction", "value", "z"):
        assert frame[col].dtype == "float64"
    for col in ("baseline_median", "baseline_mad"):
        assert frame[col].dtype == "float64"
    assert frame.crs.to_epsg() == 4326
    assert frame.geometry.iloc[0].equals(GEOMETRIES["ramsar-52"])
    assert frame.geometry.iloc[2].equals(GEOMETRIES["ramsar-56"])


def test_write_changes_returns_path_and_declares_covering_bbox(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_changes(
        _scores(), GEOMETRIES, store, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert relpath == change_path(2026, "50HLK", ITEM)
    meta = json.loads(pq.read_schema(tmp_path / relpath).metadata[b"geo"])
    assert meta["version"] == "1.1.0"
    assert meta["columns"]["geometry"]["covering"]["bbox"]["xmin"] == ["bbox", "xmin"]
    back = gpd.read_parquet(tmp_path / relpath)
    assert len(back) == 3
    assert back.crs.to_epsg() == 4326


def test_geoparquet_validator_accepts_file(tmp_path: Path) -> None:
    exe = shutil.which("geoparquet-validator")
    if exe is None:
        pytest.skip("geoparquet-validator not on PATH; run under uv")
    relpath = write_changes(
        _scores(),
        GEOMETRIES,
        OutputStore(str(tmp_path)),
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    result = subprocess.run(
        [exe, "check", str(tmp_path / relpath), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_rewrite_is_byte_identical(tmp_path: Path) -> None:
    first = OutputStore(str(tmp_path / "one"))
    second = OutputStore(str(tmp_path / "two"))
    path_one = write_changes(
        _scores(), GEOMETRIES, first, water=WATER, operation_epsg=OPERATION_EPSG
    )
    path_two = write_changes(
        _scores().iloc[::-1],
        GEOMETRIES,
        second,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    assert path_one == path_two
    assert first.read_bytes(path_one) == second.read_bytes(path_two)


def test_multi_item_scores_are_refused(tmp_path: Path) -> None:
    mixed = pd.concat([_scores(), _scores("other")], ignore_index=True)
    with pytest.raises(ValueError, match="one file per item"):
        write_changes(
            mixed,
            GEOMETRIES,
            OutputStore(str(tmp_path)),
            water=WATER,
            operation_epsg=OPERATION_EPSG,
        )


def test_empty_scores_are_refused(tmp_path: Path) -> None:
    empty = _scores().iloc[0:0]
    with pytest.raises(ValueError, match="no scores"):
        write_changes(
            empty,
            GEOMETRIES,
            OutputStore(str(tmp_path)),
            water=WATER,
            operation_epsg=OPERATION_EPSG,
        )


# score_changes

PRIOR_WATER = [38.0, 39.5, 40.0, 41.0, 42.5, 40.5]
PRIOR_NDVI = [0.18, 0.19, 0.2, 0.21, 0.22, 0.2]
SCORED_DAY = date(2026, 10, 27)
OUTLIER_WATER = 60.0
CHANGE_FILE = change_path(2026, "50HLK", "item-2026")
MIN_VALID = 0.8


def _row(
    item_id: str,
    when: datetime,
    water: float,
    ndvi: float,
    *,
    valid_fraction: float = 0.95,
    scene_coverage: float = 1.0,
    tile: str = "50HLK",
    polygon_id: str = "ramsar-52",
) -> ObservationRow:
    return ObservationRow(
        polygon_id=polygon_id,
        site="Forrestdale & Thomsons Lakes",
        aoi_layer="ramsar",
        item_id=item_id,
        product_uri="S2C_MSIL2A_x.SAFE",
        datetime=when,
        tile=tile,
        processing_baseline="05.13",
        scene_coverage=scene_coverage,
        n_pixels=1000,
        n_clear=round(1000 * valid_fraction),
        valid_fraction=valid_fraction,
        cloud_fraction=0.05,
        water_ha_index=water,
        water_ha_scl=water,
        ndwi_median=0.2,
        mndwi_median=0.3,
        ndvi_median=ndvi,
        dea_wo_agreement=None,
        geometry_4326=GEOMETRIES[polygon_id],
        run_id="run-1",
    )


def _seed(store: OutputStore, n_prior: int = 6) -> None:
    for i in range(n_prior):
        when = datetime(2020 + i, 10, 27, 2, 26, 46, tzinfo=UTC)
        write_observations(
            [_row(f"item-{when.year}", when, PRIOR_WATER[i], PRIOR_NDVI[i])],
            store,
            water=WATER,
            operation_epsg=OPERATION_EPSG,
        )


def _score_day(
    store: OutputStore, water: float, ndvi: float = 0.2, **kwargs: float
) -> None:
    when = datetime(2026, 10, 27, 2, 26, 46, tzinfo=UTC)
    write_observations(
        [_row("item-2026", when, water, ndvi, **kwargs)],
        store,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )


def _expected_z(value: float, prior: list[float]) -> float:
    values = np.array(prior)
    median = np.median(values)
    return float((value - median) / (1.4826 * np.median(np.abs(values - median))))


def test_score_changes_writes_outlier(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store)
    _score_day(store, OUTLIER_WATER)
    result = score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert result.files == [CHANGE_FILE]
    assert result.rows == 1
    assert result.removed == []
    back = gpd.read_parquet(tmp_path / CHANGE_FILE)
    assert len(back) == 1
    row = back.iloc[0]
    assert row["metric"] == "water_ha_index"
    assert row["z"] == pytest.approx(_expected_z(OUTLIER_WATER, PRIOR_WATER))
    assert row["value"] == OUTLIER_WATER
    assert row["baseline_n"] == 6
    assert row["baseline_median"] == pytest.approx(np.median(PRIOR_WATER))


def test_score_changes_written_file_has_no_nulls(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store)
    _score_day(store, OUTLIER_WATER)
    score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    back = gpd.read_parquet(tmp_path / CHANGE_FILE)
    required = [
        "polygon_id",
        "item_id",
        "datetime",
        "metric",
        "value",
        "z",
        "baseline_median",
        "baseline_mad",
        "baseline_n",
    ]
    assert not back[required].isna().any().any()
    assert back.geometry.iloc[0].equals(GEOMETRIES["ramsar-52"])


def test_score_changes_normal_value_writes_nothing(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store)
    _score_day(store, 40.5)
    result = score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert (result.files, result.rows, result.removed) == ([], 0, [])
    assert store.list_files("changes") == []


def test_score_changes_low_valid_fraction_writes_nothing(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store)
    _score_day(store, OUTLIER_WATER, valid_fraction=0.7)
    result = score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert result.files == []
    assert store.list_files("changes") == []


def test_score_changes_ignores_same_day_partner_and_later_rows(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store)
    _score_day(store, OUTLIER_WATER)
    same_day = datetime(2026, 10, 27, 2, 26, 50, tzinfo=UTC)
    write_observations(
        [_row("partner", same_day, 500.0, 0.9, scene_coverage=0.4, tile="50HMK")],
        store,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    later = datetime(2027, 10, 27, 2, 26, 46, tzinfo=UTC)
    write_observations(
        [_row("item-2027", later, 900.0, 0.95)],
        store,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    result = score_changes(
        store,
        min_valid_fraction=MIN_VALID,
        dates=[SCORED_DAY],
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    assert result.files == [CHANGE_FILE]
    row = gpd.read_parquet(tmp_path / CHANGE_FILE).iloc[0]
    assert row["z"] == pytest.approx(_expected_z(OUTLIER_WATER, PRIOR_WATER))
    assert row["baseline_n"] == 6
    assert row["item_ids"] == "item-2026,partner"


def test_score_changes_too_few_prior_samples_flags_nothing(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store, n_prior=3)
    _score_day(store, OUTLIER_WATER)
    result = score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert (result.files, result.rows) == ([], 0)


def test_score_changes_empty_store(tmp_path: Path) -> None:
    result = score_changes(
        OutputStore(str(tmp_path)),
        min_valid_fraction=MIN_VALID,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    assert (result.files, result.rows, result.removed) == ([], 0, [])


def test_score_changes_deletes_stale_change_file(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store)
    _score_day(store, OUTLIER_WATER)
    assert score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    ).files == [CHANGE_FILE]
    _score_day(store, 40.5)
    result = score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert result.files == []
    assert result.removed == [CHANGE_FILE]
    assert not store.exists(CHANGE_FILE)
    again = score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert again.removed == []


def test_score_changes_is_byte_identical_on_rerun(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store)
    _score_day(store, OUTLIER_WATER)
    score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    first = store.read_bytes(CHANGE_FILE)
    result = score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert result.files == [CHANGE_FILE]
    assert store.read_bytes(CHANGE_FILE) == first


def test_score_changes_date_range_is_inclusive_and_excludes_others(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store)
    _score_day(store, OUTLIER_WATER)
    later = datetime(2027, 10, 27, 2, 26, 46, tzinfo=UTC)
    write_observations(
        [_row("item-2027", later, 900.0, 0.2)],
        store,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    window = (SCORED_DAY, SCORED_DAY)
    result = score_changes(
        store,
        min_valid_fraction=MIN_VALID,
        date_range=window,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    assert result.files == [CHANGE_FILE]
    outside = (date(2026, 11, 1), date(2026, 11, 30))
    result = score_changes(
        store,
        min_valid_fraction=MIN_VALID,
        date_range=outside,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    assert (result.files, result.rows, result.removed) == ([], 0, [])
    both = score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert both.files == sorted([CHANGE_FILE, change_path(2027, "50HLK", "item-2027")])


class CountingStore(OutputStore):
    """Records every path read through `read_bytes`."""

    def __init__(self, root: str) -> None:
        super().__init__(root)
        self.reads: list[str] = []

    def read_bytes(self, relpath: str) -> bytes:
        self.reads.append(relpath)
        return super().read_bytes(relpath)


def _ledger_entry(item_id: str, when: datetime, path: str) -> LedgerEntry:
    return LedgerEntry(
        item_id=item_id,
        collection="sentinel-2-c1-l2a",
        datetime=when,
        created=when,
        updated=when,
        tile="50HLK",
        cloud_cover=1.0,
        product_uri="S2C_MSIL2A_x.SAFE",
        status="succeeded",
        attempts=1,
        error=None,
        run_id="run-1",
        processed_at=when,
        n_rows=1,
        observation_path=path,
        source_item=None,
    )


OFF_MONTHS = [
    datetime(2021, 6, 14, 2, 26, 46, tzinfo=UTC),
    datetime(2023, 3, 9, 2, 26, 46, tzinfo=UTC),
    datetime(2024, 3, 11, 2, 26, 46, tzinfo=UTC),
    datetime(2025, 12, 2, 2, 26, 46, tzinfo=UTC),
]


def _spread_store(root: str) -> tuple[CountingStore, pa.Table, dict[str, datetime]]:
    """October history, an October outlier and observations in other months.

    The returned ledger names every observation file.
    """
    store = CountingStore(root)
    _seed(store)
    _score_day(store, OUTLIER_WATER)
    for when in OFF_MONTHS:
        write_observations(
            [_row(f"item-{when:%Y%m%d}", when, 70.0, 0.9)],
            store,
            water=WATER,
            operation_epsg=OPERATION_EPSG,
        )
    stamps: dict[str, datetime] = {}
    for path in store.list_files("observations"):
        name = path.rsplit("/", 1)[-1].removeprefix("obs_").removesuffix(".parquet")
        frame = gpd.read_parquet(BytesIO(store.read_bytes(path)))
        stamps[path] = frame["datetime"].iloc[0].to_pydatetime()
        assert name.startswith("item-")
    ledger = entries_to_table(
        [_ledger_entry(Path(p).stem, when, p) for p, when in stamps.items()]
    )
    store.reads.clear()
    return store, ledger, stamps


# Footer key-value metadata

PER_METRIC_UNITS = {"water_ha_index": "hectares", "ndvi_median": "unitless index"}
WATER_WITH_OVERRIDE = WaterConfig(
    method="mndwi",
    threshold=-0.1,
    overrides={
        "ramsar-56": WaterSetting(method="mndwi", threshold=0.05, agreement_min=0.9)
    },
)


def _change_footers(path: Path) -> list[dict[bytes, bytes]]:
    return [pq.read_schema(path).metadata, pq.read_metadata(path).metadata]


def test_change_footer_records_crss_scl_drops_and_water_settings(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_changes(
        _scores(),
        GEOMETRIES,
        store,
        water=WATER_WITH_OVERRIDE,
        operation_epsg=OPERATION_EPSG,
    )
    for footer in _change_footers(tmp_path / relpath):
        assert footer[b"source_epsg"] == b"32750"
        assert footer[b"operation_epsg"] == b"32750"
        assert footer[b"geometry_epsg"] == b"4326"
        assert json.loads(footer[b"scl_classes_dropped"]) == [0, 1, 2, 3, 8, 9, 10]
        assert json.loads(footer[b"scl_classes_clear"]) == [4, 5, 6, 7, 11]
        assert json.loads(footer[b"water_settings"]) == {
            "ramsar-52": {"method": "mndwi", "threshold": -0.1},
            "ramsar-56": {"method": "mndwi", "threshold": 0.05},
        }
        assert b"config_sha256" in footer[b"water_units_note"]
    meta = json.loads(pq.read_schema(tmp_path / relpath).metadata[b"geo"])
    assert meta["columns"]["geometry"]["covering"]["bbox"]["xmin"] == ["bbox", "xmin"]
    assert gpd.read_parquet(tmp_path / relpath).crs.to_epsg() == 4326


def test_change_footer_units_depend_on_the_metric_column(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_changes(
        _scores(), GEOMETRIES, store, water=WATER, operation_epsg=OPERATION_EPSG
    )
    units = json.loads(pq.read_schema(tmp_path / relpath).metadata[b"units"])
    for column in ("value", "baseline_median", "baseline_mad"):
        assert units[column] == PER_METRIC_UNITS
    assert units["z"] == "unitless (robust z-score)"
    assert units["month"] == "calendar month 1 to 12"
    assert units["n_scenes"] == "count"
    assert units["baseline_n"] == "count"
    assert units["scene_coverage"] == "fraction (0 to 1)"
    assert units["valid_fraction"] == "fraction (0 to 1)"


def test_every_numeric_change_column_has_a_unit(tmp_path: Path) -> None:
    frame = changes_to_frame(_scores(), GEOMETRIES)
    footer = footer_metadata(
        frame, kind="change", water=WATER, operation_epsg=OPERATION_EPSG
    )
    units = json.loads(footer["units"])
    numeric = [
        column
        for column in frame.columns
        if column != "geometry"
        and is_numeric_dtype(frame[column])
        and not is_bool_dtype(frame[column])
    ]
    assert numeric
    assert set(numeric) <= set(units)
    assert set(units) <= set(frame.columns)


def test_change_footer_water_settings_only_list_polygons_in_the_file(
    tmp_path: Path,
) -> None:
    only_52 = _scores().loc[lambda frame: frame["polygon_id"] == "ramsar-52"]
    store = OutputStore(str(tmp_path))
    relpath = write_changes(
        only_52,
        GEOMETRIES,
        store,
        water=WATER_WITH_OVERRIDE,
        operation_epsg=OPERATION_EPSG,
    )
    settings = json.loads(
        pq.read_schema(tmp_path / relpath).metadata[b"water_settings"]
    )
    assert settings == {"ramsar-52": {"method": "mndwi", "threshold": -0.1}}


def test_score_changes_written_file_carries_the_footer_crss(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store)
    _score_day(store, OUTLIER_WATER)
    score_changes(
        store,
        min_valid_fraction=MIN_VALID,
        water=WATER_WITH_OVERRIDE,
        operation_epsg=OPERATION_EPSG,
    )
    footer = pq.read_schema(tmp_path / CHANGE_FILE).metadata
    assert footer[b"source_epsg"] == b"32750"
    assert footer[b"operation_epsg"] == b"32750"
    assert footer[b"geometry_epsg"] == b"4326"
    assert json.loads(footer[b"water_settings"]) == {
        "ramsar-52": {"method": "mndwi", "threshold": -0.1}
    }


def _change_files_bytes(store: OutputStore) -> dict[str, bytes]:
    return {p: store.read_bytes(p) for p in store.list_files("changes")}


def test_score_changes_with_ledger_matches_no_ledger_and_skips_other_months(
    tmp_path: Path,
) -> None:
    store, ledger, stamps = _spread_store(str(tmp_path / "with"))
    day = {SCORED_DAY}
    with_ledger = score_changes(
        store,
        min_valid_fraction=MIN_VALID,
        dates=day,
        rescore_later=True,
        ledger=ledger,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    october = {p for p, when in stamps.items() if when.month == 10}
    assert {p for p in store.reads if p.startswith("observations/")} == october
    assert len(october) < len(stamps)

    plain, _, _ = _spread_store(str(tmp_path / "plain"))
    without = score_changes(
        plain,
        min_valid_fraction=MIN_VALID,
        dates=day,
        rescore_later=True,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    assert with_ledger == without
    assert with_ledger.files == [CHANGE_FILE]
    assert _change_files_bytes(store) == _change_files_bytes(plain)

    full, _, _ = _spread_store(str(tmp_path / "full"))
    score_changes(
        full, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert store.read_bytes(CHANGE_FILE) == full.read_bytes(CHANGE_FILE)


def test_score_changes_with_ledger_removes_the_same_stale_files(
    tmp_path: Path,
) -> None:
    store, ledger, _ = _spread_store(str(tmp_path / "a"))
    score_changes(
        store, min_valid_fraction=MIN_VALID, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert store.exists(CHANGE_FILE)
    _score_day(store, 40.5)
    result = score_changes(
        store,
        min_valid_fraction=MIN_VALID,
        dates={SCORED_DAY},
        rescore_later=True,
        ledger=ledger,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    assert result.removed == [CHANGE_FILE]
    assert not store.exists(CHANGE_FILE)


def test_score_changes_reads_an_observation_file_that_has_no_ledger_row(
    tmp_path: Path,
) -> None:
    store, ledger, stamps = _spread_store(str(tmp_path))
    march = next(p for p, when in stamps.items() if when.month == 3)
    kept = ledger.filter(pa.compute.not_equal(ledger["observation_path"], march))
    assert kept.num_rows == ledger.num_rows - 1
    score_changes(
        store,
        min_valid_fraction=MIN_VALID,
        dates={SCORED_DAY},
        rescore_later=True,
        ledger=kept,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    read = {p for p in store.reads if p.startswith("observations/")}
    assert march in read
    assert read == {p for p, when in stamps.items() if when.month in (10,)} | {march}


def test_score_changes_without_dates_reads_every_file_even_with_a_ledger(
    tmp_path: Path,
) -> None:
    store, ledger, stamps = _spread_store(str(tmp_path))
    score_changes(
        store,
        min_valid_fraction=MIN_VALID,
        ledger=ledger,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    assert {p for p in store.reads if p.startswith("observations/")} == set(stamps)


def test_score_changes_date_range_alone_does_not_exclude_files(
    tmp_path: Path,
) -> None:
    store, ledger, stamps = _spread_store(str(tmp_path))
    score_changes(
        store,
        min_valid_fraction=MIN_VALID,
        date_range=(SCORED_DAY, SCORED_DAY),
        ledger=ledger,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    assert {p for p in store.reads if p.startswith("observations/")} == set(stamps)


def test_read_observations_exclude_skips_the_named_paths(tmp_path: Path) -> None:
    store, _, stamps = _spread_store(str(tmp_path))
    skipped = sorted(stamps)[:2]
    frame = read_observations(store, exclude=skipped)
    assert set(frame["item_id"]) == {
        Path(p).stem.removeprefix("obs_") for p in stamps if p not in skipped
    }
    assert not set(store.reads) & set(skipped)


runner = CliRunner()


def _score_cli_setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path]:
    cfg = _config(tmp_path / "configured")
    monkeypatch.setattr(cli, "load_config", lambda config: cfg)
    config_file = tmp_path / "pipeline.toml"
    config_file.write_text("# test config\n")
    override = tmp_path / "override"
    store = OutputStore(str(override))
    _seed(store)
    _score_day(store, OUTLIER_WATER)
    return config_file, override


def _score_args(config_file: Path, override: Path, start: str, end: str) -> list[str]:
    return [
        "score",
        "--start",
        start,
        "--end",
        end,
        "--config",
        str(config_file),
        "--output-root",
        str(override),
    ]


def test_score_help_lists_range_and_output_root() -> None:
    result = runner.invoke(cli.app, ["score", "--help"])
    assert result.exit_code == 0
    for option in ("--start", "--end", "--output-root"):
        assert option in click.unstyle(result.output)


def test_score_cli_writes_changes_and_manifest_under_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, override = _score_cli_setup(monkeypatch, tmp_path)
    result = runner.invoke(
        cli.app, _score_args(config_file, override, "2026-10-27", "2026-10-27")
    )
    assert result.exit_code == 0, result.output
    assert list((override / "changes").rglob("*.parquet"))
    manifests = sorted((override / "runs").glob("*.json"))
    assert len(manifests) == 1
    payload = json.loads(manifests[0].read_text())
    assert payload["kind"] == "score"
    assert payload["change_rows"] >= 1
    assert payload["output_root_override"] == str(override)
    assert payload["datetime_end"] == "2026-10-27T23:59:59.999999+00:00"
    assert not (tmp_path / "configured").exists()


def test_score_cli_rejects_reversed_range_before_loading_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(config: Path) -> None:
        raise AssertionError("config must not be loaded")

    monkeypatch.setattr(cli, "load_config", fail)
    config_file = tmp_path / "pipeline.toml"
    config_file.write_text("# test config\n")
    result = runner.invoke(
        cli.app,
        _score_args(config_file, tmp_path / "out", "2026-10-28", "2026-10-27"),
    )
    assert result.exit_code == 2
    assert not isinstance(result.exception, AssertionError)


def test_score_cli_day_range_is_inclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, override = _score_cli_setup(monkeypatch, tmp_path)
    result = runner.invoke(
        cli.app, _score_args(config_file, override, "2026-10-26", "2026-10-26")
    )
    assert result.exit_code == 0, result.output
    assert not list((override / "changes").rglob("*.parquet"))
    payload = json.loads(next((override / "runs").glob("*.json")).read_text())
    assert payload["change_rows"] == 0


def test_change_footer_carries_the_dea_attribution(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_changes(
        _scores(), GEOMETRIES, store, water=WATER, operation_epsg=OPERATION_EPSG
    )
    expected = footer_metadata(
        changes_to_frame(_scores(), GEOMETRIES),
        kind="change",
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    for footer in _change_footers(tmp_path / relpath):
        parsed = json.loads(footer[b"dea_attribution"])
        assert parsed == dea_attribution("change")
        assert (
            parsed["copyright"] == "© Commonwealth of Australia (Geoscience Australia)"
        )
        assert parsed["licence_uri"] == "https://creativecommons.org/licenses/by/4.0/"
        assert len(parsed["datasets"]) == 1
        dataset = parsed["datasets"][0]
        assert "Waterbodies" in dataset["name"]
        assert "https://dx.doi.org/10.26186/148920" in dataset["citation"]
        assert "https://doi.org/10.3390/rs13081437" in dataset["paper_citation"]
        assert (
            "https://knowledge.dea.ga.gov.au/data/product/dea-waterbodies-landsat/"
            in dataset["sources"]
        )
        assert dataset["modification"]
        for key in FOOTER_KEYS:
            assert footer[key.encode()] == expected[key].encode()
        keys = {k.decode() for k in footer} - {"geo", "pandas", "ARROW:schema"}
        assert keys == {*FOOTER_KEYS, "dea_attribution", "copernicus_notice"}


def test_write_changes_notice_years_default_to_the_scored_rows(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_changes(
        _scores(), GEOMETRIES, store, water=WATER, operation_epsg=OPERATION_EPSG
    )
    for footer in _change_footers(tmp_path / relpath):
        parsed = json.loads(footer[b"copernicus_notice"])
        assert parsed == copernicus_notice("change", [2026])
        assert parsed["notice"] == "Contains modified Copernicus Sentinel data 2026"


def test_write_changes_notice_years_include_the_baseline_years(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_changes(
        _scores(),
        GEOMETRIES,
        store,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
        baseline_years={2024, 2025},
    )
    for footer in _change_footers(tmp_path / relpath):
        parsed = json.loads(footer[b"copernicus_notice"])
        assert parsed == copernicus_notice("change", [2024, 2025, 2026])
        assert parsed["years"] == [2024, 2025, 2026]
        assert (
            parsed["notice"] == "Contains modified Copernicus Sentinel data 2024-2026"
        )


def test_score_changes_notice_years_cover_the_baseline_observations(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store)
    _score_day(store, OUTLIER_WATER)
    score_changes(
        store,
        min_valid_fraction=MIN_VALID,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    for footer in _change_footers(tmp_path / CHANGE_FILE):
        parsed = json.loads(footer[b"copernicus_notice"])
        assert parsed["years"] == [2020, 2021, 2022, 2023, 2024, 2025, 2026]
        assert (
            parsed["notice"] == "Contains modified Copernicus Sentinel data 2020-2026"
        )
    row = gpd.read_parquet(tmp_path / CHANGE_FILE).iloc[0]
    assert row["z"] == pytest.approx(_expected_z(OUTLIER_WATER, PRIOR_WATER))
    assert row["value"] == OUTLIER_WATER
    assert row["baseline_median"] == pytest.approx(float(np.median(PRIOR_WATER)))


def test_score_changes_notice_ignores_observations_from_other_months(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    _seed(store)
    other_month = datetime(2019, 3, 27, 2, 26, 46, tzinfo=UTC)
    write_observations(
        [_row("item-2019", other_month, 90.0, 0.9)],
        store,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    _score_day(store, OUTLIER_WATER)
    score_changes(
        store,
        min_valid_fraction=MIN_VALID,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    for footer in _change_footers(tmp_path / CHANGE_FILE):
        parsed = json.loads(footer[b"copernicus_notice"])
        assert 2019 not in parsed["years"]
        assert (
            parsed["notice"] == "Contains modified Copernicus Sentinel data 2020-2026"
        )
