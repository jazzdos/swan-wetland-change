from __future__ import annotations

import itertools
import json
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tests.test_attribution_backfill import (
    CHG_PATH,
    OBS_PATH,
    PARQUET,
    REPORT_PATH,
    RUN_ID,
    _chg_bytes,
    _dump,
    _meta,
    _obs_bytes,
    _report_doc,
)
from tests.test_footer_backfill import (
    ITEM_A,
    OPERATION_EPSG,
    OVERRIDE_WATER,
    _old_bytes,
    _rows,
)
from tests.test_notice_backfill import NOT_PROVENANCE
from wetland_change.attribution import DEA_ATTRIBUTION_ADDED_KEY, DEA_ATTRIBUTION_KEY
from wetland_change.dbca_attribution import (
    DBCA_ATTRIBUTION_ADDED_KEY,
    DBCA_ATTRIBUTION_KEY,
    dbca_attribution,
)
from wetland_change.ledger import ledger_path
from wetland_change.outputs import dbca_backfill
from wetland_change.outputs.attribution_backfill import add_missing_attribution
from wetland_change.outputs.dbca_backfill import (
    DbcaBackfillResult,
    add_missing_dbca_attribution,
)
from wetland_change.outputs.footer_backfill import (
    ADDED_KEY,
    add_missing_footers,
    added_footer_value,
)
from wetland_change.outputs.geoparquet import observation_path
from wetland_change.outputs.notice_backfill import add_missing_notice
from wetland_change.outputs.provenance import FOOTER_KEYS
from wetland_change.sentinel_notice import (
    COPERNICUS_NOTICE_ADDED_KEY,
    COPERNICUS_NOTICE_KEY,
)
from wetland_change.store import OutputStore

COMMIT = "abc1234"
ON = date(2026, 11, 15)
KEY = DBCA_ATTRIBUTION_KEY.encode()
ADDED = DBCA_ATTRIBUTION_ADDED_KEY.encode()


@pytest.fixture
def store(tmp_path: Path) -> OutputStore:
    return OutputStore(str(tmp_path))


@pytest.fixture
def write_spy(
    store: OutputStore, monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    original = store.write_bytes

    def spy(relpath: str, data: bytes, *, content_type: str | None = None) -> str:
        calls.append({"relpath": relpath, "content_type": content_type})
        return original(relpath, data, content_type=content_type)

    monkeypatch.setattr(store, "write_bytes", spy)
    return calls


def _run(store: OutputStore, *, dry_run: bool = False) -> DbcaBackfillResult:
    return add_missing_dbca_attribution(store, commit=COMMIT, on=ON, dry_run=dry_run)


def _tables_equal(a: bytes, b: bytes) -> bool:
    return pq.read_table(BytesIO(a)).equals(pq.read_table(BytesIO(b)))


def test_observation_gains_exactly_the_two_keys(store: OutputStore) -> None:
    old = _obs_bytes()
    store.write_bytes(OBS_PATH, old)
    result = _run(store)
    assert result.rewritten == (OBS_PATH,)
    assert result.scanned == 1
    assert result.dry_run is False
    new = store.read_bytes(OBS_PATH)
    assert _tables_equal(old, new)
    old_meta, new_meta = _meta(old), _meta(new)
    for key, value in old_meta.items():
        assert new_meta[key] == value
    assert set(new_meta) == set(old_meta) | {KEY, ADDED}
    assert json.loads(new_meta[KEY]) == dbca_attribution("observation")
    assert new_meta[ADDED] == added_footer_value(COMMIT, ON).encode()
    assert pq.read_table(BytesIO(new)).schema.equals(
        pq.read_table(BytesIO(old)).schema, check_metadata=False
    )


def test_change_file_gains_the_change_block(store: OutputStore) -> None:
    old = _chg_bytes()
    store.write_bytes(CHG_PATH, old)
    result = _run(store)
    assert result.rewritten == (CHG_PATH,)
    new = store.read_bytes(CHG_PATH)
    assert _tables_equal(old, new)
    new_meta = _meta(new)
    assert json.loads(new_meta[KEY]) == dbca_attribution("change")
    assert set(new_meta) == set(_meta(old)) | {KEY, ADDED}
    for key, value in _meta(old).items():
        assert new_meta[key] == value


def test_a_file_with_the_block_is_skipped_untouched(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    schema_meta = _meta(_obs_bytes())
    table = pq.read_table(BytesIO(_obs_bytes()))
    holding = BytesIO()
    pq.write_table(
        table.replace_schema_metadata({**schema_meta, KEY: b"any value"}), holding
    )
    store.write_bytes(OBS_PATH, holding.getvalue())
    write_spy.clear()
    result = _run(store)
    assert result.skipped == (OBS_PATH,)
    assert result.rewritten == ()
    assert write_spy == []
    assert store.read_bytes(OBS_PATH) == holding.getvalue()


def test_second_run_rewrites_nothing(store: OutputStore) -> None:
    store.write_bytes(OBS_PATH, _obs_bytes())
    store.write_bytes(CHG_PATH, _chg_bytes())
    first = _run(store)
    assert set(first.rewritten) == {OBS_PATH, CHG_PATH}
    after = {p: store.read_bytes(p) for p in (OBS_PATH, CHG_PATH)}
    second = _run(store)
    assert second.rewritten == ()
    assert set(second.skipped) == {OBS_PATH, CHG_PATH}
    assert second.scanned == 2
    for path, data in after.items():
        assert store.read_bytes(path) == data


def test_dry_run_writes_nothing(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    old_obs, old_chg = _obs_bytes(), _chg_bytes()
    store.write_bytes(OBS_PATH, old_obs)
    store.write_bytes(CHG_PATH, old_chg)
    write_spy.clear()
    result = _run(store, dry_run=True)
    assert result.dry_run is True
    assert set(result.rewritten) == {OBS_PATH, CHG_PATH}
    assert write_spy == []
    assert store.read_bytes(OBS_PATH) == old_obs
    assert store.read_bytes(CHG_PATH) == old_chg


def test_an_unreadable_file_fails_alone(store: OutputStore) -> None:
    bad_path = observation_path(2026, "50HLK", "S2A_BAD")
    store.write_bytes(bad_path, b"not parquet")
    store.write_bytes(OBS_PATH, _obs_bytes())
    result = _run(store)
    assert result.rewritten == (OBS_PATH,)
    assert [path for path, _ in result.failed] == [bad_path]
    assert result.scanned == 2
    assert store.read_bytes(bad_path) == b"not parquet"
    assert KEY in _meta(store.read_bytes(OBS_PATH))


def test_a_rewrite_that_drops_a_row_is_refused(
    store: OutputStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _obs_bytes()
    store.write_bytes(OBS_PATH, old)
    original = dbca_backfill._with_metadata

    def drop_a_row(table: pa.Table, metadata: dict[bytes, bytes]) -> bytes:
        return original(table.slice(1), metadata)

    monkeypatch.setattr(dbca_backfill, "_with_metadata", drop_a_row)
    result = _run(store)
    assert result.rewritten == ()
    assert [path for path, _ in result.failed] == [OBS_PATH]
    assert store.read_bytes(OBS_PATH) == old


def test_a_rewrite_that_changes_a_footer_value_is_refused(
    store: OutputStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _obs_bytes()
    store.write_bytes(OBS_PATH, old)
    original = dbca_backfill._with_metadata
    key = FOOTER_KEYS[0].encode()

    def change_a_value(table: pa.Table, metadata: dict[bytes, bytes]) -> bytes:
        return original(table, {**metadata, key: b"changed"})

    monkeypatch.setattr(dbca_backfill, "_with_metadata", change_a_value)
    result = _run(store)
    assert [path for path, _ in result.failed] == [OBS_PATH]
    assert store.read_bytes(OBS_PATH) == old


def test_only_observation_and_change_files_are_scanned(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    others = {
        REPORT_PATH: _dump(_report_doc()),
        ledger_path(RUN_ID, 2026): b"not parquet",
        f"runs/{RUN_ID}.json": b"{}",
        "stac/catalog.json": b"{}",
        "observations/year=2026/tile=50HLK/notes.parquet": b"junk",
        "changes/year=2026/tile=50HLK/other.parquet": b"junk",
    }
    for path, data in others.items():
        store.write_bytes(path, data)
    store.write_bytes(OBS_PATH, _obs_bytes())
    store.write_bytes(CHG_PATH, _chg_bytes())
    write_spy.clear()
    result = _run(store)
    assert result.scanned == 2
    assert set(result.rewritten) == {OBS_PATH, CHG_PATH}
    assert result.failed == ()
    assert {call["relpath"] for call in write_spy} == {OBS_PATH, CHG_PATH}
    for path, data in others.items():
        assert store.read_bytes(path) == data


def test_writes_use_the_parquet_content_type(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    store.write_bytes(OBS_PATH, _obs_bytes())
    store.write_bytes(CHG_PATH, _chg_bytes())
    write_spy.clear()
    _run(store)
    assert len(write_spy) == 2
    assert {call["content_type"] for call in write_spy} == {PARQUET}


def _apply(store: OutputStore, name: str) -> None:
    if name == "footers":
        add_missing_footers(
            store,
            water=OVERRIDE_WATER,
            operation_epsg=OPERATION_EPSG,
            commit=COMMIT,
            on=ON,
        )
    elif name == "attribution":
        add_missing_attribution(store, commit=COMMIT, on=ON)
    elif name == "notice":
        add_missing_notice(store, commit=COMMIT, on=ON)
    else:
        add_missing_dbca_attribution(store, commit=COMMIT, on=ON)


def _entries(data: bytes) -> dict[bytes, bytes]:
    return {k: v for k, v in _meta(data).items() if k not in NOT_PROVENANCE}


def _after(tmp_path: Path, order: tuple[str, ...], path: str, data: bytes) -> bytes:
    store = OutputStore(str(tmp_path / "-".join(order)))
    store.write_bytes(path, data)
    for name in order:
        _apply(store, name)
    return store.read_bytes(path)


def test_the_four_backfills_commute_on_an_unfooted_observation_file(
    tmp_path: Path,
) -> None:
    old = _old_bytes(_rows(ITEM_A))
    path = observation_path(2026, "50HLK", ITEM_A)
    expected_keys = {
        *(key.encode() for key in FOOTER_KEYS),
        ADDED_KEY.encode(),
        DEA_ATTRIBUTION_KEY.encode(),
        DEA_ATTRIBUTION_ADDED_KEY.encode(),
        COPERNICUS_NOTICE_KEY.encode(),
        COPERNICUS_NOTICE_ADDED_KEY.encode(),
        KEY,
        ADDED,
    }
    original = pq.read_table(BytesIO(old))
    finals = {
        order: _after(tmp_path, order, path, old)
        for order in itertools.permutations(
            ("footers", "attribution", "notice", "dbca")
        )
    }
    assert len(finals) == 24
    reference = _entries(next(iter(finals.values())))
    assert set(reference) == expected_keys
    for final in finals.values():
        assert _entries(final) == reference
        assert pq.read_table(BytesIO(final)).equals(original)


def test_attribution_notice_and_dbca_commute_on_a_change_file(
    tmp_path: Path,
) -> None:
    old = _chg_bytes()
    finals = [
        _after(tmp_path, order, CHG_PATH, old)
        for order in itertools.permutations(("attribution", "notice", "dbca"))
    ]
    assert len(finals) == 6
    reference = _entries(finals[0])
    for final in finals:
        assert _entries(final) == reference
        assert _tables_equal(final, old)
        for key, value in _meta(old).items():
            assert _meta(final)[key] == value
        assert set(_meta(final)) - set(_meta(old)) == {
            DEA_ATTRIBUTION_KEY.encode(),
            DEA_ATTRIBUTION_ADDED_KEY.encode(),
            COPERNICUS_NOTICE_KEY.encode(),
            COPERNICUS_NOTICE_ADDED_KEY.encode(),
            KEY,
            ADDED,
        }
