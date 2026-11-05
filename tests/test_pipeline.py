from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyarrow.parquet as pq
import pyproj
import pytest
from pydantic import ValidationError
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
from wetland_change.ledger import read_ledger, retry_ids, watermark
from wetland_change.manifest import KIND_SCORE, RunManifest
from wetland_change.outputs.changes import CHANGE_COLUMNS, change_path
from wetland_change.outputs.geoparquet import observation_path, write_observations
from wetland_change.pipeline import backfill_once, run_once, score_changes, score_once
from wetland_change.raster.read import Grid, RasterioReader
from wetland_change.stats import ObservationRow
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


class RecordingClient(FakeClient):
    """Keeps the kwargs of every search that is not an `ids` retry lookup."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        super().__init__(items)
        self.main_searches: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> FakeSearch:
        if "ids" not in kwargs:
            self.main_searches.append(kwargs)
        return super().search(**kwargs)


class InterruptingReader(RasterioReader):
    """Raises KeyboardInterrupt in `open_grid` on the Nth call (1-based)."""

    def __init__(self, interrupt_on: int) -> None:
        super().__init__()
        self._interrupt_on = interrupt_on
        self._calls = 0

    def open_grid(self, href: str) -> Grid:
        self._calls += 1
        if self._calls == self._interrupt_on:
            raise KeyboardInterrupt
        return super().open_grid(href)


def _run(
    tmp_path: Path,
    client: FakeClient,
    polygons: list[AoiPolygon],
    now: datetime,
    *,
    cfg: PipelineConfig | None = None,
    reader: RasterioReader | None = None,
) -> RunManifest:
    cfg = cfg or _config(tmp_path)
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")
    return run_once(
        cfg,
        client=client,
        reader=reader or RasterioReader(),
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


def _wrong_collection(fixture_item: dict[str, Any]) -> dict[str, Any]:
    wrong = copy.deepcopy(fixture_item)
    wrong["id"] = f"{fixture_item['id']}_L2A"
    wrong["collection"] = "sentinel-2-l2a"
    return wrong


def test_rejected_items_and_scenes_get_separate_ledger_parts(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    wrong = _wrong_collection(fixture_item)
    manifest = _run(
        tmp_path,
        FakeClient([wrong, fixture_item]),
        _polygons(fixture_polygon),
        NOW,
    )
    assert (manifest.rejected, manifest.processed) == (1, 1)
    assert manifest.ledger_files == [
        f"ledger/year=2026/ledger_{manifest.run_id}_00000.parquet",
        f"ledger/year=2026/ledger_{manifest.run_id}_00001.parquet",
    ]
    ledger = read_ledger(OutputStore(str(tmp_path / "out"))).to_pandas()
    by_item = dict(zip(ledger["item_id"], ledger["status"], strict=True))
    assert by_item == {wrong["id"]: "rejected", fixture_item["id"]: "succeeded"}


def test_rejected_rows_survive_an_interrupt_on_the_first_scene(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    wrong = _wrong_collection(fixture_item)
    out = tmp_path / "out"
    with pytest.raises(KeyboardInterrupt):
        _run(
            tmp_path,
            FakeClient([wrong, fixture_item]),
            _polygons(fixture_polygon),
            NOW,
            reader=InterruptingReader(interrupt_on=1),
        )
    ledger = read_ledger(OutputStore(str(out))).to_pandas()
    assert ledger["status"].tolist() == ["rejected"]
    assert ledger["item_id"].tolist() == [wrong["id"]]
    assert len(list((out / "ledger").rglob("*.parquet"))) == 1


def test_run_once_tags_rows_and_manifest_as_run(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    manifest = _run(
        tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW
    )
    ledger = read_ledger(OutputStore(str(tmp_path / "out"))).to_pandas()
    assert ledger["run_kind"].tolist() == ["run"]
    assert manifest.kind == "run"
    assert manifest.output_root_override is None
    assert manifest.datetime_start is None
    assert manifest.ledger_files == [
        f"ledger/year=2026/ledger_{manifest.run_id}_00000.parquet"
    ]


def _four_scenes(fixture_item: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for i, suffix in enumerate("ABCD"):
        item = copy.deepcopy(fixture_item)
        stamp = f"2026-10-28T08:{i}0:00.000Z"
        item["id"] = f"{fixture_item['id']}_{suffix}"
        item["properties"]["s2:product_uri"] = f"{suffix}_{item['id']}.SAFE"
        item["properties"]["created"] = stamp
        item["properties"]["updated"] = stamp
        items.append(item)
    return items


def _z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def test_run_once_interrupted_keeps_finished_scenes_and_resumes(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    items = _four_scenes(fixture_item)
    polygons = _polygons(fixture_polygon)
    out = tmp_path / "out"
    store = OutputStore(str(out))
    with pytest.raises(KeyboardInterrupt):
        _run(
            tmp_path,
            FakeClient(items),
            polygons,
            NOW,
            reader=InterruptingReader(interrupt_on=3),
        )
    ledger = read_ledger(store).to_pandas()
    assert sorted(ledger["item_id"]) == [items[0]["id"], items[1]["id"]]
    assert set(ledger["status"]) == {"succeeded"}
    assert len(list((out / "ledger").rglob("*.parquet"))) == 2
    first_files = sorted((out / "observations").rglob("*.parquet"))
    assert len(first_files) == 2
    first_bytes = {f: f.read_bytes() for f in first_files}
    assert not (out / "runs" / "20261029T100000Z.json").exists()
    b_created = datetime(2026, 10, 28, 8, 10, tzinfo=UTC)
    assert watermark(read_ledger(store)) == b_created

    client = RecordingClient(items)
    second = _run(tmp_path, client, polygons, NOW + timedelta(days=1))
    assert (second.skipped_seen, second.processed) == (2, 2)
    assert sorted(second.observation_files) == [
        f"observations/year=2026/tile=50HLK/obs_{items[2]['id']}.parquet",
        f"observations/year=2026/tile=50HLK/obs_{items[3]['id']}.parquet",
    ]
    for f, data in first_bytes.items():
        assert f.read_bytes() == data
    (search,) = client.main_searches
    assert search["query"]["created"]["gte"] == _z(b_created - timedelta(days=1))
    final = read_ledger(store).to_pandas()
    assert len(final) == 4
    assert set(final["status"]) == {"succeeded"}


def test_run_without_watermark_bounds_discovery_to_lookback(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    client = RecordingClient([fixture_item])
    _run(tmp_path, client, polygons, NOW)
    (search,) = client.main_searches
    assert search["query"]["created"]["gte"] == _z(NOW - timedelta(days=30))

    short = tmp_path / "short"
    short.mkdir()
    cfg = _config(short)
    cfg = cfg.model_copy(
        update={"stac": cfg.stac.model_copy(update={"initial_lookback_days": 7})}
    )
    client = RecordingClient([fixture_item])
    _run(short, client, polygons, NOW, cfg=cfg)
    (search,) = client.main_searches
    assert search["query"]["created"]["gte"] == _z(NOW - timedelta(days=7))


def test_run_after_backfill_only_ledger_uses_lookback_and_skips_seeded_items(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    cfg = _config(tmp_path)
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")
    store = OutputStore(cfg.output.root)
    backfill_once(
        cfg,
        start=datetime(2026, 10, 26, tzinfo=UTC),
        end=datetime(2026, 10, 28, 23, 59, 59, tzinfo=UTC),
        client=FakeClient([fixture_item]),
        reader=RasterioReader(),
        store=store,
        polygons=polygons,
        now=NOW,
        config_path=config_path,
    )
    later = NOW + timedelta(days=1)
    client = RecordingClient([fixture_item])
    manifest = _run(tmp_path, client, polygons, later)
    assert manifest.watermark_before is None
    (search,) = client.main_searches
    assert search["query"]["created"]["gte"] == _z(later - timedelta(days=30))
    assert (manifest.processed, manifest.skipped_seen) == (0, 1)


def test_stac_config_rejects_zero_lookback() -> None:
    with pytest.raises(ValidationError):
        StacConfig(
            endpoint="https://example.invalid",
            collection="sentinel-2-c1-l2a",
            cloud_cover_max=20.0,
            initial_lookback_days=0,
        )


def test_run_once_refuses_reused_run_id(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    client = FakeClient([fixture_item])
    _run(tmp_path, client, polygons, NOW)
    with pytest.raises(ValueError, match="run id"):
        _run(tmp_path, client, polygons, NOW)


def test_run_once_records_output_root_override(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg = _config(tmp_path)
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")
    override = str(tmp_path / "out")
    manifest = run_once(
        cfg,
        client=FakeClient([fixture_item]),
        reader=RasterioReader(),
        store=OutputStore(cfg.output.root),
        polygons=_polygons(fixture_polygon),
        now=NOW,
        config_path=config_path,
        output_root_override=override,
    )
    assert manifest.output_root_override == override
    recorded = json.loads(
        (tmp_path / "out" / "runs" / f"{manifest.run_id}.json").read_text()
    )
    assert recorded["output_root_override"] == override
    assert recorded["kind"] == "run"
    assert (
        recorded["config_sha256"]
        == hashlib.sha256(config_path.read_bytes()).hexdigest()
    )


def _probe(
    tmp_path: Path, item: dict[str, Any], fixture_polygon: BaseGeometry
) -> dict[str, Any]:
    """The fixture scene's observation row, from a run in a scratch root."""
    probe = tmp_path / "probe"
    probe.mkdir()
    manifest = _run(probe, FakeClient([item]), _polygons(fixture_polygon), NOW)
    frame = gpd.read_parquet(probe / "out" / manifest.observation_files[0])
    row: dict[str, Any] = frame.iloc[0].to_dict()
    row["datetime"] = row["datetime"].to_pydatetime()
    return row


def _seed_october_baseline(
    store: OutputStore, probe: dict[str, Any], fixture_polygon: BaseGeometry
) -> None:
    """Six prior Octobers far from the fixture row, with nonzero spread."""
    geometry = _polygons(fixture_polygon)[0].geometry_4326
    for i in range(6):
        when = probe["datetime"].replace(year=2020 + i)
        write_observations(
            [
                ObservationRow(
                    polygon_id="ramsar-52",
                    site=probe["site"],
                    aoi_layer=probe["aoi_layer"],
                    item_id=f"prior-{2020 + i}",
                    product_uri=probe["product_uri"],
                    datetime=when,
                    tile=probe["tile"],
                    processing_baseline=probe["processing_baseline"],
                    scene_coverage=1.0,
                    n_pixels=1000,
                    n_clear=950,
                    valid_fraction=0.95,
                    cloud_fraction=0.05,
                    water_ha_index=probe["water_ha_index"] + 10.0 + 0.5 * i,
                    water_ha_scl=probe["water_ha_scl"],
                    ndwi_median=probe["ndwi_median"],
                    mndwi_median=probe["mndwi_median"],
                    ndvi_median=probe["ndvi_median"] + 0.3 + 0.01 * i,
                    dea_wo_agreement=None,
                    geometry_4326=geometry,
                    run_id="seed",
                )
            ],
            store,
        )


def test_run_once_writes_change_file_for_flagged_item(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    probe = _probe(tmp_path, fixture_item, fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    _seed_october_baseline(store, probe, fixture_polygon)
    client = FakeClient([fixture_item])
    manifest = _run(tmp_path, client, _polygons(fixture_polygon), NOW)
    expected = change_path(2026, probe["tile"], probe["item_id"])
    assert manifest.change_rows == 2
    assert manifest.change_files == [expected]
    out = tmp_path / "out"
    back = gpd.read_parquet(out / expected)
    assert set(CHANGE_COLUMNS) <= set(back.columns)
    assert sorted(back["metric"]) == ["ndvi_median", "water_ha_index"]
    recorded = json.loads((out / "runs" / f"{manifest.run_id}.json").read_text())
    assert recorded["change_rows"] == 2
    assert recorded["change_files"] == [expected]
    exe = shutil.which("geoparquet-validator")
    if exe is not None:
        result = subprocess.run(
            [exe, "check", str(out / expected), "--json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    before = (out / expected).read_bytes()
    again = score_changes(
        store,
        min_valid_fraction=_config(tmp_path).water.min_valid_fraction,
        dates=[probe["datetime"].date()],
    )
    assert again.files == [expected]
    assert (out / expected).read_bytes() == before
    second = _run(tmp_path, client, _polygons(fixture_polygon), NOW + timedelta(days=1))
    assert second.change_rows == 0
    assert second.change_files == []
    assert (out / expected).read_bytes() == before


def test_run_once_without_baseline_writes_no_changes(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    manifest = _run(
        tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW
    )
    assert manifest.change_rows == 0
    assert manifest.change_files == []
    assert not (tmp_path / "out" / "changes").exists()


def test_backfill_once_does_not_score(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    probe = _probe(tmp_path, fixture_item, fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    _seed_october_baseline(store, probe, fixture_polygon)
    cfg = _config(tmp_path)
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")
    manifest = backfill_once(
        cfg,
        start=datetime(2026, 10, 26, tzinfo=UTC),
        end=datetime(2026, 10, 28, 23, 59, 59, tzinfo=UTC),
        client=FakeClient([fixture_item]),
        reader=RasterioReader(),
        store=store,
        polygons=_polygons(fixture_polygon),
        now=NOW,
        config_path=config_path,
    )
    assert manifest.processed == 1
    assert manifest.change_rows == 0
    assert manifest.change_files == []
    assert not (tmp_path / "out" / "changes").exists()


def _score_once(
    tmp_path: Path, start: datetime, end: datetime, now: datetime
) -> RunManifest:
    cfg = _config(tmp_path)
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")
    return score_once(
        cfg,
        start=start,
        end=end,
        store=OutputStore(cfg.output.root),
        now=now,
        config_path=config_path,
        output_root_override="override-root",
    )


def test_score_once_scores_range_and_writes_manifest(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    probe = _probe(tmp_path, fixture_item, fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    first = _run(tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW)
    assert first.change_rows == 0
    _seed_october_baseline(store, probe, fixture_polygon)
    start = datetime(2026, 10, 26, tzinfo=UTC)
    end = datetime(2026, 10, 28, 23, 59, 59, tzinfo=UTC)
    later = NOW + timedelta(days=1)
    manifest = _score_once(tmp_path, start, end, later)
    expected = change_path(2026, probe["tile"], probe["item_id"])
    assert manifest.kind == KIND_SCORE
    assert manifest.change_rows == 2
    assert manifest.change_files == [expected]
    assert (manifest.datetime_start, manifest.datetime_end) == (start, end)
    assert manifest.watermark_before is None
    assert manifest.watermark_after is None
    assert (manifest.discovered, manifest.processed, manifest.failed) == (0, 0, 0)
    assert manifest.output_root_override == "override-root"
    assert (tmp_path / "out" / expected).exists()
    recorded = json.loads(
        (tmp_path / "out" / "runs" / f"{manifest.run_id}.json").read_text()
    )
    assert recorded["kind"] == "score"
    assert recorded["change_rows"] == 2
    assert recorded["change_files_removed"] == []
    assert pq.read_schema(tmp_path / "out" / expected).names[0] == "polygon_id"
    with pytest.raises(ValueError, match="manifest"):
        _score_once(tmp_path, start, end, later)


def test_score_once_records_removed_change_files(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    probe = _probe(tmp_path, fixture_item, fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    _run(tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW)
    _seed_october_baseline(store, probe, fixture_polygon)
    start = datetime(2026, 10, 26, tzinfo=UTC)
    end = datetime(2026, 10, 28, 23, 59, 59, tzinfo=UTC)
    first = _score_once(tmp_path, start, end, NOW + timedelta(days=1))
    expected = change_path(2026, probe["tile"], probe["item_id"])
    assert first.change_files == [expected]
    assert first.change_files_removed == []
    for year in range(2020, 2026):
        assert store.delete(observation_path(year, probe["tile"], f"prior-{year}"))
    second = _score_once(tmp_path, start, end, NOW + timedelta(days=2))
    assert second.change_files == []
    assert second.change_files_removed == [expected]
    assert not (tmp_path / "out" / expected).exists()
    recorded = json.loads(
        (tmp_path / "out" / "runs" / f"{second.run_id}.json").read_text()
    )
    assert recorded["change_files_removed"] == [expected]


def test_score_once_rejects_reversed_and_naive_ranges(tmp_path: Path) -> None:
    start = datetime(2026, 10, 28, tzinfo=UTC)
    end = datetime(2026, 10, 26, tzinfo=UTC)
    with pytest.raises(ValueError, match="after end"):
        _score_once(tmp_path, start, end, NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        _score_once(tmp_path, datetime(2026, 10, 26), end, NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        _score_once(tmp_path, start, datetime(2026, 10, 29), NOW)
