from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
from pandas.api.types import is_bool_dtype, is_numeric_dtype
from shapely.geometry import box

from wetland_change.attribution import dea_attribution
from wetland_change.config import WaterConfig, WaterSetting
from wetland_change.mask import CLEAR_BANDS, CLEAR_CLASSES
from wetland_change.outputs.geoparquet import (
    OBSERVATION_COLUMNS,
    observation_path,
    read_observations,
    rows_to_frame,
    to_geoparquet_bytes,
    write_observations,
)
from wetland_change.outputs.provenance import FOOTER_KEYS, footer_metadata
from wetland_change.stats import ObservationRow
from wetland_change.store import OutputStore

WHEN = datetime(2026, 10, 27, 2, 26, 46, tzinfo=UTC)
WATER = WaterConfig(method="mndwi", threshold=-0.1)
OPERATION_EPSG = 32750


def _row(
    polygon_id: str, minx: float, item_id: str = "S2C_T50HLK_20261027T022351_L2A"
) -> ObservationRow:
    return ObservationRow(
        polygon_id=polygon_id,
        site="Forrestdale & Thomsons Lakes",
        aoi_layer="ramsar",
        item_id=item_id,
        product_uri="S2C_MSIL2A_x.SAFE",
        datetime=WHEN,
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


ROWS = [_row("ramsar-56", 115.93), _row("ramsar-52", 115.82)]


def _footer(frame: gpd.GeoDataFrame, water: WaterConfig = WATER) -> dict[str, str]:
    return footer_metadata(
        frame, kind="observation", water=water, operation_epsg=OPERATION_EPSG
    )


def test_observation_path() -> None:
    assert (
        observation_path(2026, "50HLK", "S2C_T50HLK_20261027T022351_L2A")
        == "observations/year=2026/tile=50HLK/obs_S2C_T50HLK_20261027T022351_L2A.parquet"  # noqa: E501
    )


def test_frame_is_sorted_and_typed() -> None:
    frame = rows_to_frame(ROWS)
    assert list(frame["polygon_id"]) == ["ramsar-52", "ramsar-56"]
    assert list(frame.columns) == [*OBSERVATION_COLUMNS, "geometry"]
    dtype = str(frame["datetime"].dtype)
    assert dtype.startswith("datetime64[") and dtype.endswith("UTC]")
    assert frame["dea_wo_agreement"].dtype == "float64"
    assert frame.crs.to_epsg() == 4326


def test_write_and_read_back(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_observations(
        ROWS, store, water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert relpath == observation_path(2026, "50HLK", ROWS[0].item_id)
    back = gpd.read_parquet(tmp_path / relpath)
    assert len(back) == 2
    assert back.crs.to_epsg() == 4326
    assert back["water_ha_scl"].tolist() == [0.6, 0.6]


def test_geo_metadata_declares_covering_bbox(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_observations(
        ROWS, store, water=WATER, operation_epsg=OPERATION_EPSG
    )
    meta = json.loads(pq.read_schema(tmp_path / relpath).metadata[b"geo"])
    assert meta["version"] == "1.1.0"
    assert meta["columns"]["geometry"]["covering"]["bbox"]["xmin"] == ["bbox", "xmin"]
    assert meta["columns"]["geometry"]["crs"] is not None


def test_geoparquet_validator_accepts_file(tmp_path: Path) -> None:
    exe = shutil.which("geoparquet-validator")
    if exe is None:
        pytest.skip("geoparquet-validator not on PATH; run under uv")
    store = OutputStore(str(tmp_path))
    relpath = write_observations(
        ROWS, store, water=WATER, operation_epsg=OPERATION_EPSG
    )
    result = subprocess.run(
        [exe, "check", str(tmp_path / relpath), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_duckdb_reads_bbox_column(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_observations(
        ROWS, store, water=WATER, operation_epsg=OPERATION_EPSG
    )
    rows = (
        duckdb.connect()
        .execute(
            "SELECT polygon_id, bbox.xmin FROM read_parquet(?) ORDER BY polygon_id",
            [str(tmp_path / relpath)],
        )
        .fetchall()
    )
    assert rows[0][0] == "ramsar-52"
    assert rows[0][1] == pytest.approx(115.82)


def test_installed_readers_agree_on_rows_and_bounds(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    write_observations(
        [_row("ramsar-56", 115.93), _row("ramsar-52", 115.82)],
        store,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    second = "S2C_T50HLK_20261030T022351_L2A"
    write_observations(
        [
            _row("ramsar-60", 115.50, item_id=second),
            _row("ramsar-61", 116.10, item_id=second),
        ],
        store,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    files = sorted((tmp_path / "observations").glob("*/*/*.parquet"))
    assert len(files) == 2

    duck = (
        duckdb.connect()
        .execute(
            "SELECT count(*), min(bbox.xmin), min(bbox.ymin), max(bbox.xmax), "
            "max(bbox.ymax) FROM read_parquet(?, hive_partitioning = true)",
            [str(tmp_path / "observations" / "*" / "*" / "*.parquet")],
        )
        .fetchone()
    )
    assert duck is not None
    duck_rows, duck_bounds = duck[0], tuple(duck[1:])

    table = pa.concat_tables([pq.read_table(path) for path in files])
    bbox = table.column("bbox").combine_chunks()
    arrow_rows = table.num_rows
    arrow_bounds = (
        pc.min(bbox.field("xmin")).as_py(),
        pc.min(bbox.field("ymin")).as_py(),
        pc.max(bbox.field("xmax")).as_py(),
        pc.max(bbox.field("ymax")).as_py(),
    )

    frame = pd.concat([gpd.read_parquet(path) for path in files])
    geo_rows = len(frame)
    geo_bounds = tuple(float(v) for v in gpd.GeoDataFrame(frame).total_bounds)

    assert duck_rows == arrow_rows == geo_rows == 4
    assert arrow_bounds == pytest.approx(duck_bounds, abs=1e-9)
    assert geo_bounds == pytest.approx(duck_bounds, abs=1e-9)


def test_rewrite_is_byte_identical() -> None:
    frame = rows_to_frame(ROWS)
    reversed_frame = rows_to_frame(list(reversed(ROWS)))
    assert to_geoparquet_bytes(frame, _footer(frame)) == to_geoparquet_bytes(
        reversed_frame, _footer(reversed_frame)
    )


def test_mixed_items_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="one file per item"):
        write_observations(
            [ROWS[0], _row("x", 115.0, item_id="other")],
            OutputStore(str(tmp_path)),
            water=WATER,
            operation_epsg=OPERATION_EPSG,
        )


# Footer key-value metadata


def _written(tmp_path: Path, rows: list[ObservationRow], water: WaterConfig = WATER):
    store = OutputStore(str(tmp_path))
    relpath = write_observations(
        rows, store, water=water, operation_epsg=OPERATION_EPSG
    )
    return tmp_path / relpath


def _footers(path: Path) -> list[dict[bytes, bytes]]:
    schema = pq.read_schema(path).metadata
    file_level = pq.read_metadata(path).metadata
    return [schema, file_level]


def test_footer_records_the_crss(tmp_path: Path) -> None:
    for footer in _footers(_written(tmp_path, ROWS)):
        assert footer[b"source_epsg"] == b"32750"
        assert footer[b"operation_epsg"] == b"32750"
        assert footer[b"geometry_epsg"] == b"4326"


def test_footer_units_name_hectares_indices_and_fractions(tmp_path: Path) -> None:
    for footer in _footers(_written(tmp_path, ROWS)):
        units = json.loads(footer[b"units"])
        assert units["water_ha_index"] == "hectares"
        assert units["water_ha_scl"] == "hectares"
        for column in ("ndwi_median", "mndwi_median", "ndvi_median"):
            assert units[column] == "unitless index"
        for column in (
            "scene_coverage",
            "valid_fraction",
            "cloud_fraction",
            "dea_wo_agreement",
        ):
            assert units[column] == "fraction (0 to 1)"
        assert units["n_pixels"] == "count of 10 m pixels"
        assert units["n_clear"] == "count of 10 m pixels"


def test_every_numeric_observation_column_has_a_unit() -> None:
    frame = rows_to_frame(ROWS)
    units = json.loads(_footer(frame)["units"])
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


def test_footer_names_the_scl_classes_the_clear_mask_drops(tmp_path: Path) -> None:
    for footer in _footers(_written(tmp_path, ROWS)):
        dropped = json.loads(footer[b"scl_classes_dropped"])
        assert dropped == [0, 1, 2, 3, 8, 9, 10]
        assert dropped == sorted(set(range(12)) - set(CLEAR_CLASSES))
        assert json.loads(footer[b"scl_classes_clear"]) == list(CLEAR_CLASSES)
        assert b"finite" in footer[b"clear_pixel_rule"]
        for band in CLEAR_BANDS:
            assert band.encode() in footer[b"clear_pixel_rule"]
        assert b"clear pixels of SCL class 6" in footer[b"water_units_note"]


WATER_WITH_OVERRIDES = WaterConfig(
    method="mndwi",
    threshold=-0.1,
    overrides={
        "ramsar-56": WaterSetting(method="mndwi", threshold=0.05, agreement_min=0.9),
        "ramsar-15": WaterSetting(method="scl6", agreement_min=0.9),
    },
)


def test_footer_water_settings_cover_only_polygons_in_the_file(tmp_path: Path) -> None:
    path = _written(tmp_path, ROWS, WATER_WITH_OVERRIDES)
    for footer in _footers(path):
        settings = json.loads(footer[b"water_settings"])
        assert settings == {
            "ramsar-52": {"method": "mndwi", "threshold": -0.1},
            "ramsar-56": {"method": "mndwi", "threshold": 0.05},
        }
        assert b"unitless" in footer[b"water_units_note"]


def test_footer_water_settings_for_an_scl6_polygon_have_a_null_threshold(
    tmp_path: Path,
) -> None:
    path = _written(tmp_path, [_row("ramsar-15", 115.5)], WATER_WITH_OVERRIDES)
    settings = json.loads(pq.read_schema(path).metadata[b"water_settings"])
    assert settings == {"ramsar-15": {"method": "scl6", "threshold": None}}


def test_footer_leaves_geo_metadata_and_crs_readable(tmp_path: Path) -> None:
    path = _written(tmp_path, ROWS)
    meta = json.loads(pq.read_schema(path).metadata[b"geo"])
    assert meta["columns"]["geometry"]["covering"]["bbox"]["xmin"] == ["bbox", "xmin"]
    assert gpd.read_parquet(path).crs.to_epsg() == 4326


def test_footer_refuses_a_frame_without_an_epsg() -> None:
    frame = rows_to_frame(ROWS).set_crs(None, allow_override=True)
    with pytest.raises(ValueError, match="EPSG"):
        _footer(frame)


def test_rewrite_with_reversed_rows_is_byte_identical(tmp_path: Path) -> None:
    one = _written(tmp_path / "a", ROWS).read_bytes()
    two = _written(tmp_path / "b", list(reversed(ROWS))).read_bytes()
    assert one == two


def test_read_observations_mixes_files_with_and_without_footer_keys(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    old_item = "S2C_T50HLK_20261020T022351_L2A"
    old_rows = [_row("ramsar-60", 115.50, item_id=old_item)]
    old_path = observation_path(2026, "50HLK", old_item)
    plain = BytesIO()
    rows_to_frame(old_rows).to_parquet(
        plain, index=False, schema_version="1.1.0", write_covering_bbox=True
    )
    store.write_bytes(old_path, plain.getvalue())
    assert b"units" not in pq.read_schema(tmp_path / old_path).metadata
    write_observations(ROWS, store, water=WATER, operation_epsg=OPERATION_EPSG)

    combined = read_observations(store)
    assert sorted(combined["polygon_id"]) == ["ramsar-52", "ramsar-56", "ramsar-60"]
    assert combined.crs.to_epsg() == 4326


def test_footer_carries_the_dea_attribution_for_observations(
    tmp_path: Path,
) -> None:
    frame = rows_to_frame(ROWS)
    for footer in _footers(_written(tmp_path, ROWS)):
        parsed = json.loads(footer[b"dea_attribution"])
        assert parsed == dea_attribution("observation")
        assert (
            parsed["copyright"] == "© Commonwealth of Australia (Geoscience Australia)"
        )
        assert parsed["licence_uri"] == "https://creativecommons.org/licenses/by/4.0/"
        waterbodies = [d for d in parsed["datasets"] if "Waterbodies" in d["name"]]
        assert waterbodies
        assert any(
            "https://dx.doi.org/10.26186/148920" in d["citation"] for d in waterbodies
        )
        assert any(
            "https://doi.org/10.3390/rs13081437" in d["paper_citation"]
            for d in waterbodies
        )
        assert any(
            "https://knowledge.dea.ga.gov.au/data/product/dea-waterbodies-landsat/"
            in d["sources"]
            for d in waterbodies
        )
        assert all(d["modification"] for d in parsed["datasets"])
        expected = _footer(frame)
        for key in FOOTER_KEYS:
            assert footer[key.encode()] == expected[key].encode()
        keys = {k.decode() for k in footer} - {"geo", "pandas", "ARROW:schema"}
        assert keys == {*FOOTER_KEYS, "dea_attribution"}
