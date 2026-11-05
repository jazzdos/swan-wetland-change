from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
from shapely.geometry import box

from wetland_change.outputs.geoparquet import (
    OBSERVATION_COLUMNS,
    observation_path,
    rows_to_frame,
    to_geoparquet_bytes,
    write_observations,
)
from wetland_change.stats import ObservationRow
from wetland_change.store import OutputStore

WHEN = datetime(2026, 10, 27, 2, 26, 46, tzinfo=UTC)


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
    relpath = write_observations(ROWS, store)
    assert relpath == observation_path(2026, "50HLK", ROWS[0].item_id)
    back = gpd.read_parquet(tmp_path / relpath)
    assert len(back) == 2
    assert back.crs.to_epsg() == 4326
    assert back["water_ha_scl"].tolist() == [0.6, 0.6]


def test_geo_metadata_declares_covering_bbox(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_observations(ROWS, store)
    meta = json.loads(pq.read_schema(tmp_path / relpath).metadata[b"geo"])
    assert meta["version"] == "1.1.0"
    assert meta["columns"]["geometry"]["covering"]["bbox"]["xmin"] == ["bbox", "xmin"]
    assert meta["columns"]["geometry"]["crs"] is not None


def test_geoparquet_validator_accepts_file(tmp_path: Path) -> None:
    exe = shutil.which("geoparquet-validator")
    if exe is None:
        pytest.skip("geoparquet-validator not on PATH; run under uv")
    store = OutputStore(str(tmp_path))
    relpath = write_observations(ROWS, store)
    result = subprocess.run(
        [exe, "check", str(tmp_path / relpath), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_duckdb_reads_bbox_column(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_observations(ROWS, store)
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
    write_observations([_row("ramsar-56", 115.93), _row("ramsar-52", 115.82)], store)
    second = "S2C_T50HLK_20261030T022351_L2A"
    write_observations(
        [
            _row("ramsar-60", 115.50, item_id=second),
            _row("ramsar-61", 116.10, item_id=second),
        ],
        store,
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
    assert to_geoparquet_bytes(frame) == to_geoparquet_bytes(
        rows_to_frame(list(reversed(ROWS)))
    )


def test_mixed_items_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="one file per item"):
        write_observations(
            [ROWS[0], _row("x", 115.0, item_id="other")], OutputStore(str(tmp_path))
        )
