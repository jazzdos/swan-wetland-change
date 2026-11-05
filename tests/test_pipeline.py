from __future__ import annotations

import copy
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
from wetland_change.aoi import AoiPolygon
from wetland_change.catalogue.item import parse_timestamp
from wetland_change.config import (
    AoiConfig,
    OutputConfig,
    PipelineConfig,
    StacConfig,
    WaterConfig,
)
from wetland_change.ledger import (
    attempts_so_far,
    exhausted_ids,
    latest_entries,
    read_ledger,
    retry_ids,
    watermark,
)
from wetland_change.manifest import KIND_REQUEUE, KIND_SCORE, RunManifest
from wetland_change.outputs.changes import CHANGE_COLUMNS, change_path
from wetland_change.outputs.geoparquet import observation_path, write_observations
from wetland_change.pipeline import (
    _with_later_dates,
    backfill_once,
    requeue_once,
    run_once,
    score_changes,
    score_once,
)
from wetland_change.raster.read import Grid, RasterioReader
from wetland_change.stac import PlaceholderBaseUrlError
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
        # the third failure exhausts the scene; later quiet runs keep reporting it
        exhausted = [broken["id"]] if attempt >= 3 else []
        assert manifest.exhausted_items == exhausted
        assert manifest.exhausted == len(exhausted)
        written = json.loads(store.read_bytes(f"runs/{manifest.run_id}.json"))
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
    score_changes(store, min_valid_fraction=_config(tmp_path).water.min_valid_fraction)
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
