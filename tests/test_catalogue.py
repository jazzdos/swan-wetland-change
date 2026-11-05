"""STAC catalogue built from the ledger alone; all offline."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
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
from wetland_change.stac.catalogue import (
    ensure_publishable_base_url,
    processed_entries,
)
from wetland_change.store import OutputStore
from wetland_change.verify.checks import write_report

BASE_URL = "https://catalogue.test.invalid/wetlands"
T0 = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
OK_IDS = ["S2C_T50HLK_20261001T022351_L2A", "S2C_T50HLK_20261011T022351_L2A"]
RETRIED_ID = "S2C_T50HLK_20261021T022351_L2A"
FAILED_ID = "S2C_T50HLK_20261022T022351_L2A"
SUCCEEDED_IDS = sorted([*OK_IDS, RETRIED_ID, "S2C_T50HLK_20261026T022351_L2A"])
INDEX_KEY = "stac/write-index.json"
COLLECTION_KEY = "stac/swan-wetland-change/collection.json"
CATALOG_KEY = "stac/catalog.json"
PARQUET_KEY = "stac/swan-wetland-change/items.parquet"


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
    assert _stac_files(store) == sorted([*expected, INDEX_KEY])
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
        if not relpath.endswith(".json") or relpath == INDEX_KEY:
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


def test_rebuild_writes_nothing_and_changes_no_bytes(
    store: OutputStore, tmp_path: Path
) -> None:
    first = build_and_write(store, base_url=BASE_URL)
    snapshot = {p: store.read_bytes(p) for p in _stac_files(store)}
    assert build_and_write(store, base_url=BASE_URL) == []
    assert {p: store.read_bytes(p) for p in _stac_files(store)} == snapshot

    other = OutputStore(str(tmp_path / "other"))
    for path in store.list_files("ledger"):
        other.write_bytes(path, store.read_bytes(path))
    build_and_write(other, base_url=BASE_URL + "/")
    assert {p: other.read_bytes(p) for p in first} == {p: snapshot[p] for p in first}


class RecordingStore(OutputStore):
    """Same root as another store; records writes and reads."""

    def __init__(self, root: str) -> None:
        super().__init__(root)
        self.writes: list[str] = []
        self.reads: list[str] = []

    def write_bytes(self, relpath: str, data: bytes) -> str:
        self.writes.append(relpath)
        return super().write_bytes(relpath, data)

    def read_bytes(self, relpath: str) -> bytes:
        self.reads.append(relpath)
        return super().read_bytes(relpath)


def _item_key(item_id: str) -> str:
    return f"stac/swan-wetland-change/{item_id}/{item_id}.json"


def _all_objects() -> list[str]:
    return sorted(
        [
            CATALOG_KEY,
            COLLECTION_KEY,
            PARQUET_KEY,
            *(_item_key(i) for i in SUCCEEDED_IDS),
        ]
    )


def _built(store: OutputStore) -> RecordingStore:
    build_and_write(store, base_url=BASE_URL)
    return RecordingStore(store.uri)


def test_index_records_base_url_and_digests(store: OutputStore) -> None:
    build_and_write(store, base_url=BASE_URL + "/")
    index = _json(store, INDEX_KEY)
    assert index["base_url"] == BASE_URL
    assert sorted(index["objects"]) == _all_objects()
    for key, digest in index["objects"].items():
        assert digest == hashlib.sha256(store.read_bytes(key)).hexdigest()


def test_noop_rerun_does_not_write_even_the_index(store: OutputStore) -> None:
    rec = _built(store)
    assert build_and_write(rec, base_url=BASE_URL) == []
    assert rec.writes == []


def test_new_ledger_item_writes_only_that_item_and_aggregates(
    store: OutputStore, fixture_item: dict[str, Any]
) -> None:
    rec = _built(store)
    new_id = "S2C_T50HLK_20261028T022351_L2A"
    scene = _scene(fixture_item, new_id, 28)
    write_ledger([_succeeded(scene, "r3", T0 + timedelta(hours=2))], store, run_id="r3")
    written = build_and_write(rec, base_url=BASE_URL)
    assert written == sorted([_item_key(new_id), COLLECTION_KEY, PARQUET_KEY])
    assert sorted(set(rec.writes) - {INDEX_KEY}) == written
    assert rec.writes[-1] == INDEX_KEY
    for old in SUCCEEDED_IDS:
        assert _item_key(old) not in rec.writes


def test_new_change_file_rewrites_only_that_item_and_the_parquet(
    store: OutputStore,
) -> None:
    rec = _built(store)
    target = SUCCEEDED_IDS[0]
    entry = next(
        e for e in processed_entries(read_ledger(store)) if e["item_id"] == target
    )
    path = change_path(entry["datetime"].astimezone(UTC).year, entry["tile"], target)
    store.write_bytes(path, b"x")
    written = build_and_write(rec, base_url=BASE_URL)
    # items.parquet embeds each item's assets, so it changes with the item.
    assert written == sorted([_item_key(target), PARQUET_KEY])
    assert "changes" in _item_json(store, target)["assets"]


def test_deleted_object_is_restored(store: OutputStore) -> None:
    rec = _built(store)
    victim = _item_key(SUCCEEDED_IDS[1])
    original = store.read_bytes(victim)
    assert store.delete(victim)
    assert build_and_write(rec, base_url=BASE_URL) == [victim]
    assert store.read_bytes(victim) == original


def test_changed_base_url_rewrites_everything(store: OutputStore) -> None:
    rec = _built(store)
    new_url = "https://other.test.invalid/wetlands"
    written = build_and_write(rec, base_url=new_url)
    assert written == _all_objects()
    assert _json(store, INDEX_KEY)["base_url"] == new_url


@pytest.mark.parametrize("junk", [b"not json", b"[]", b'{"base_url": 1, "objects": 2}'])
def test_corrupt_index_rewrites_everything(store: OutputStore, junk: bytes) -> None:
    rec = _built(store)
    store.write_bytes(INDEX_KEY, junk)
    assert build_and_write(rec, base_url=BASE_URL) == _all_objects()
    assert sorted(_json(store, INDEX_KEY)["objects"]) == _all_objects()


def test_stale_index_entry_rewrites_that_object(store: OutputStore) -> None:
    rec = _built(store)
    index = _json(store, INDEX_KEY)
    key = _item_key(SUCCEEDED_IDS[2])
    index["objects"][key] = "0" * 64
    store.write_bytes(INDEX_KEY, json.dumps(index).encode())
    assert build_and_write(rec, base_url=BASE_URL) == [key]
    assert _json(store, INDEX_KEY)["objects"][key] != "0" * 64


def test_index_is_not_in_the_catalogue_graph(store: OutputStore) -> None:
    build_and_write(store, base_url=BASE_URL)
    catalog = _load_and_validate(store)
    hrefs = {link.href for link in catalog.get_links()}
    assert not any(INDEX_KEY in h for h in hrefs)


def test_given_ledger_is_used_without_reading_ledger_objects(
    store: OutputStore,
) -> None:
    table = read_ledger(store)
    rec = RecordingStore(store.uri)
    written = build_and_write(rec, base_url=BASE_URL, ledger=table)
    assert written == _all_objects()
    assert not [p for p in rec.reads if p.startswith("ledger/")]


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


PLACEHOLDER_URL = "https://example.invalid/swan-wetland-change"
BUCKET_URL = "https://bucket.s3.ap-southeast-2.amazonaws.com"


def _stub_store(uri: str) -> OutputStore:
    return SimpleNamespace(uri=uri)  # type: ignore[return-value]


def test_ensure_publishable_rejects_placeholder_on_s3() -> None:
    with pytest.raises(ValueError, match="base_url") as excinfo:
        ensure_publishable_base_url(PLACEHOLDER_URL, _stub_store("s3://bucket/"))
    assert "config/pipeline.toml" in str(excinfo.value)
    assert "bucket_url" in str(excinfo.value)


def test_ensure_publishable_rejects_bare_invalid_host_on_s3() -> None:
    with pytest.raises(ValueError, match="base_url"):
        ensure_publishable_base_url("https://invalid/x", _stub_store("s3://bucket/"))


def test_ensure_publishable_accepts_real_bucket_url_on_s3() -> None:
    ensure_publishable_base_url(BUCKET_URL, _stub_store("s3://bucket/"))


def test_ensure_publishable_accepts_placeholder_on_local_store() -> None:
    ensure_publishable_base_url(PLACEHOLDER_URL, _stub_store("file:///tmp/out"))


def test_build_and_write_refuses_placeholder_on_s3_before_reading() -> None:
    with pytest.raises(ValueError, match="base_url"):
        build_and_write(_stub_store("s3://bucket/"), base_url=PLACEHOLDER_URL)
