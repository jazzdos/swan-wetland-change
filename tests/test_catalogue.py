"""STAC catalogue built from the ledger alone; all offline."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import duckdb
import pystac
import pystac.validation
import pystac.validation.local_validator
import pytest
import stac_validator.utilities
from stac_check.lint import Linter

from tests.conftest import REQUIRED_ASSETS
from wetland_change.catalogue.item import SceneItem, parse_item
from wetland_change.ledger import (
    LedgerEntry,
    entry_for,
    read_ledger,
    rejected_entry,
    write_ledger,
)
from wetland_change.outputs.changes import change_path
from wetland_change.outputs.geoparquet import observation_path
from wetland_change.stac import (
    StoreStacIO,
    build_and_write,
    build_catalogue,
    validate_catalogue,
    write_catalogue,
)
from wetland_change.stac.catalogue import processed_entries
from wetland_change.store import OutputStore
from wetland_change.verify.checks import write_report

BASE_URL = "https://catalogue.test.invalid/wetlands"
T0 = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
OK_IDS = ["S2C_T50HLK_20261001T022351_L2A", "S2C_T50HLK_20261011T022351_L2A"]
RETRIED_ID = "S2C_T50HLK_20261021T022351_L2A"
FAILED_ID = "S2C_T50HLK_20261022T022351_L2A"
SUCCEEDED_IDS = sorted([*OK_IDS, RETRIED_ID, "S2C_T50HLK_20261026T022351_L2A"])


def _scene(base: dict[str, Any], item_id: str, day: int) -> SceneItem:
    item = copy.deepcopy(base)
    item["id"] = item_id
    when = datetime(2026, 10, day, 2, 26, 39, tzinfo=UTC)
    item["properties"]["datetime"] = when.strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    return parse_item(
        item, collection="sentinel-2-c1-l2a", required_assets=REQUIRED_ASSETS
    )


def _obs(scene: SceneItem) -> str:
    return observation_path(scene.year, scene.tile, scene.item_id)


def _succeeded(scene: SceneItem, run_id: str, at: datetime) -> LedgerEntry:
    return entry_for(
        scene,
        status="succeeded",
        attempts=1,
        run_id=run_id,
        processed_at=at,
        n_rows=2,
        observation_path=_obs(scene),
    )


@pytest.fixture
def store(tmp_path: Path, fixture_item: dict[str, Any]) -> OutputStore:
    store = OutputStore(str(tmp_path / "out"))
    days = {OK_IDS[0]: 1, OK_IDS[1]: 11, RETRIED_ID: 21, SUCCEEDED_IDS[-1]: 26}
    scenes = {i: _scene(fixture_item, i, d) for i, d in days.items()}
    failed_scene = _scene(fixture_item, FAILED_ID, 22)
    r1 = [
        _succeeded(scenes[OK_IDS[0]], "r1", T0),
        _succeeded(scenes[OK_IDS[1]], "r1", T0),
        entry_for(
            scenes[RETRIED_ID],
            status="failed",
            attempts=1,
            run_id="r1",
            processed_at=T0,
            error="boom",
        ),
        entry_for(
            failed_scene,
            status="failed",
            attempts=1,
            run_id="r1",
            processed_at=T0,
            error="boom",
        ),
        rejected_entry(
            "rejected-id", "collection mismatch", run_id="r1", processed_at=T0
        ),
    ]
    later = T0 + timedelta(hours=1)
    r2 = [
        _succeeded(scenes[RETRIED_ID], "r2", later),
        _succeeded(scenes[SUCCEEDED_IDS[-1]], "r2", later),
    ]
    write_ledger(r1, store, run_id="r1")
    write_ledger(r2, store, run_id="r2")
    return store


def _stac_files(store: OutputStore) -> list[str]:
    return store.list_files("stac")


def _json(store: OutputStore, relpath: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(store.read_bytes(relpath))
    return data


def test_processed_entries_latest_succeeded_only(store: OutputStore) -> None:
    entries = processed_entries(read_ledger(store))
    assert [e["item_id"] for e in entries] == SUCCEEDED_IDS


def test_written_files_are_exactly_the_succeeded_items(store: OutputStore) -> None:
    written = build_and_write(store, base_url=BASE_URL)
    expected = [
        "stac/catalog.json",
        "stac/swan-wetland-change/collection.json",
        "stac/swan-wetland-change/items.parquet",
        *(f"stac/swan-wetland-change/{i}/{i}.json" for i in SUCCEEDED_IDS),
    ]
    assert written == sorted(expected)
    assert _stac_files(store) == sorted(expected)
    assert not any(FAILED_ID in p or "rejected-id" in p for p in written)


def test_observation_asset_href(store: OutputStore) -> None:
    build_and_write(store, base_url=BASE_URL)
    ledger = {
        e["item_id"]: e["observation_path"]
        for e in processed_entries(read_ledger(store))
    }
    for item_id in SUCCEEDED_IDS:
        item = _json(store, f"stac/swan-wetland-change/{item_id}/{item_id}.json")
        asset = item["assets"]["observations"]
        assert asset["href"] == f"{BASE_URL}/{ledger[item_id]}"
        assert asset["type"] == "application/vnd.apache.parquet"
        assert asset["roles"] == ["data"]
        assert set(item["assets"]) == {"observations"}  # no change/report files yet
        assert item["stac_extensions"] == []


def _item_json(store: OutputStore, item_id: str) -> dict[str, Any]:
    return _json(store, f"stac/swan-wetland-change/{item_id}/{item_id}.json")


def test_changes_asset_only_for_items_with_change_file(store: OutputStore) -> None:
    target = SUCCEEDED_IDS[0]
    entry = next(
        e for e in processed_entries(read_ledger(store)) if e["item_id"] == target
    )
    path = change_path(entry["datetime"].astimezone(UTC).year, entry["tile"], target)
    store.write_bytes(path, b"x")
    build_and_write(store, base_url=BASE_URL)
    asset = _item_json(store, target)["assets"]["changes"]
    assert asset["href"] == f"{BASE_URL}/{path}"
    assert asset["type"] == "application/vnd.apache.parquet"
    assert asset["roles"] == ["data"]
    for other in SUCCEEDED_IDS[1:]:
        assert "changes" not in _item_json(store, other)["assets"]


def test_verification_asset_points_at_run_report(store: OutputStore) -> None:
    write_report([], store=store, run_id="r2", docs_dir=None)
    build_and_write(store, base_url=BASE_URL)
    run_ids = {e["item_id"]: e["run_id"] for e in processed_entries(read_ledger(store))}
    assert set(run_ids.values()) == {"r1", "r2"}
    for item_id, run_id in run_ids.items():
        assets = _item_json(store, item_id)["assets"]
        if run_id == "r2":
            assert assets["verification"]["href"] == f"{BASE_URL}/verification/r2.json"
            assert assets["verification"]["type"] == "application/json"
            assert assets["verification"]["roles"] == ["metadata"]
        else:
            assert "verification" not in assets


def test_items_parquet_written_and_readable_by_duckdb(
    store: OutputStore, tmp_path: Path
) -> None:
    key = "stac/swan-wetland-change/items.parquet"
    written = build_and_write(store, base_url=BASE_URL)
    assert key in written
    local = tmp_path / "items.parquet"
    local.write_bytes(store.read_bytes(key))
    rows = duckdb.sql(f"SELECT count(*) FROM read_parquet('{local}')").fetchall()
    assert rows[0][0] == len(SUCCEEDED_IDS)
    collection = _json(store, "stac/swan-wetland-change/collection.json")
    assert collection["assets"]["items"]["href"] == f"{BASE_URL}/{key}"


def test_item_derived_from_and_properties(store: OutputStore) -> None:
    build_and_write(store, base_url=BASE_URL)
    item_id = SUCCEEDED_IDS[0]
    item = _json(store, f"stac/swan-wetland-change/{item_id}/{item_id}.json")
    derived = [link for link in item["links"] if link["rel"] == "derived_from"]
    assert len(derived) == 1
    assert derived[0]["href"].startswith("https://earth-search.aws.element84.com/")
    assert item["properties"]["grid:code"] == "MGRS-50HLK"
    assert "s2:vegetation_percentage" not in item["properties"]


def _load_and_validate(store: OutputStore) -> pystac.Catalog:
    """Read the written catalogue back from the store and validate it.

    `stac_io` reaches children through the root catalogue; `validate_all` takes
    it separately. No global StacIO default is touched.
    """
    io = StoreStacIO(store, BASE_URL)
    catalog = pystac.Catalog.from_file(f"{BASE_URL}/stac/catalog.json", stac_io=io)
    assert pystac.validation.validate_all(catalog, stac_io=io) is None
    return catalog


def test_pystac_validate_all_passes(store: OutputStore) -> None:
    build_and_write(store, base_url=BASE_URL)
    catalog = _load_and_validate(store)
    assert len(list(catalog.get_items(recursive=True))) == len(SUCCEEDED_IDS)


@pytest.fixture
def offline_schemas(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    real = stac_validator.utilities.fetch_and_parse_file
    cache = pystac.validation.local_validator.get_local_schema_cache()

    def fake(path: str, headers: dict[str, str] | None = None) -> Any:
        if path in cache:
            return cache[path]
        if path.startswith("http"):
            raise RuntimeError(f"network access blocked: {path}")
        return real(path, headers)

    stac_validator.utilities.fetch_and_parse_schema.cache_clear()
    monkeypatch.setattr(stac_validator.utilities, "fetch_and_parse_file", fake)
    yield
    stac_validator.utilities.fetch_and_parse_schema.cache_clear()


def test_stac_check_reports_no_errors(
    store: OutputStore, tmp_path: Path, offline_schemas: None
) -> None:
    build_and_write(store, base_url=BASE_URL)
    item_id = SUCCEEDED_IDS[0]
    scratch = tmp_path / "check"
    scratch.mkdir()
    for relpath in (
        "stac/swan-wetland-change/collection.json",
        f"stac/swan-wetland-change/{item_id}/{item_id}.json",
    ):
        path = scratch / Path(relpath).name
        path.write_bytes(store.read_bytes(relpath))
        linter = Linter(str(path))
        assert linter.valid_stac is True, linter.message
        assert not linter.message.get("error_message"), linter.message


def test_all_hrefs_are_absolute_https(store: OutputStore) -> None:
    build_and_write(store, base_url=BASE_URL)
    for relpath in _stac_files(store):
        if not relpath.endswith(".json"):
            continue
        doc = _json(store, relpath)
        hrefs = [link["href"] for link in doc["links"]]
        hrefs += [asset["href"] for asset in doc.get("assets", {}).values()]
        assert hrefs
        for href in hrefs:
            parsed = urlparse(href)
            assert parsed.scheme == "https" and parsed.netloc, (relpath, href)


def test_collection_license_and_providers(store: OutputStore) -> None:
    build_and_write(store, base_url=BASE_URL)
    collection = _json(store, "stac/swan-wetland-change/collection.json")
    assert collection["license"] == "CC-BY-SA-4.0"
    names = " | ".join(p["name"] for p in collection["providers"])
    for needle in ("Element 84", "ESA", "DBCA", "Geoscience Australia"):
        assert needle in names
    interval = collection["extent"]["temporal"]["interval"][0]
    assert interval[0].startswith("2026-10-01")
    assert interval[1].startswith("2026-10-26")


def test_rebuild_is_byte_identical(store: OutputStore, tmp_path: Path) -> None:
    first = build_and_write(store, base_url=BASE_URL)
    snapshot = {p: store.read_bytes(p) for p in first}
    again = build_and_write(store, base_url=BASE_URL)
    assert again == first
    assert {p: store.read_bytes(p) for p in again} == snapshot

    other = OutputStore(str(tmp_path / "other"))
    for path in store.list_files("ledger"):
        other.write_bytes(path, store.read_bytes(path))
    build_and_write(other, base_url=BASE_URL + "/")
    assert {p: other.read_bytes(p) for p in first} == snapshot


def test_empty_ledger_gives_valid_catalogue(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    written = build_and_write(store, base_url=BASE_URL)
    assert written == [
        "stac/catalog.json",
        "stac/swan-wetland-change/collection.json",
    ]
    catalog = _load_and_validate(store)
    assert list(catalog.get_items(recursive=True)) == []


def test_build_and_validate_in_memory(store: OutputStore) -> None:
    catalog = build_catalogue(read_ledger(store), base_url=BASE_URL)
    validate_catalogue(catalog)
    assert catalog.id == "swan-wetland-change-catalog"
    assert write_catalogue(catalog, store, base_url=BASE_URL)


def test_write_catalogue_rejects_mismatched_base_url(store: OutputStore) -> None:
    catalog = build_catalogue(read_ledger(store), base_url=BASE_URL)
    with pytest.raises(ValueError, match="base_url"):
        write_catalogue(catalog, store, base_url="https://other.example/stac-x")
    assert _stac_files(store) == []
