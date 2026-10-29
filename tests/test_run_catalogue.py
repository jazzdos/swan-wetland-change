"""run_once publishes the STAC catalogue; offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pystac
import pystac.validation
from shapely.geometry.base import BaseGeometry

from tests.test_pipeline import (
    NOW,
    FakeClient,
    _polygons,
    _probe,
    _run,
    _seed_october_baseline,
)
from wetland_change.config import DEFAULT_CATALOGUE_BASE_URL
from wetland_change.outputs.changes import change_path
from wetland_change.stac import StoreStacIO, build_and_write
from wetland_change.store import OutputStore
from wetland_change.verify.checks import write_report

BASE = DEFAULT_CATALOGUE_BASE_URL.rstrip("/")


def _item_json(store: OutputStore, item_id: str) -> dict[str, Any]:
    key = f"stac/swan-wetland-change/{item_id}/{item_id}.json"
    payload: dict[str, Any] = json.loads(store.read_bytes(key))
    return payload


def test_run_once_publishes_valid_catalogue(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    _run(tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW)
    store = OutputStore(str(tmp_path / "out"))
    assert store.exists("stac/catalog.json")
    io = StoreStacIO(store, BASE)
    catalog = pystac.Catalog.from_file(f"{BASE}/stac/catalog.json", stac_io=io)
    assert pystac.validation.validate_all(catalog, stac_io=io) is None
    assert len(list(catalog.get_items(recursive=True))) == 1


def test_item_with_change_rows_has_changes_asset(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    probe = _probe(tmp_path, fixture_item, fixture_polygon)
    store = OutputStore(str(tmp_path / "out"))
    _seed_october_baseline(store, probe, fixture_polygon)
    _run(tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW)
    item = _item_json(store, probe["item_id"])
    expected = change_path(2026, probe["tile"], probe["item_id"])
    assert item["assets"]["changes"]["href"] == f"{BASE}/{expected}"


def test_item_without_change_rows_has_no_changes_asset(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    _run(tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW)
    store = OutputStore(str(tmp_path / "out"))
    item = _item_json(store, fixture_item["id"])
    assert "changes" not in item["assets"]


def test_items_parquet_row_count_matches_items(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    _run(tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW)
    store = OutputStore(str(tmp_path / "out"))
    key = "stac/swan-wetland-change/items.parquet"
    local = tmp_path / "items-copy.parquet"
    local.write_bytes(store.read_bytes(key))
    rows = duckdb.sql(f"select count(*) from read_parquet('{local}')").fetchall()
    io = StoreStacIO(store, BASE)
    catalog = pystac.Catalog.from_file(f"{BASE}/stac/catalog.json", stac_io=io)
    assert rows[0][0] == len(list(catalog.get_items(recursive=True))) == 1


def test_verification_report_asset(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    manifest = _run(
        tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW
    )
    store = OutputStore(str(tmp_path / "out"))
    assert "verification" not in _item_json(store, fixture_item["id"])["assets"]
    write_report([], store=store, run_id=manifest.run_id, docs_dir=None)
    build_and_write(store, base_url=BASE)
    item = _item_json(store, fixture_item["id"])
    assert (
        item["assets"]["verification"]["href"]
        == f"{BASE}/verification/{manifest.run_id}.json"
    )
