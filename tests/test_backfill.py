from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry.base import BaseGeometry
from typer.testing import CliRunner

from tests.test_pipeline import NOW, FakeSearch, _config, _polygons, _run
from wetland_change.aoi import AoiPolygon
from wetland_change.catalogue.item import parse_timestamp
from wetland_change.cli import app
from wetland_change.config import load_config
from wetland_change.ledger import (
    attempts_so_far,
    exhausted_ids,
    read_ledger,
    retry_ids,
    watermark,
)
from wetland_change.manifest import RunManifest
from wetland_change.pipeline import backfill_once
from wetland_change.raster.read import RasterioReader, RasterReader
from wetland_change.store import OutputStore
from wetland_change.windows import Grid

START = datetime(2026, 10, 26, tzinfo=UTC)
END = datetime(2026, 10, 28, 23, 59, 59, 999999, tzinfo=UTC)


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _item(
    base: dict[str, Any], item_id: str, *, acquired: datetime, created: datetime
) -> dict[str, Any]:
    item = copy.deepcopy(base)
    item["id"] = item_id
    item["properties"]["datetime"] = _stamp(acquired)
    item["properties"]["created"] = _stamp(created)
    item["properties"]["updated"] = _stamp(created)
    return item


class ServiceClient:
    """A catalogue that honours the `created` and `datetime` filters."""

    def __init__(
        self, items: list[dict[str, Any]], *, honour_filters: bool = True
    ) -> None:
        self.items = items
        self.honour_filters = honour_filters
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> FakeSearch:
        self.calls.append(kwargs)
        if "ids" in kwargs:
            return FakeSearch([i for i in self.items if i["id"] in kwargs["ids"]])
        found = list(self.items)
        if self.honour_filters:
            created = kwargs.get("query", {}).get("created", {}).get("gte")
            if created is not None:
                floor = parse_timestamp(created)
                found = [
                    i
                    for i in found
                    if parse_timestamp(i["properties"]["created"]) >= floor
                ]
            if "datetime" in kwargs:
                lo, hi = (parse_timestamp(p) for p in kwargs["datetime"].split("/"))
                found = [
                    i
                    for i in found
                    if lo <= parse_timestamp(i["properties"]["datetime"]) <= hi
                ]
        return FakeSearch(found)


def _backfill(
    tmp_path: Path,
    client: ServiceClient,
    polygons: list[AoiPolygon],
    now: datetime,
    *,
    start: datetime = START,
    end: datetime = END,
    reader: RasterReader | None = None,
) -> RunManifest:
    cfg = _config(tmp_path)
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")
    return backfill_once(
        cfg,
        start=start,
        end=end,
        client=client,
        reader=reader or RasterioReader(),
        store=OutputStore(cfg.output.root),
        polygons=polygons,
        now=now,
        config_path=config_path,
    )


def _range_items(base: dict[str, Any]) -> list[dict[str, Any]]:
    created = datetime(2026, 10, 29, 8, 0, tzinfo=UTC)
    return [
        _item(base, "in_start", acquired=START, created=created),
        _item(
            base,
            "in_mid",
            acquired=datetime(2026, 10, 27, 2, 26, tzinfo=UTC),
            created=created,
        ),
        _item(
            base, "out_before", acquired=START - timedelta(seconds=1), created=created
        ),
        _item(
            base, "out_after", acquired=END + timedelta(microseconds=1), created=created
        ),
    ]


def test_backfill_processes_only_in_range_items(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    client = ServiceClient(_range_items(fixture_item), honour_filters=False)
    manifest = _backfill(tmp_path, client, _polygons(fixture_polygon), NOW)
    assert (
        manifest.discovered,
        manifest.processed,
        manifest.failed,
        manifest.skipped_filter,
    ) == (2, 2, 0, 2)
    expected = {"obs_in_mid.parquet", "obs_in_start.parquet"}
    assert {Path(p).name for p in manifest.observation_files} == expected
    out = tmp_path / "out"
    assert {p.name for p in (out / "observations").rglob("*.parquet")} == expected
    assert client.calls[0]["datetime"] == (
        "2026-10-26T00:00:00Z/2026-10-28T23:59:59.999999Z"
    )
    assert "created" not in client.calls[0].get("query", {})
    ledger = read_ledger(OutputStore(str(out))).to_pandas()
    assert set(ledger["run_kind"]) == {"backfill"}
    assert set(ledger["status"]) == {"succeeded"}
    assert manifest.kind == "backfill"
    assert manifest.datetime_start == START
    assert manifest.datetime_end == END
    assert manifest.ledger_files == [
        f"ledger/year=2026/ledger_{manifest.run_id}_00000.parquet",
        f"ledger/year=2026/ledger_{manifest.run_id}_00001.parquet",
    ]
    recorded = json.loads((out / "runs" / f"{manifest.run_id}.json").read_text())
    assert recorded["kind"] == "backfill"


def test_repeated_backfill_writes_nothing_new(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    client = ServiceClient(_range_items(fixture_item), honour_filters=False)
    polygons = _polygons(fixture_polygon)
    _backfill(tmp_path, client, polygons, NOW)
    obs = tmp_path / "out" / "observations"
    before = {p: p.stat().st_mtime_ns for p in obs.rglob("*.parquet")}
    assert len(before) == 2
    second = _backfill(tmp_path, client, polygons, NOW + timedelta(hours=1))
    assert second.processed == 0
    assert second.observation_files == []
    assert second.ledger_files == []
    assert second.skipped_seen == 2
    assert {p: p.stat().st_mtime_ns for p in obs.rglob("*.parquet")} == before
    recorded = json.loads(
        (tmp_path / "out" / "runs" / f"{second.run_id}.json").read_text()
    )
    assert recorded["processed"] == 0


def test_backfill_does_not_move_the_daily_watermark(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    daily_a = _item(
        fixture_item,
        "daily_a",
        acquired=datetime(2026, 10, 19, 2, 0, tzinfo=UTC),
        created=datetime(2026, 10, 20, 0, 0, tzinfo=UTC),
    )
    old_b = _item(
        fixture_item,
        "old_b",
        acquired=datetime(2026, 1, 15, 2, 0, tzinfo=UTC),
        created=datetime(2026, 10, 28, 0, 0, tzinfo=UTC),
    )
    late_c = _item(
        fixture_item,
        "late_c",
        acquired=datetime(2026, 10, 24, 2, 0, tzinfo=UTC),
        created=datetime(2026, 10, 25, 0, 0, tzinfo=UTC),
    )
    first = _run(
        tmp_path,
        ServiceClient([daily_a]),
        polygons,
        datetime(2026, 10, 21, 10, 0, tzinfo=UTC),
    )
    stamp = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    assert first.processed == 1
    assert first.watermark_after == stamp

    backfill = _backfill(
        tmp_path,
        ServiceClient([daily_a, old_b]),
        polygons,
        datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 31, 23, 59, 59, 999999, tzinfo=UTC),
    )
    assert backfill.processed == 1
    assert backfill.watermark_before == backfill.watermark_after == stamp
    assert watermark(read_ledger(store)) == stamp

    daily = _run(
        tmp_path,
        ServiceClient([daily_a, old_b, late_c]),
        polygons,
        datetime(2026, 10, 29, 10, 0, tzinfo=UTC),
    )
    assert (daily.processed, daily.skipped_seen) == (1, 2)
    assert [Path(p).name for p in daily.observation_files] == ["obs_late_c.parquet"]


class _Interrupted(BaseException):
    pass


class InterruptingReader(RasterioReader):
    def __init__(self, interrupt_on: int) -> None:
        super().__init__()
        self.interrupt_on = interrupt_on
        self.calls = 0

    def open_grid(self, href: str) -> Grid:
        self.calls += 1
        if self.calls == self.interrupt_on:
            raise _Interrupted
        return super().open_grid(href)


def test_interrupted_backfill_resumes(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    items = [
        _item(
            fixture_item,
            f"bf_{n}",
            acquired=datetime(2026, 10, 27, 2, n, tzinfo=UTC),
            created=datetime(2026, 10, 29, 8, n, tzinfo=UTC),
        )
        for n in range(3)
    ]
    client = ServiceClient(items)
    with pytest.raises(_Interrupted):
        _backfill(tmp_path, client, polygons, NOW, reader=InterruptingReader(2))
    out = tmp_path / "out"
    ledger = read_ledger(OutputStore(str(out))).to_pandas()
    assert ledger["item_id"].tolist() == ["bf_0"]
    assert ledger["status"].tolist() == ["succeeded"]
    assert not (out / "runs").exists()

    second = _backfill(tmp_path, client, polygons, NOW + timedelta(hours=1))
    assert (second.processed, second.skipped_seen) == (2, 1)
    names = {p.name for p in (out / "observations").rglob("*.parquet")}
    assert names == {f"obs_bf_{n}.parquet" for n in range(3)}


def test_backfill_refuses_to_resume_with_the_same_now(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    items = [
        _item(
            fixture_item,
            f"bf_{n}",
            acquired=datetime(2026, 10, 27, 2, n, tzinfo=UTC),
            created=datetime(2026, 10, 29, 8, n, tzinfo=UTC),
        )
        for n in range(3)
    ]
    client = ServiceClient(items)
    with pytest.raises(_Interrupted):
        _backfill(tmp_path, client, polygons, NOW, reader=InterruptingReader(2))
    store = OutputStore(str(tmp_path / "out"))
    before = read_ledger(store)["item_id"].to_pylist()
    assert before == ["bf_0"]

    with pytest.raises(ValueError, match="already has"):
        _backfill(tmp_path, client, polygons, NOW)
    assert read_ledger(store)["item_id"].to_pylist() == before

    second = _backfill(tmp_path, client, polygons, NOW + timedelta(seconds=1))
    assert (second.processed, second.skipped_seen) == (2, 1)
    assert sorted(read_ledger(store)["item_id"].to_pylist()) == [
        "bf_0",
        "bf_1",
        "bf_2",
    ]

    with pytest.raises(ValueError, match="already has"):
        _backfill(tmp_path, client, polygons, NOW + timedelta(seconds=1))


def test_backfill_retries_failed_scene_on_rerun(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    broken = _item(
        fixture_item,
        "broken",
        acquired=datetime(2026, 10, 27, 2, 0, tzinfo=UTC),
        created=datetime(2026, 10, 29, 8, 0, tzinfo=UTC),
    )
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    client = ServiceClient([broken])
    polygons = _polygons(fixture_polygon)
    first = _backfill(tmp_path, client, polygons, NOW)
    assert first.failed == 1
    second = _backfill(tmp_path, client, polygons, NOW + timedelta(hours=1))
    assert (second.discovered, second.failed) == (1, 1)
    store = OutputStore(str(tmp_path / "out"))
    assert attempts_so_far(read_ledger(store), "broken") == 2


def test_backfill_reports_scene_exhausted_on_third_attempt(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    broken = _item(
        fixture_item,
        "broken",
        acquired=datetime(2026, 10, 27, 2, 0, tzinfo=UTC),
        created=datetime(2026, 10, 29, 8, 0, tzinfo=UTC),
    )
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    client = ServiceClient([broken])
    polygons = _polygons(fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    for attempt in range(1, 4):
        manifest = _backfill(tmp_path, client, polygons, NOW + timedelta(hours=attempt))
        assert manifest.failed == 1
        exhausted = ["broken"] if attempt == 3 else []
        assert manifest.exhausted_items == exhausted
        assert manifest.exhausted == len(exhausted)
        written = json.loads(store.read_bytes(f"runs/{manifest.run_id}.json"))
        assert written["exhausted_items"] == exhausted
    assert exhausted_ids(read_ledger(store)) == ["broken"]
    assert retry_ids(read_ledger(store)) == []


def test_backfill_rejects_naive_or_reversed_range(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    client = ServiceClient([fixture_item])
    polygons = _polygons(fixture_polygon)
    with pytest.raises(ValueError):
        _backfill(tmp_path, client, polygons, NOW, start=datetime(2026, 10, 26))
    with pytest.raises(ValueError):
        _backfill(tmp_path, client, polygons, NOW, start=END, end=START)


@pytest.mark.live
def test_live_backfill_over_the_27_october_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(root)
    cfg = load_config(root / "config" / "pipeline.toml")
    assert cfg.aoi.ramsar_path.exists(), "run: uv run python scripts/fetch_aoi.py"
    out = tmp_path / "out"
    result = CliRunner().invoke(
        app,
        [
            "backfill",
            "--start",
            "2026-10-26",
            "--end",
            "2026-10-28",
            "--config",
            "config/pipeline.toml",
            "--output-root",
            str(out),
        ],
    )
    assert result.exit_code in (0, 2), (result.output, result.exception)
    manifests = sorted((out / "runs").glob("*.json"))
    assert len(manifests) == 1
    payload = json.loads(manifests[0].read_text())
    assert payload["kind"] == "backfill"
    assert payload["processed"] >= 1
    assert payload["observation_files"]
    for name in payload["observation_files"]:
        assert (out / name).exists(), name
    assert payload["output_root_override"] == str(out)
