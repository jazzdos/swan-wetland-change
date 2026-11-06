from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import geopandas as gpd
import pandas as pd
import pyarrow.parquet as pq
import pyproj
import pytest
from pydantic import ValidationError
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from tests.conftest import REQUIRED_ASSETS
from wetland_change import pipeline as pipeline_module
from wetland_change.aoi import AoiPolygon
from wetland_change.catalogue.item import SceneItem, parse_timestamp
from wetland_change.config import (
    AoiConfig,
    OutputConfig,
    PipelineConfig,
    StacConfig,
    WaterConfig,
)
from wetland_change.ledger import (
    RUN_KIND_BACKFILL,
    attempts_so_far,
    compact_ledger,
    entry_for,
    exhausted_ids,
    latest_entries,
    read_ledger,
    read_ledger_parts,
    rejected_entry,
    retry_ids,
    seen_keys,
    watermark,
    write_ledger,
)
from wetland_change.manifest import KIND_REQUEUE, KIND_SCORE, RunManifest, new_run_id
from wetland_change.outputs.changes import CHANGE_COLUMNS, change_path
from wetland_change.outputs.geoparquet import observation_path, write_observations
from wetland_change.pipeline import (
    RunIdReusedError,
    _with_later_dates,
    backfill_once,
    requeue_once,
    run_once,
    score_changes,
    score_once,
)
from wetland_change.raster.read import Grid, RasterioReader
from wetland_change.runtime import Environment
from wetland_change.stac import PlaceholderBaseUrlError
from wetland_change.stats import ObservationRow
from wetland_change.store import OutputStore
from wetland_change.verify.run import latest_run_id

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


WATER = WaterConfig()
OPERATION_EPSG = 32750


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
        water=WATER,
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


class CreatedAwareClient(FakeClient):
    """Honours the `created` lower bound on main searches, as Earth Search does.

    Scenes behind the watermark are then reachable only through the `ids` lookup.
    """

    def __init__(self, items: list[dict[str, Any]]) -> None:
        super().__init__(items)
        self.id_searches: list[list[str]] = []
        self.main_returned: list[list[str]] = []

    def search(self, **kwargs: Any) -> FakeSearch:
        if "ids" in kwargs:
            self.id_searches.append(list(kwargs["ids"]))
            return super().search(**kwargs)
        bound = kwargs["query"].get("created", {}).get("gte")
        kept = [
            i
            for i in self.items
            if bound is None
            or parse_timestamp(i["properties"]["created"]) >= parse_timestamp(bound)
        ]
        self.main_returned.append([i["id"] for i in kept])
        return FakeSearch(kept)


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
    store: OutputStore | None = None,
    build_catalogue: bool = True,
    config_text: str = "# test\n",
) -> RunManifest:
    cfg = cfg or _config(tmp_path)
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text(config_text)
    return run_once(
        cfg,
        client=client,
        reader=reader or RasterioReader(),
        store=store or OutputStore(cfg.output.root),
        polygons=polygons,
        now=now,
        config_path=config_path,
        build_catalogue=build_catalogue,
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


def test_run_once_observation_footer_records_operation_epsg_and_water(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    manifest = _run(
        tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW
    )
    footer = pq.read_schema(tmp_path / "out" / manifest.observation_files[0]).metadata
    assert footer[b"operation_epsg"] == b"32750"
    assert footer[b"source_epsg"] == b"32750"
    assert footer[b"geometry_epsg"] == b"4326"
    water = WATER.for_polygon("ramsar-52")
    assert json.loads(footer[b"water_settings"]) == {
        "ramsar-52": {"method": water.method, "threshold": water.threshold}
    }


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
        # the third failure exhausts the scene; later quiet runs keep reporting it
        exhausted = [broken["id"]] if attempt >= 3 else []
        assert manifest.exhausted_items == exhausted
        assert manifest.exhausted == len(exhausted)
        written = json.loads(store.read_bytes(f"runs/{manifest.run_id}.json"))
        assert written["operation_epsg"] == 32750
        assert written["exhausted"] == len(exhausted)
        assert written["exhausted_items"] == exhausted
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


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_run_once_refuses_reused_run_id(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    client = FakeClient([fixture_item])
    _run(tmp_path, client, polygons, NOW)
    before = _snapshot(tmp_path / "out")
    assert before
    with pytest.raises(RunIdReusedError, match="already has"):
        _run(tmp_path, client, polygons, NOW)
    assert _snapshot(tmp_path / "out") == before


def test_run_once_refuses_a_run_id_with_ledger_parts_but_no_manifest(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    client = FakeClient([fixture_item])
    _run(tmp_path, client, polygons, NOW)
    root = tmp_path / "out"
    manifest_file = root / "runs" / f"{new_run_id(NOW)}.json"
    assert manifest_file.is_file()
    manifest_file.unlink()
    before = _snapshot(root)
    ledger_files = [name for name in before if name.startswith("ledger")]
    assert ledger_files
    with pytest.raises(RunIdReusedError, match="already has"):
        _run(tmp_path, client, polygons, NOW)
    after = _snapshot(root)
    assert sorted(after) == sorted(before)
    assert not manifest_file.exists()
    assert {name: after[name] for name in ledger_files} == {
        name: before[name] for name in ledger_files
    }


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
            water=WATER,
            operation_epsg=OPERATION_EPSG,
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
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    assert again.files == [expected]
    assert (out / expected).read_bytes() == before
    second = _run(tmp_path, client, _polygons(fixture_polygon), NOW + timedelta(days=1))
    assert second.change_rows == 0
    assert second.change_files == []
    assert (out / expected).read_bytes() == before


class _ReadRecordingStore(OutputStore):
    def __init__(self, root: str) -> None:
        super().__init__(root)
        self.read_paths: list[str] = []

    def read_bytes(self, relpath: str) -> bytes:
        self.read_paths.append(relpath)
        return super().read_bytes(relpath)


def test_run_once_scoring_skips_observation_files_from_other_months(
    fixture_item: dict[str, Any],
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    probe = _probe(tmp_path, fixture_item, fixture_polygon)
    store = _ReadRecordingStore(str(tmp_path / "out"))
    off_month = probe["datetime"].replace(
        month=4 if probe["datetime"].month != 4 else 5
    )
    geometry = _polygons(fixture_polygon)[0].geometry_4326
    off_path = write_observations(
        [
            ObservationRow(
                polygon_id="ramsar-52",
                site=probe["site"],
                aoi_layer=probe["aoi_layer"],
                item_id="off-month",
                product_uri=probe["product_uri"],
                datetime=off_month,
                tile=probe["tile"],
                processing_baseline=probe["processing_baseline"],
                scene_coverage=1.0,
                n_pixels=1000,
                n_clear=950,
                valid_fraction=0.95,
                cloud_fraction=0.05,
                water_ha_index=probe["water_ha_index"],
                water_ha_scl=probe["water_ha_scl"],
                ndwi_median=probe["ndwi_median"],
                mndwi_median=probe["mndwi_median"],
                ndvi_median=probe["ndvi_median"],
                dea_wo_agreement=None,
                geometry_4326=geometry,
                run_id="seed",
            )
        ],
        store,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    seeded = entry_for(
        dataclasses.replace(fixture_scene, item_id="off-month", datetime=off_month),
        status="succeeded",
        attempts=1,
        run_id="seed",
        processed_at=NOW - timedelta(days=30),
        n_rows=1,
        observation_path=off_path,
        # A seeded row is backfill, so run_once does not take it for a daily
        # run that crashed and rescore its date.
        run_kind=RUN_KIND_BACKFILL,
    )
    write_ledger([seeded], store, run_id="seed")
    store.read_paths.clear()
    manifest = _run(
        tmp_path,
        FakeClient([fixture_item]),
        _polygons(fixture_polygon),
        NOW,
        store=store,
    )
    (new_path,) = manifest.observation_files
    assert new_path in store.read_paths
    assert off_path not in store.read_paths


def _stored_frame(rows: list[tuple[str, str]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "polygon_id": [polygon for polygon, _ in rows],
            "datetime": pd.to_datetime(
                [f"{day}T02:26:39Z" for _, day in rows], utc=True
            ),
        }
    )
    frame["acq_date"] = frame["datetime"].dt.date
    return frame


def test_with_later_dates_adds_later_same_polygon_and_month() -> None:
    frame = _stored_frame(
        [
            ("a", "2025-10-05"),
            ("a", "2026-10-02"),
            ("a", "2026-10-27"),
            ("a", "2024-10-01"),
            ("a", "2026-09-30"),
            ("a", "2026-11-02"),
            ("b", "2026-10-15"),
        ]
    )
    assert _with_later_dates(frame, [date(2025, 10, 5)]) == [
        date(2025, 10, 5),
        date(2026, 10, 2),
        date(2026, 10, 27),
    ]


def test_with_later_dates_uses_the_earliest_wanted_date_per_polygon_and_month() -> None:
    frame = _stored_frame(
        [
            ("a", "2026-10-05"),
            ("a", "2026-10-10"),
            ("a", "2026-10-20"),
            ("b", "2026-10-12"),
            ("b", "2026-10-25"),
        ]
    )
    assert _with_later_dates(frame, [date(2026, 10, 10), date(2026, 10, 12)]) == [
        date(2026, 10, 10),
        date(2026, 10, 12),
        date(2026, 10, 20),
        date(2026, 10, 25),
    ]


def test_with_later_dates_ignores_dates_with_no_stored_rows() -> None:
    frame = _stored_frame([("a", "2026-10-05"), ("a", "2026-10-20")])
    assert _with_later_dates(frame, [date(2026, 10, 1)]) == []


def _change_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(f.relative_to(root)): f.read_bytes()
        for f in sorted(root.rglob("*"))
        if f.is_file()
    }


def test_retried_earlier_scene_leaves_change_files_equal_to_full_rescore(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    probe = _probe(tmp_path, fixture_item, fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    _seed_october_baseline(store, probe, fixture_polygon)
    fixed = copy.deepcopy(fixture_item)
    fixed["id"] = f"{fixture_item['id']}_A"
    fixed["properties"]["s2:product_uri"] = f"A_{fixture_item['id']}.SAFE"
    fixed["properties"]["datetime"] = "2026-10-20T02:26:39Z"
    fixed["properties"]["created"] = "2026-10-28T08:00:00.000Z"
    fixed["properties"]["updated"] = "2026-10-28T08:00:00.000Z"
    broken = copy.deepcopy(fixed)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    polygons = _polygons(fixture_polygon)
    out = tmp_path / "out"
    expected = change_path(2026, probe["tile"], probe["item_id"])

    first = _run(tmp_path, FakeClient([broken, fixture_item]), polygons, NOW)
    assert first.failed == 1
    assert first.change_files == [expected]
    first_n = gpd.read_parquet(out / expected)["baseline_n"].unique().tolist()

    second = _run(
        tmp_path, FakeClient([fixed, fixture_item]), polygons, NOW + timedelta(days=1)
    )
    assert second.failed == 0
    assert expected in second.change_files
    rescored_n = gpd.read_parquet(out / expected)["baseline_n"].unique().tolist()
    assert rescored_n != first_n

    snapshot = _change_bytes(out / "changes")
    score_changes(
        store,
        min_valid_fraction=_config(tmp_path).water.min_valid_fraction,
        water=WATER,
        operation_epsg=OPERATION_EPSG,
    )
    assert _change_bytes(out / "changes") == snapshot


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
    assert recorded["operation_epsg"] == 32750
    assert recorded["change_rows"] == 2
    assert recorded["change_files_removed"] == []
    assert pq.read_schema(tmp_path / "out" / expected).names[0] == "polygon_id"
    with pytest.raises(ValueError, match="manifest"):
        _score_once(tmp_path, start, end, later)


FIXED_ENVIRONMENT = Environment(
    runtime={
        "python": "3.12.0",
        "gdal": "3.0",
        "proj": "9.0",
        "geopandas": "1",
        "rasterio": "1",
        "pyarrow": "1",
        "numpy": "2",
    },
    uv_lock_sha256="a" * 64,
    git_commit="b" * 40,
)


def _fix_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "wetland_change.pipeline.capture_environment", lambda: FIXED_ENVIRONMENT
    )


def _assert_fixed_environment(payload: dict[str, Any]) -> None:
    assert payload["runtime"] == FIXED_ENVIRONMENT.runtime
    assert payload["uv_lock_sha256"] == "a" * 64
    assert payload["git_commit"] == "b" * 40


def test_run_and_score_manifests_record_the_environment(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fix_environment(monkeypatch)
    store = OutputStore(str(tmp_path / "out"))
    run = _run(tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW)
    _assert_fixed_environment(_manifest_json(store, run.run_id))
    start = datetime(2026, 10, 26, tzinfo=UTC)
    end = datetime(2026, 10, 28, 23, 59, 59, tzinfo=UTC)
    score = _score_once(tmp_path, start, end, NOW + timedelta(days=1))
    _assert_fixed_environment(_manifest_json(store, score.run_id))


def test_requeue_manifest_records_the_environment(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = copy.deepcopy(fixture_item)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    store = _exhaust(tmp_path, broken, _polygons(fixture_polygon))
    _fix_environment(monkeypatch)
    manifest = _requeue(
        tmp_path, store, NOW + timedelta(days=10), item_ids=[broken["id"]]
    )
    _assert_fixed_environment(_manifest_json(store, manifest.run_id))


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


def test_backfill_and_score_refuse_placeholder_base_url_on_s3(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    assert "invalid" in cfg.catalogue.base_url
    store = cast(OutputStore, SimpleNamespace(uri="s3://bucket/"))
    start = datetime(2026, 10, 26, tzinfo=UTC)
    end = datetime(2026, 10, 28, tzinfo=UTC)
    with pytest.raises(PlaceholderBaseUrlError, match="base_url"):
        backfill_once(
            cfg,
            start=start,
            end=end,
            client=FakeClient([]),
            reader=RasterioReader(),
            store=store,
            polygons=[],
            now=NOW,
            config_path=tmp_path / "pipeline.toml",
        )
    with pytest.raises(PlaceholderBaseUrlError, match="base_url"):
        score_once(
            cfg,
            start=start,
            end=end,
            store=store,
            now=NOW,
            config_path=tmp_path / "pipeline.toml",
        )


def _exhaust(
    tmp_path: Path, broken: dict[str, Any], polygons: list[AoiPolygon]
) -> OutputStore:
    client = FakeClient([broken])
    for attempt in range(1, 4):
        _run(tmp_path, client, polygons, NOW + timedelta(days=attempt))
    store = OutputStore(str(tmp_path / "out"))
    assert exhausted_ids(read_ledger(store)) == [broken["id"]]
    return store


def _requeue(
    tmp_path: Path,
    store: OutputStore,
    now: datetime,
    *,
    item_ids: list[str],
    all_exhausted: bool = False,
) -> RunManifest:
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")
    return requeue_once(
        _config(tmp_path),
        item_ids=item_ids,
        all_exhausted=all_exhausted,
        store=store,
        now=now,
        config_path=config_path,
    )


def test_requeue_once_brings_an_exhausted_scene_back(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    broken = copy.deepcopy(fixture_item)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    store = _exhaust(tmp_path, broken, polygons)
    ledger_before = sorted(p for p in store.list_files("ledger"))

    when = NOW + timedelta(days=10)
    manifest = _requeue(tmp_path, store, when, item_ids=[broken["id"]])

    assert manifest.kind == KIND_REQUEUE
    assert manifest.run_id == "20261108T100000Z"
    assert manifest.requeued_items == [broken["id"]]
    assert manifest.exhausted == 0
    assert manifest.exhausted_items == []
    assert manifest.finished_at == when
    assert manifest.watermark_before is None
    assert manifest.watermark_after is None
    assert len(manifest.ledger_files) == 1
    written = json.loads(store.read_bytes(f"runs/{manifest.run_id}.json"))
    assert written["kind"] == KIND_REQUEUE
    assert written["operation_epsg"] == 32750
    assert written["requeued_items"] == [broken["id"]]
    # earlier ledger files are untouched; the requeue only adds one
    assert [p for p in store.list_files("ledger") if p in ledger_before] == (
        ledger_before
    )
    ledger = read_ledger(store)
    assert retry_ids(ledger) == [broken["id"]]
    assert attempts_so_far(ledger, broken["id"]) == 0

    fixed = _run(
        tmp_path,
        FakeClient([fixture_item]),
        polygons,
        when + timedelta(days=1),
    )
    assert fixed.processed == 1
    assert fixed.exhausted == 0
    latest = read_ledger(store).to_pandas().sort_values("processed_at").iloc[-1]
    assert latest["item_id"] == fixture_item["id"]
    assert latest["status"] == "succeeded"


def test_requeue_once_all_exhausted(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    broken = copy.deepcopy(fixture_item)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    store = _exhaust(tmp_path, broken, _polygons(fixture_polygon))
    manifest = _requeue(
        tmp_path,
        store,
        NOW + timedelta(days=10),
        item_ids=[],
        all_exhausted=True,
    )
    assert manifest.requeued_items == [broken["id"]]
    assert exhausted_ids(read_ledger(store)) == []


def test_requeue_once_refuses_nothing_to_requeue(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "out"))
    with pytest.raises(ValueError, match="nothing to requeue"):
        _requeue(tmp_path, store, NOW, item_ids=[], all_exhausted=True)


def test_requeue_once_needs_exactly_one_selection(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    broken = copy.deepcopy(fixture_item)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    store = _exhaust(tmp_path, broken, _polygons(fixture_polygon))
    when = NOW + timedelta(days=10)
    with pytest.raises(ValueError, match="either"):
        _requeue(tmp_path, store, when, item_ids=[], all_exhausted=False)
    with pytest.raises(ValueError, match="either"):
        _requeue(tmp_path, store, when, item_ids=[broken["id"]], all_exhausted=True)


def test_requeue_once_rejects_an_unknown_id(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    broken = copy.deepcopy(fixture_item)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    store = _exhaust(tmp_path, broken, _polygons(fixture_polygon))
    with pytest.raises(ValueError, match="nope"):
        _requeue(tmp_path, store, NOW + timedelta(days=10), item_ids=["nope"])


def test_requeue_once_refuses_reused_run_id(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    broken = copy.deepcopy(fixture_item)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    store = _exhaust(tmp_path, broken, _polygons(fixture_polygon))
    when = NOW + timedelta(days=10)
    _requeue(tmp_path, store, when, item_ids=[broken["id"]])
    with pytest.raises(ValueError, match="run id"):
        _requeue(tmp_path, store, when, item_ids=[broken["id"]])


def _exhausted_behind_the_watermark(
    fixture_item: dict[str, Any], polygons: list[AoiPolygon], tmp_path: Path
) -> tuple[dict[str, Any], dict[str, Any], OutputStore]:
    """Exhaust a broken scene, then let a later scene push the watermark past it."""
    broken = copy.deepcopy(fixture_item)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    store = _exhaust(tmp_path, broken, polygons)
    late = copy.deepcopy(fixture_item)
    stamp = "2026-11-02T08:00:00.000Z"
    late["id"] = f"{fixture_item['id']}_late"
    late["properties"]["s2:product_uri"] = f"late_{late['id']}.SAFE"
    late["properties"]["created"] = stamp
    late["properties"]["updated"] = stamp
    manifest = _run(
        tmp_path,
        CreatedAwareClient([broken, late]),
        polygons,
        NOW + timedelta(days=5),
    )
    assert manifest.processed == 1
    assert watermark(read_ledger(store)) == parse_timestamp(stamp)
    return broken, late, store


def test_requeued_scene_behind_the_watermark_is_reached_by_id(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    broken, late, store = _exhausted_behind_the_watermark(
        fixture_item, polygons, tmp_path
    )
    _requeue(tmp_path, store, NOW + timedelta(days=10), item_ids=[broken["id"]])

    client = CreatedAwareClient([fixture_item, late])
    manifest = _run(tmp_path, client, polygons, NOW + timedelta(days=11))

    # the created bound hides the scene from the main search; only the id lookup
    assert client.main_returned == [[late["id"]]]
    assert client.id_searches == [[broken["id"]]]
    assert (manifest.processed, manifest.failed) == (1, 0)
    assert manifest.exhausted_items == []
    latest = latest_entries(read_ledger(store)).set_index("item_id")
    assert latest.loc[fixture_item["id"], "status"] == "succeeded"


def test_requeued_scene_behind_the_watermark_exhausts_again(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    broken, late, store = _exhausted_behind_the_watermark(
        fixture_item, polygons, tmp_path
    )
    _requeue(tmp_path, store, NOW + timedelta(days=10), item_ids=[broken["id"]])

    client = CreatedAwareClient([broken, late])
    for attempt in range(1, 4):
        manifest = _run(tmp_path, client, polygons, NOW + timedelta(days=10 + attempt))
        assert manifest.failed == 1
        assert manifest.exhausted_items == ([broken["id"]] if attempt == 3 else [])
    assert client.id_searches == [[broken["id"]]] * 3
    assert all(returned == [late["id"]] for returned in client.main_returned)
    assert exhausted_ids(read_ledger(store)) == [broken["id"]]


# --- one ledger read per run, one catalogue build, bounded part count ---------


class LedgerCountingStore(OutputStore):
    """Counts `list_files("ledger")` calls and `read_bytes` under `ledger/`."""

    def __init__(self, root: str) -> None:
        super().__init__(root)
        self.ledger_listings = 0
        self.ledger_reads: list[str] = []
        self.writes: list[str] = []

    def list_files(self, prefix: str) -> list[str]:
        if prefix.strip("/") == "ledger":
            self.ledger_listings += 1
        return super().list_files(prefix)

    def read_bytes(self, relpath: str) -> bytes:
        if relpath.startswith("ledger/"):
            self.ledger_reads.append(relpath)
        return super().read_bytes(relpath)

    def write_bytes(self, relpath: str, data: bytes, **kwargs: Any) -> str:
        self.writes.append(relpath)
        return super().write_bytes(relpath, data, **kwargs)

    def reset(self) -> None:
        self.ledger_listings = 0
        self.ledger_reads.clear()
        self.writes.clear()


def _parts(store: OutputStore) -> list[str]:
    return [p for p in store.list_files("ledger") if p.endswith(".parquet")]


def _assert_one_ledger_read(store: LedgerCountingStore, parts_before: int) -> None:
    assert store.ledger_listings == 1
    assert len(store.ledger_reads) == parts_before
    assert len(set(store.ledger_reads)) == parts_before


def _counting_store(tmp_path: Path) -> LedgerCountingStore:
    return LedgerCountingStore(str(tmp_path / "out"))


def test_run_once_lists_and_reads_the_ledger_once_on_a_processed_day(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    items = _four_scenes(fixture_item)
    polygons = _polygons(fixture_polygon)
    store = _counting_store(tmp_path)
    _run(tmp_path, FakeClient(items[:2]), polygons, NOW, store=store)
    before = len(_parts(store))
    assert before == 2
    store.reset()
    manifest = _run(
        tmp_path, FakeClient(items), polygons, NOW + timedelta(days=1), store=store
    )
    assert manifest.processed == 2
    _assert_one_ledger_read(store, before)


def test_run_once_lists_and_reads_the_ledger_once_on_a_no_op_day(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    store = _counting_store(tmp_path)
    client = FakeClient([fixture_item])
    _run(tmp_path, client, polygons, NOW, store=store)
    store.reset()
    manifest = _run(tmp_path, client, polygons, NOW + timedelta(days=1), store=store)
    assert manifest.processed == 0
    _assert_one_ledger_read(store, 1)


def test_run_once_lists_and_reads_the_ledger_once_with_a_rejected_item(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    store = _counting_store(tmp_path)
    _run(tmp_path, FakeClient([fixture_item]), polygons, NOW, store=store)
    store.reset()
    manifest = _run(
        tmp_path,
        FakeClient([_wrong_collection(fixture_item), fixture_item]),
        polygons,
        NOW + timedelta(days=1),
        store=store,
    )
    assert manifest.rejected == 1
    _assert_one_ledger_read(store, 1)


def test_backfill_once_lists_and_reads_the_ledger_once(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    store = _counting_store(tmp_path)
    other = copy.deepcopy(fixture_item)
    other["id"] = f"{fixture_item['id']}_B"
    other["properties"]["s2:product_uri"] = f"B_{other['id']}.SAFE"
    _run(tmp_path, FakeClient([other]), polygons, NOW, store=store)
    store.reset()
    config_path = tmp_path / "pipeline.toml"
    manifest = backfill_once(
        _config(tmp_path),
        start=datetime(2026, 10, 26, tzinfo=UTC),
        end=datetime(2026, 10, 28, 23, 59, 59, tzinfo=UTC),
        client=FakeClient([_wrong_collection(fixture_item), fixture_item]),
        reader=RasterioReader(),
        store=store,
        polygons=polygons,
        now=NOW + timedelta(days=1),
        config_path=config_path,
    )
    assert (manifest.processed, manifest.rejected) == (1, 1)
    _assert_one_ledger_read(store, 1)


def test_requeue_once_lists_and_reads_the_ledger_once(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    broken = copy.deepcopy(fixture_item)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    _exhaust(tmp_path, broken, _polygons(fixture_polygon))
    store = _counting_store(tmp_path)
    before = len(_parts(store))
    store.reset()
    manifest = _requeue(
        tmp_path, store, NOW + timedelta(days=10), item_ids=[], all_exhausted=True
    )
    assert manifest.exhausted == 0
    _assert_one_ledger_read(store, before)


def test_run_once_without_catalogue_writes_no_stac_files(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    store = _counting_store(tmp_path)
    manifest = _run(
        tmp_path,
        FakeClient([fixture_item]),
        _polygons(fixture_polygon),
        NOW,
        store=store,
        build_catalogue=False,
    )
    assert manifest.processed == 1
    assert not [p for p in store.writes if p.startswith("stac/")]
    assert not (tmp_path / "out" / "stac").exists()


def test_a_second_no_op_run_writes_no_stac_objects(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    store = _counting_store(tmp_path)
    client = FakeClient([fixture_item])
    _run(tmp_path, client, polygons, NOW, store=store)
    assert [p for p in store.writes if p.startswith("stac/")]
    store.reset()
    _run(tmp_path, client, polygons, NOW + timedelta(days=1), store=store)
    assert store.writes
    assert not [p for p in store.writes if p.startswith("stac/")]


def _compacted(store: OutputStore) -> list[str]:
    return [p for p in _parts(store) if p.startswith("ledger/compacted/")]


def test_compaction_bounds_the_part_count_without_reprocessing_scenes(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    items = _four_scenes(fixture_item)
    polygons = _polygons(fixture_polygon)
    reference = tmp_path / "reference"
    reference.mkdir()
    for count in (1, 2, 3, 4):
        _run(
            reference,
            FakeClient(items[:count]),
            polygons,
            NOW + timedelta(days=count),
        )
    expected = read_ledger(OutputStore(str(reference / "out")))

    monkeypatch.setattr("wetland_change.pipeline.COMPACT_MIN_PARTS", 2)
    store = OutputStore(str(tmp_path / "out"))
    for count in (1, 2, 3, 4):
        manifest = _run(
            tmp_path,
            FakeClient(items[:count]),
            polygons,
            NOW + timedelta(days=count),
            store=store,
        )
        assert manifest.processed == 1
        compacted = _compacted(store)
        fresh = [p for p in _parts(store) if p not in compacted]
        assert len(compacted) <= 1
        assert len(fresh) < 2
    assert len(_compacted(store)) == 1

    ledger = read_ledger(store)
    assert seen_keys(ledger) == seen_keys(expected)
    assert sorted(ledger["item_id"].to_pylist()) == sorted(
        expected["item_id"].to_pylist()
    )
    again = _run(
        tmp_path, FakeClient(items), polygons, NOW + timedelta(days=5), store=store
    )
    assert (again.discovered, again.processed, again.skipped_seen) == (0, 0, 4)


class FailingLedgerDeleteStore(OutputStore):
    def delete(self, relpath: str) -> bool:
        if relpath.startswith("ledger/"):
            raise OSError("delete refused")
        return super().delete(relpath)


def test_a_failed_compaction_delete_does_not_fail_the_run(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    items = _four_scenes(fixture_item)
    polygons = _polygons(fixture_polygon)
    monkeypatch.setattr("wetland_change.pipeline.COMPACT_MIN_PARTS", 2)
    store = FailingLedgerDeleteStore(str(tmp_path / "out"))
    _run(tmp_path, FakeClient(items[:1]), polygons, NOW, store=store)
    manifest = _run(
        tmp_path, FakeClient(items[:2]), polygons, NOW + timedelta(days=1), store=store
    )
    assert manifest.processed == 1
    assert store.exists(f"runs/{manifest.run_id}.json")
    assert len(_compacted(store)) == 1
    ledger = read_ledger(store)
    assert sorted(ledger["item_id"].to_pylist()) == sorted(
        [items[0]["id"], items[1]["id"]]
    )


def test_run_once_refuses_a_run_id_whose_parts_were_compacted_away(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    items = _four_scenes(fixture_item)
    polygons = _polygons(fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    with pytest.raises(KeyboardInterrupt):
        _run(
            tmp_path,
            FakeClient(items),
            polygons,
            NOW,
            reader=InterruptingReader(interrupt_on=3),
        )
    table, paths = read_ledger_parts(store)
    compact_ledger(store, table, paths, run_id="20261101T000000Z", min_parts=1)
    assert not any("ledger_20261029T100000Z_" in p for p in store.list_files("ledger"))
    assert not store.exists("runs/20261029T100000Z.json")
    before = store.list_files("")
    with pytest.raises(ValueError, match="run id"):
        _run(tmp_path, FakeClient(items), polygons, NOW)
    assert store.list_files("") == before


# --- a run that did not finish is finished by the next run -----------------


def _flaky(
    monkeypatch: pytest.MonkeyPatch, name: str, *, failures: int = 1, after: int = 0
) -> list[dict[str, Any]]:
    """Patch `wetland_change.pipeline.<name>` to raise OSError on calls
    `after + 1` to `after + failures` (1-based) and delegate otherwise.

    Returns the kwargs of every call, so a test can count calls and read the
    arguments.
    """
    real = getattr(pipeline_module, name)
    calls: list[dict[str, Any]] = []

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        if after < len(calls) <= after + failures:
            raise OSError(f"injected {name} failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(f"wetland_change.pipeline.{name}", wrapper)
    return calls


def _spy(monkeypatch: pytest.MonkeyPatch, name: str) -> list[dict[str, Any]]:
    return _flaky(monkeypatch, name, failures=0)


def _flagged_store(
    tmp_path: Path, item: dict[str, Any], fixture_polygon: BaseGeometry
) -> tuple[dict[str, Any], OutputStore, str]:
    """The probe row, a store seeded so the fixture scene is flagged, and the
    expected change file path."""
    probe = _probe(tmp_path, item, fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    _seed_october_baseline(store, probe, fixture_polygon)
    return probe, store, change_path(2026, probe["tile"], probe["item_id"])


def _control_bytes(
    tmp_path: Path,
    items: list[dict[str, Any]],
    probe: dict[str, Any],
    fixture_polygon: BaseGeometry,
    expected: list[str],
) -> dict[str, bytes]:
    """Change files from one uninterrupted run on a separate clean store."""
    control = tmp_path / "control"
    control.mkdir()
    _seed_october_baseline(OutputStore(str(control / "out")), probe, fixture_polygon)
    _run(control, FakeClient(items), _polygons(fixture_polygon), NOW)
    return {path: (control / "out" / path).read_bytes() for path in expected}


def _later_day_item(item: dict[str, Any]) -> dict[str, Any]:
    """A copy of the fixture scene acquired a day later, as its own scene."""
    later = copy.deepcopy(item)
    later["id"] = f"{item['id']}_next"
    later["properties"]["s2:product_uri"] = f"next_{item['id']}.SAFE"
    acquired = parse_timestamp(item["properties"]["datetime"]) + timedelta(days=1)
    created = _z(NOW - timedelta(hours=2))
    later["properties"]["datetime"] = _z(acquired)
    later["properties"]["created"] = created
    later["properties"]["updated"] = created
    return later


def _manifest_json(store: OutputStore, run_id: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(store.read_bytes(f"runs/{run_id}.json"))
    return loaded


def _run_ids(store: OutputStore) -> list[str]:
    return [Path(p).stem for p in store.list_files("runs") if p.endswith(".json")]


RUN1 = new_run_id(NOW)
RUN2 = new_run_id(NOW + timedelta(days=1))
RUN3 = new_run_id(NOW + timedelta(days=2))


def test_scoring_failure_is_finished_by_the_next_run(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe, store, expected = _flagged_store(tmp_path, fixture_item, fixture_polygon)
    control = _control_bytes(
        tmp_path, [fixture_item], probe, fixture_polygon, [expected]
    )
    polygons = _polygons(fixture_polygon)
    client = FakeClient([fixture_item])
    _flaky(monkeypatch, "score_changes")
    with pytest.raises(OSError, match="score_changes"):
        _run(tmp_path, client, polygons, NOW, store=store)
    out = tmp_path / "out"
    assert not store.exists(f"runs/{RUN1}.json")
    assert not (out / expected).exists()
    assert set(read_ledger(store).to_pandas()["status"]) == {"succeeded"}

    second = _run(tmp_path, client, polygons, NOW + timedelta(days=1), store=store)
    assert (second.discovered, second.skipped_seen) == (0, 1)
    assert (out / expected).read_bytes() == control[expected]
    assert second.recovered_runs == [RUN1]
    assert second.recovered_by is None
    recovered = _manifest_json(store, RUN1)
    assert recovered["processed"] == 1
    assert recovered["failed"] == 0
    assert recovered["observation_files"] == [
        f"observations/year=2026/tile={probe['tile']}/obs_{probe['item_id']}.parquet"
    ]
    assert recovered["change_files"] == [expected]
    assert recovered["change_rows"] == 2
    assert recovered["recovered_by"] == RUN2
    assert recovered["finished_at"] is not None
    assert recovered["kind"] == "run"
    assert recovered["skipped_seen"] == 0
    assert recovered["skipped_filter"] == 0
    assert recovered["watermark_before"] is None
    assert recovered["watermark_after"] is None
    assert recovered["recovered_runs"] == []
    assert recovered["operation_epsg"] is None
    assert recovered["ledger_files"] == [
        f"ledger/year=2026/ledger_{RUN1}_00000.parquet"
    ]
    assert latest_run_id(store) == RUN1


def test_a_recovered_manifest_does_not_take_the_recovering_runs_config(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe, store, _ = _flagged_store(tmp_path, fixture_item, fixture_polygon)
    polygons = _polygons(fixture_polygon)
    client = FakeClient([fixture_item])
    _flaky(monkeypatch, "score_changes")
    with pytest.raises(OSError, match="score_changes"):
        _run(tmp_path, client, polygons, NOW, store=store, config_text="# a\n")

    second = _run(
        tmp_path,
        client,
        polygons,
        NOW + timedelta(days=1),
        store=store,
        config_text="# b\n",
    )
    recovered = _manifest_json(store, RUN1)
    assert recovered["recovered_by"] == RUN2
    assert recovered["package_version"] is None
    assert recovered["config_sha256"] is None
    assert recovered["runtime"] is None
    assert recovered["uv_lock_sha256"] is None
    assert recovered["git_commit"] is None
    own = _manifest_json(store, RUN2)
    assert "python" in own["runtime"]
    assert own["config_sha256"] == hashlib.sha256(b"# b\n").hexdigest()
    assert own["package_version"] is not None
    assert second.config_sha256 == own["config_sha256"]


def test_manifest_write_failure_is_finished_by_the_next_run(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store, expected = _flagged_store(tmp_path, fixture_item, fixture_polygon)
    polygons = _polygons(fixture_polygon)
    client = FakeClient([fixture_item])
    _flaky(monkeypatch, "write_manifest")
    with pytest.raises(OSError, match="write_manifest"):
        _run(tmp_path, client, polygons, NOW, store=store)
    written = (tmp_path / "out" / expected).read_bytes()
    assert not store.exists(f"runs/{RUN1}.json")

    second = _run(tmp_path, client, polygons, NOW + timedelta(days=1), store=store)
    assert second.recovered_runs == [RUN1]
    assert (tmp_path / "out" / expected).read_bytes() == written
    recovered = _manifest_json(store, RUN1)
    assert recovered["processed"] == 1
    assert recovered["change_files"] == [expected]


def test_a_persistent_scoring_failure_is_finished_by_the_third_run(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store, expected = _flagged_store(tmp_path, fixture_item, fixture_polygon)
    polygons = _polygons(fixture_polygon)
    client = FakeClient([fixture_item])
    _flaky(monkeypatch, "score_changes", failures=2)
    with pytest.raises(OSError):
        _run(tmp_path, client, polygons, NOW, store=store)
    with pytest.raises(OSError):
        _run(tmp_path, client, polygons, NOW + timedelta(days=1), store=store)
    assert not (tmp_path / "out" / expected).exists()

    third = _run(tmp_path, client, polygons, NOW + timedelta(days=2), store=store)
    assert (tmp_path / "out" / expected).exists()
    assert third.recovered_runs == [RUN1]
    # Run 2 raised before writing any ledger row, so it has nothing to recover
    # and gets no manifest.
    assert sorted(_run_ids(store)) == [RUN1, RUN3]
    assert _manifest_json(store, RUN1)["recovered_by"] == RUN3


def test_a_raise_inside_the_scene_loop_loses_no_scene(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [fixture_item, _later_day_item(fixture_item)]
    probe, store, _ = _flagged_store(tmp_path, items[0], fixture_polygon)
    expected = [change_path(2026, probe["tile"], item["id"]) for item in items]
    control = _control_bytes(tmp_path, items, probe, fixture_polygon, expected)
    polygons = _polygons(fixture_polygon)
    client = FakeClient(items)
    # The checkpoint of the second scene fails.
    _flaky(monkeypatch, "write_ledger", after=1)
    with pytest.raises(OSError, match="write_ledger"):
        _run(tmp_path, client, polygons, NOW, store=store)
    assert [r for r in read_ledger(store).to_pandas()["item_id"]] == [items[0]["id"]]
    assert not store.exists(f"runs/{RUN1}.json")

    second = _run(tmp_path, client, polygons, NOW + timedelta(days=1), store=store)
    assert (second.skipped_seen, second.processed) == (1, 1)
    assert second.recovered_runs == [RUN1]
    assert second.observation_files == [
        f"observations/year=2026/tile={probe['tile']}/obs_{items[1]['id']}.parquet"
    ]
    recovered = _manifest_json(store, RUN1)
    assert recovered["processed"] == 1
    assert recovered["observation_files"] == [
        f"observations/year=2026/tile={probe['tile']}/obs_{items[0]['id']}.parquet"
    ]
    for path in expected:
        assert (tmp_path / "out" / path).read_bytes() == control[path]
    assert sorted(second.change_files) == sorted(expected)


def test_a_finished_recovery_is_not_repeated(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store, _ = _flagged_store(tmp_path, fixture_item, fixture_polygon)
    polygons = _polygons(fixture_polygon)
    client = FakeClient([fixture_item])
    _flaky(monkeypatch, "write_manifest")
    with pytest.raises(OSError):
        _run(tmp_path, client, polygons, NOW, store=store)
    _run(tmp_path, client, polygons, NOW + timedelta(days=1), store=store)
    before = store.read_bytes(f"runs/{RUN1}.json")

    calls = _spy(monkeypatch, "score_changes")
    third = _run(tmp_path, client, polygons, NOW + timedelta(days=2), store=store)
    assert calls == []
    assert third.recovered_runs == []
    assert store.read_bytes(f"runs/{RUN1}.json") == before
    assert sorted(_run_ids(store)) == [RUN1, RUN2, RUN3]


def test_a_normal_run_recovers_nothing_and_writes_one_manifest(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path / "out"))
    manifest = _run(
        tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW
    )
    assert manifest.recovered_runs == []
    assert manifest.recovered_by is None
    assert _run_ids(store) == [RUN1]


def test_backfill_rows_without_a_manifest_are_not_recovered(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe, store, _ = _flagged_store(tmp_path, fixture_item, fixture_polygon)
    cfg = _config(tmp_path)
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")
    polygons = _polygons(fixture_polygon)
    backfilled = backfill_once(
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
    assert store.delete(f"runs/{backfilled.run_id}.json")
    assert _run_ids(store) == []

    calls = _spy(monkeypatch, "score_changes")
    later = _run(
        tmp_path,
        FakeClient([fixture_item]),
        polygons,
        NOW + timedelta(days=1),
        store=store,
    )
    assert calls == []
    assert later.recovered_runs == []
    assert _run_ids(store) == [RUN2]


def test_unfinished_run_and_new_scenes_are_scored_in_one_call(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_item = fixture_item
    next_item = _later_day_item(fixture_item)
    probe, store, _ = _flagged_store(tmp_path, first_item, fixture_polygon)
    polygons = _polygons(fixture_polygon)
    client = FakeClient([first_item])
    _flaky(monkeypatch, "score_changes")
    with pytest.raises(OSError):
        _run(tmp_path, client, polygons, NOW, store=store)

    calls = _spy(monkeypatch, "score_changes")
    client.items = [first_item, next_item]
    second = _run(tmp_path, client, polygons, NOW + timedelta(days=1), store=store)
    assert second.processed == 1
    assert second.recovered_runs == [RUN1]
    (call,) = calls
    assert set(call["dates"]) == {probe["datetime"].date(), date(2026, 10, 28)}
    assert call["rescore_later"] is True


def test_a_crashed_run_with_only_failed_rows_is_recovered_without_scoring(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = copy.deepcopy(fixture_item)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    items = [_wrong_collection(fixture_item), broken]
    polygons = _polygons(fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    client = FakeClient(items)
    _flaky(monkeypatch, "write_manifest")
    with pytest.raises(OSError):
        _run(tmp_path, client, polygons, NOW, store=store)

    calls = _spy(monkeypatch, "score_changes")
    second = _run(tmp_path, client, polygons, NOW + timedelta(days=1), store=store)
    assert calls == []
    assert second.recovered_runs == [RUN1]
    recovered = _manifest_json(store, RUN1)
    assert recovered["processed"] == 0
    assert recovered["failed"] == 1
    assert recovered["rejected"] == 1
    assert recovered["discovered"] == 1
    assert recovered["observation_files"] == []
    assert recovered["change_files"] == []
    assert recovered["change_rows"] == 0
    assert recovered["recovered_by"] == RUN2


# --- unchanged rejections are logged once ------------------------------------

STAMP = "2026-10-28T08:30:21.681234Z"


def _stamped_wrong(fixture_item: dict[str, Any], stamp: str = STAMP) -> dict[str, Any]:
    wrong = _wrong_collection(fixture_item)
    wrong["properties"]["updated"] = stamp
    return wrong


def _rejected_rows(store: OutputStore, item_id: str) -> pd.DataFrame:
    frame = read_ledger(store).to_pandas()
    return frame[(frame["item_id"] == item_id) & (frame["status"] == "rejected")]


def test_an_unchanged_rejection_is_not_written_again(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    wrong = _stamped_wrong(fixture_item)
    polygons = _polygons(fixture_polygon)
    store = _counting_store(tmp_path)
    client = FakeClient([wrong])
    first = _run(tmp_path, client, polygons, NOW, store=store)
    assert first.rejected == 1
    parts_before = _parts(store)
    store.reset()
    second = _run(tmp_path, client, polygons, NOW + timedelta(days=1), store=store)
    assert (second.rejected, second.skipped_seen) == (0, 1)
    assert second.ledger_files == []
    _assert_one_ledger_read(store, len(parts_before))
    assert _parts(store) == parts_before
    rows = _rejected_rows(store, wrong["id"])
    assert len(rows) == 1
    assert rows["updated"].iloc[0].to_pydatetime() == parse_timestamp(STAMP)


def test_an_unchanged_rejection_does_not_add_a_part_beside_a_new_scene(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    wrong = _stamped_wrong(fixture_item)
    polygons = _polygons(fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    _run(tmp_path, FakeClient([wrong]), polygons, NOW, store=store)
    second = _run(
        tmp_path,
        FakeClient([wrong, fixture_item]),
        polygons,
        NOW + timedelta(days=1),
        store=store,
    )
    assert (second.rejected, second.processed, second.skipped_seen) == (0, 1, 1)
    assert second.ledger_files == [
        f"ledger/year=2026/ledger_{second.run_id}_00000.parquet"
    ]


def test_a_rejected_item_with_a_new_updated_is_logged_again(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    wrong = _stamped_wrong(fixture_item)
    polygons = _polygons(fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    _run(tmp_path, FakeClient([wrong]), polygons, NOW, store=store)
    newer = _stamped_wrong(fixture_item, "2026-10-29T01:02:03.5Z")
    second = _run(
        tmp_path, FakeClient([newer]), polygons, NOW + timedelta(days=1), store=store
    )
    assert second.rejected == 1
    rows = _rejected_rows(store, wrong["id"])
    stamps = sorted(v.to_pydatetime() for v in rows["updated"])
    assert stamps == [
        parse_timestamp(STAMP),
        parse_timestamp("2026-10-29T01:02:03.5Z"),
    ]


def test_a_legacy_rejected_row_without_updated_is_relogged_once(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    wrong = _stamped_wrong(fixture_item)
    polygons = _polygons(fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    client = FakeClient([wrong])
    first = _run(tmp_path, client, polygons, NOW, store=store)
    reason = read_ledger(store).to_pandas()["error"].iloc[0]
    for path in first.ledger_files:
        (tmp_path / "out" / path).unlink()
    legacy = rejected_entry(
        wrong["id"], reason, run_id="legacy", processed_at=NOW - timedelta(days=1)
    )
    write_ledger([legacy], store, run_id="legacy")

    second = _run(tmp_path, client, polygons, NOW + timedelta(days=1), store=store)
    assert (second.rejected, second.skipped_seen) == (1, 0)
    third = _run(tmp_path, client, polygons, NOW + timedelta(days=2), store=store)
    assert (third.rejected, third.skipped_seen) == (0, 1)
    assert third.ledger_files == []
    assert len(_rejected_rows(store, wrong["id"])) == 2


def test_backfill_once_does_not_write_an_unchanged_rejection_again(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    wrong = _stamped_wrong(fixture_item)
    store = OutputStore(str(tmp_path / "out"))
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")

    def backfill(now: datetime) -> RunManifest:
        return backfill_once(
            _config(tmp_path),
            start=datetime(2026, 10, 26, tzinfo=UTC),
            end=datetime(2026, 10, 28, 23, 59, 59, tzinfo=UTC),
            client=FakeClient([wrong]),
            reader=RasterioReader(),
            store=store,
            polygons=_polygons(fixture_polygon),
            now=now,
            config_path=config_path,
        )

    first = backfill(NOW)
    assert first.rejected == 1
    second = backfill(NOW + timedelta(days=1))
    assert (second.rejected, second.skipped_seen) == (0, 1)
    assert second.ledger_files == []
    assert len(_rejected_rows(store, wrong["id"])) == 1
