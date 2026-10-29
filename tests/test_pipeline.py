from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyproj
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from tests.conftest import REQUIRED_ASSETS
from wetland_change.aoi import AoiPolygon
from wetland_change.config import (
    AoiConfig,
    OutputConfig,
    PipelineConfig,
    StacConfig,
    WaterConfig,
)
from wetland_change.ledger import read_ledger, retry_ids
from wetland_change.manifest import RunManifest
from wetland_change.pipeline import run_once
from wetland_change.raster.read import RasterioReader
from wetland_change.store import OutputStore

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
TO_4326 = pyproj.Transformer.from_crs(32750, 4326, always_xy=True).transform


class FakeSearch:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    def items_as_dicts(self) -> Iterator[dict[str, Any]]:
        yield from copy.deepcopy(self._items)


class FakeClient:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items

    def search(self, **kwargs: Any) -> FakeSearch:
        if "ids" in kwargs:
            return FakeSearch([i for i in self.items if i["id"] in kwargs["ids"]])
        return FakeSearch(self.items)


def _config(tmp_path: Path) -> PipelineConfig:
    return PipelineConfig(
        stac=StacConfig(
            endpoint="https://example.invalid",
            collection="sentinel-2-c1-l2a",
            cloud_cover_max=20.0,
            required_assets=REQUIRED_ASSETS,
        ),
        aoi=AoiConfig(
            ramsar_path=Path("unused"),
            waterbodies_path=Path("unused"),
            site_prefixes=[],
        ),
        water=WaterConfig(),
        output=OutputConfig(root=str(tmp_path / "out")),
    )


def _polygons(fixture_polygon: BaseGeometry) -> list[AoiPolygon]:
    lake = AoiPolygon(
        "ramsar-52",
        "Forrestdale & Thomsons Lakes",
        "ramsar",
        fixture_polygon,
        shapely_transform(TO_4326, fixture_polygon),
    )
    off_scene = box(500000, 6442000, 500300, 6442300)
    far = AoiPolygon(
        "ramsar-99",
        "Elsewhere",
        "ramsar",
        off_scene,
        shapely_transform(TO_4326, off_scene),
    )
    return [lake, far]


def _run(
    tmp_path: Path, client: FakeClient, polygons: list[AoiPolygon], now: datetime
) -> RunManifest:
    cfg = _config(tmp_path)
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")
    return run_once(
        cfg,
        client=client,
        reader=RasterioReader(),
        store=OutputStore(cfg.output.root),
        polygons=polygons,
        now=now,
        config_path=config_path,
    )


def test_run_once_end_to_end_offline(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    manifest = _run(
        tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW
    )
    assert manifest.run_id == "20261029T100000Z"
    assert (manifest.discovered, manifest.processed, manifest.failed) == (1, 1, 0)
    assert manifest.watermark_before is None
    assert manifest.watermark_after is not None
    assert len(manifest.observation_files) == 1
    assert len(manifest.ledger_files) == 1
    out = tmp_path / "out"
    assert (out / "runs" / "20261029T100000Z.json").exists()
    frame = gpd.read_parquet(out / manifest.observation_files[0])
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["polygon_id"] == "ramsar-52"
    assert row["run_id"] == manifest.run_id
    assert row["valid_fraction"] > 0.9
    assert row["water_ha_scl"] > 5.0
    assert frame.crs.to_epsg() == 4326


def test_rerun_is_incremental(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    client = FakeClient([fixture_item])
    first = _run(tmp_path, client, _polygons(fixture_polygon), NOW)
    second = _run(tmp_path, client, _polygons(fixture_polygon), NOW + timedelta(days=1))
    assert second.watermark_before == first.watermark_after
    assert (second.discovered, second.processed, second.skipped_seen) == (0, 0, 1)
    assert second.observation_files == []
    assert sorted((tmp_path / "out" / "observations").rglob("*.parquet")) == [
        tmp_path / "out" / first.observation_files[0]
    ]


def test_failed_scene_is_recorded_and_retried_three_times(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    broken = copy.deepcopy(fixture_item)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    client = FakeClient([broken])
    store = OutputStore(str(tmp_path / "out"))
    for attempt in range(1, 5):
        manifest = _run(
            tmp_path, client, _polygons(fixture_polygon), NOW + timedelta(days=attempt)
        )
        ledger = read_ledger(store)
        if attempt <= 3:
            assert manifest.failed == 1
            assert retry_ids(ledger) == ([broken["id"]] if attempt < 3 else [])
        else:
            assert manifest.failed == 0
            assert manifest.discovered == 0
    assert manifest.observation_files == []


def test_scaling_mismatch_fails_the_scene(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    tampered = copy.deepcopy(fixture_item)
    tampered["assets"]["green"]["raster:bands"][0]["offset"] = 0.0
    manifest = _run(tmp_path, FakeClient([tampered]), _polygons(fixture_polygon), NOW)
    assert manifest.failed == 1
    ledger = read_ledger(OutputStore(str(tmp_path / "out"))).to_pandas()
    assert "offset" in ledger["error"].iloc[0]


def test_rejected_items_are_ledgered(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    wrong = copy.deepcopy(fixture_item)
    wrong["collection"] = "sentinel-2-l2a"
    manifest = _run(tmp_path, FakeClient([wrong]), _polygons(fixture_polygon), NOW)
    assert (manifest.rejected, manifest.processed) == (1, 0)
    ledger = read_ledger(OutputStore(str(tmp_path / "out"))).to_pandas()
    assert ledger["status"].tolist() == ["rejected"]
