"""Idempotency and golden-output tests for the offline pipeline run."""

from __future__ import annotations

import copy
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import geopandas as gpd
import shapely.wkt
from pytest_regressions.data_regression import DataRegressionFixture
from shapely.geometry.base import BaseGeometry

from tests.test_pipeline import NOW, FakeClient, _polygons, _run
from wetland_change.ledger import read_ledger
from wetland_change.outputs.geoparquet import OBSERVATION_COLUMNS
from wetland_change.store import OutputStore


class RecordingClient(FakeClient):
    """FakeClient that records the kwargs of every search call."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        super().__init__(items)
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return super().search(**kwargs)


def _store(root: Path) -> OutputStore:
    return OutputStore(str(root / "out"))


def _snapshot(store: OutputStore) -> dict[str, bytes]:
    observations = store.list_files("observations")
    ledger = store.list_files("ledger")
    assert observations, "no observation files written"
    assert ledger, "no ledger files written"
    return {path: store.read_bytes(path) for path in observations + ledger}


def test_same_now_gives_byte_identical_outputs(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    stores = []
    for name in ("a", "b"):
        root = tmp_path / name
        root.mkdir()
        _run(
            root,
            FakeClient([copy.deepcopy(fixture_item)]),
            _polygons(fixture_polygon),
            NOW,
        )
        stores.append(_store(root))
    first, second = (_snapshot(store) for store in stores)
    assert first.keys() == second.keys()
    for path in first:
        assert first[path] == second[path], f"{path} differs between runs"
    assert any(p.startswith("observations/") for p in first)
    assert any(p.startswith("ledger/") for p in first)


def test_second_run_same_store_processes_nothing_and_changes_no_bytes(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    client = FakeClient([fixture_item])
    polygons = _polygons(fixture_polygon)
    _run(tmp_path, client, polygons, NOW)
    store = _store(tmp_path)
    _snapshot(store)
    before = {path: store.read_bytes(path) for path in store.list_files("")}
    second = _run(tmp_path, client, polygons, NOW + timedelta(days=1))
    assert (second.discovered, second.processed, second.failed) == (0, 0, 0)
    assert second.skipped_seen == 1
    assert second.observation_files == []
    for path, content in before.items():
        assert store.read_bytes(path) == content, f"{path} changed"
    new_files = set(store.list_files("")) - before.keys()
    assert new_files == {f"runs/{second.run_id}.json"}


def test_watermark_overlap_does_not_duplicate_processed_rows(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    polygons = _polygons(fixture_polygon)
    item_a = fixture_item
    item_b = copy.deepcopy(item_a)
    item_b["id"] = f"{item_a['id']}_B"
    item_b["properties"]["s2:product_uri"] = (
        f"{item_a['properties']['s2:product_uri']}_B"
    )
    item_b["properties"]["created"] = "2026-10-28T08:30:21.681Z"
    item_b["properties"]["updated"] = "2026-10-28T08:30:21.681Z"

    first = _run(tmp_path, RecordingClient([item_a]), polygons, NOW)
    assert first.watermark_after is not None
    client = RecordingClient([item_a, item_b])
    second = _run(tmp_path, client, polygons, NOW + timedelta(days=1))

    main_calls = [call for call in client.calls if "ids" not in call]
    expected = (
        (first.watermark_after - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    )
    assert main_calls[0]["query"]["created"]["gte"] == expected
    assert (second.discovered, second.skipped_seen, second.processed) == (1, 1, 1)

    ledger = read_ledger(_store(tmp_path)).to_pandas()
    succeeded = ledger[ledger["status"] == "succeeded"]
    assert not succeeded.duplicated(["item_id", "updated"]).any()
    assert set(succeeded["item_id"]) == {item_a["id"], item_b["id"]}


def _plain(value: Any) -> Any:
    """Numpy scalars to Python, datetimes to ISO text, floats rounded, NaN None."""
    if hasattr(value, "item") and not isinstance(value, datetime):
        value = value.item()
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 6)
    return value


def test_fixture_run_observation_rows_golden(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    data_regression: DataRegressionFixture,
) -> None:
    manifest = _run(
        tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW
    )
    assert len(manifest.observation_files) == 1
    frame = gpd.read_parquet(tmp_path / "out" / manifest.observation_files[0])
    rows: list[dict[str, Any]] = []
    for _, record in frame.sort_values("polygon_id").iterrows():
        row = {column: _plain(record[column]) for column in OBSERVATION_COLUMNS}
        row["geometry_wkt"] = shapely.wkt.dumps(record.geometry, rounding_precision=6)
        rows.append(row)
    data_regression.check({"rows": rows})
