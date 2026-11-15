from __future__ import annotations

import dataclasses
import itertools
import json
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tests.test_attribution_backfill import (
    CHG_PATH,
    JSON_TYPE,
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
from tests.test_geoparquet import _row
from wetland_change.attribution import DEA_ATTRIBUTION_ADDED_KEY, DEA_ATTRIBUTION_KEY
from wetland_change.catalogue.item import SceneItem
from wetland_change.ledger import (
    LedgerEntry,
    entries_to_table,
    entry_for,
    ledger_path,
    rejected_entry,
)
from wetland_change.outputs import notice_backfill
from wetland_change.outputs.attribution_backfill import add_missing_attribution
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
    NoticeKind,
    copernicus_notice,
)
from wetland_change.store import OutputStore

COMMIT = "abc1234"
ON = date(2026, 11, 15)
NOTICE = COPERNICUS_NOTICE_KEY.encode()
NOTICE_ADDED = COPERNICUS_NOTICE_ADDED_KEY.encode()
PROCESSED = datetime(2026, 11, 15, 1, 0, tzinfo=UTC)
LEDGER_PATH = ledger_path(RUN_ID, 2026)
NOT_PROVENANCE = (b"geo", b"pandas", b"ARROW:schema")


def _at(year: int, month: int = 10, day: int = 27) -> datetime:
    return datetime(year, month, day, 2, 26, 46, tzinfo=UTC)


def _history_bytes(year: int) -> bytes:
    """An old observation file of the change test's polygons in October `year`."""
    rows = [
        dataclasses.replace(row, datetime=_at(year), item_id=f"S2_{year}")
        for row in _rows("x")
    ]
    return _old_bytes(rows)


def _scene(scene: SceneItem, item_id: str, when: datetime) -> SceneItem:
    return dataclasses.replace(scene, item_id=item_id, datetime=when)


def _succeeded(scene: SceneItem) -> LedgerEntry:
    return entry_for(
        scene,
        status="succeeded",
        attempts=1,
        run_id=RUN_ID,
        processed_at=PROCESSED,
        n_rows=2,
        observation_path=observation_path(scene.datetime.year, "50HLK", scene.item_id),
    )


def _ledger_bytes(entries: list[LedgerEntry]) -> bytes:
    buf = BytesIO()
    pq.write_table(entries_to_table(entries), buf)
    return buf.getvalue()


def _put_ledger(
    store: OutputStore, entries: list[LedgerEntry], path: str = LEDGER_PATH
) -> str:
    store.write_bytes(path, _ledger_bytes(entries))
    return path


def _expected(kind: NoticeKind, *years: int) -> dict[str, Any]:
    """The notice block as JSON gives it back."""
    block: dict[str, Any] = json.loads(json.dumps(copernicus_notice(kind, years)))
    return block


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


def _run(store: OutputStore, *, dry_run: bool = False) -> Any:
    return add_missing_notice(store, commit=COMMIT, on=ON, dry_run=dry_run)


def _put_all_old(store: OutputStore, scene: SceneItem) -> dict[str, bytes]:
    """An observation (2026), a change file, a report and a ledger part."""
    files = {
        OBS_PATH: _obs_bytes(),
        CHG_PATH: _chg_bytes(),
        REPORT_PATH: _dump(_report_doc()),
        LEDGER_PATH: _ledger_bytes([_succeeded(_scene(scene, "S2A_A", _at(2026)))]),
    }
    for path, data in files.items():
        store.write_bytes(path, data)
    return files


def test_observation_gains_the_two_keys(store: OutputStore) -> None:
    old = _obs_bytes()
    store.write_bytes(OBS_PATH, old)
    result = _run(store)
    assert result.rewritten == (OBS_PATH,)
    new = store.read_bytes(OBS_PATH)
    old_table, new_table = pq.read_table(BytesIO(old)), pq.read_table(BytesIO(new))
    assert new_table.equals(old_table)
    assert new_table.schema.equals(old_table.schema, check_metadata=False)
    old_meta, new_meta = _meta(old), _meta(new)
    for key, value in old_meta.items():
        assert new_meta[key] == value
    assert set(new_meta) == set(old_meta) | {NOTICE, NOTICE_ADDED}
    block = json.loads(new_meta[NOTICE])
    assert block == _expected("observation", 2026)
    assert block["notice"] == "Contains modified Copernicus Sentinel data 2026"
    assert json.loads(new_meta[NOTICE_ADDED]) == {
        "commit": COMMIT,
        "date": "2026-11-15",
    }
    assert new_meta[NOTICE_ADDED].decode() == added_footer_value(COMMIT, ON)


def test_change_file_years_include_the_baseline_history(store: OutputStore) -> None:
    old = _chg_bytes()
    store.write_bytes(CHG_PATH, old)
    for year in (2024, 2025):
        store.write_bytes(
            observation_path(year, "50HLK", f"S2_{year}"), _history_bytes(year)
        )
    result = _run(store)
    assert CHG_PATH in result.rewritten
    new = store.read_bytes(CHG_PATH)
    assert pq.read_table(BytesIO(new)).equals(pq.read_table(BytesIO(old)))
    new_meta = _meta(new)
    assert set(new_meta) == set(_meta(old)) | {NOTICE, NOTICE_ADDED}
    for key, value in _meta(old).items():
        assert new_meta[key] == value
    block = json.loads(new_meta[NOTICE])
    assert block == _expected("change", 2024, 2025, 2026)
    assert block["notice"] == "Contains modified Copernicus Sentinel data 2024-2026"


def test_change_history_ignores_other_months_polygons_and_later_dates(
    store: OutputStore,
) -> None:
    store.write_bytes(CHG_PATH, _chg_bytes())
    other_month = [
        dataclasses.replace(row, datetime=_at(2023, 3, 1), item_id="S2_m")
        for row in _rows("x")
    ]
    other_polygon = [
        dataclasses.replace(
            _row("ramsar-99", 115.5), datetime=_at(2022), item_id="S2_p"
        )
    ]
    later_day = [
        dataclasses.replace(row, datetime=_at(2026, 10, 28), item_id="S2_l")
        for row in _rows("x")
    ]
    for item, rows in (
        ("S2_m", other_month),
        ("S2_p", other_polygon),
        ("S2_l", later_day),
    ):
        store.write_bytes(observation_path(2026, "50HLK", item), _old_bytes(rows))
    _run(store)
    block = json.loads(_meta(store.read_bytes(CHG_PATH))[NOTICE])
    assert block["years"] == [2026]


def test_report_gets_the_run_years_and_keeps_order(
    store: OutputStore, fixture_scene: SceneItem
) -> None:
    doc = _report_doc()
    store.write_bytes(REPORT_PATH, _dump(doc))
    _put_ledger(store, [_succeeded(_scene(fixture_scene, "S2A_A", _at(2026)))])
    result = _run(store)
    assert REPORT_PATH in result.rewritten
    new = json.loads(store.read_bytes(REPORT_PATH))
    assert list(new)[: len(doc)] == list(doc)
    for key, value in doc.items():
        assert new[key] == value
    assert new["generated_at"] == doc["generated_at"]
    assert list(new)[len(doc) :] == [COPERNICUS_NOTICE_KEY, COPERNICUS_NOTICE_ADDED_KEY]
    assert new[COPERNICUS_NOTICE_KEY] == _expected("verification", 2026)
    assert new[COPERNICUS_NOTICE_ADDED_KEY] == {"commit": COMMIT, "date": "2026-11-15"}


def test_ledger_part_gets_its_row_years(
    store: OutputStore, fixture_scene: SceneItem
) -> None:
    entries = [
        _succeeded(_scene(fixture_scene, "S2A_A", _at(2025))),
        _succeeded(_scene(fixture_scene, "S2A_B", _at(2026))),
    ]
    path = _put_ledger(store, entries)
    old = store.read_bytes(path)
    result = _run(store)
    assert result.rewritten == (path,)
    new = store.read_bytes(path)
    assert pq.read_table(BytesIO(new)).equals(pq.read_table(BytesIO(old)))
    new_meta = _meta(new)
    assert set(new_meta) == set(_meta(old)) | {NOTICE, NOTICE_ADDED}
    block = json.loads(new_meta[NOTICE])
    assert block == _expected("ledger", 2025, 2026)
    assert block["notice"] == "Contains modified Copernicus Sentinel data 2025-2026"


def test_rejected_only_ledger_and_report_without_a_scene_are_skipped(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    rejected = rejected_entry(
        "S2_bad", "ItemGuardError: x", run_id=RUN_ID, processed_at=PROCESSED
    )
    part = _put_ledger(store, [rejected])
    report = _dump(_report_doc())
    store.write_bytes(REPORT_PATH, report)
    part_bytes = store.read_bytes(part)
    write_spy.clear()
    result = _run(store)
    assert result.rewritten == ()
    assert set(result.skipped) == {part, REPORT_PATH}
    assert result.failed == ()
    assert write_spy == []
    assert store.read_bytes(part) == part_bytes
    assert store.read_bytes(REPORT_PATH) == report


def test_second_run_rewrites_nothing(
    store: OutputStore, write_spy: list[dict[str, Any]], fixture_scene: SceneItem
) -> None:
    files = _put_all_old(store, fixture_scene)
    first = _run(store)
    assert len(first.rewritten) == 4
    after_first = {path: store.read_bytes(path) for path in files}
    write_spy.clear()
    again = _run(store)
    assert again.rewritten == ()
    assert len(again.skipped) == 4
    assert again.failed == ()
    assert again.scanned == 4
    assert write_spy == []
    assert {path: store.read_bytes(path) for path in files} == after_first


def test_files_holding_a_notice_are_skipped_whatever_the_value(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    obs = pq.read_table(BytesIO(_obs_bytes()))
    marked = obs.replace_schema_metadata({**(obs.schema.metadata or {}), NOTICE: b"x"})
    buf = BytesIO()
    pq.write_table(marked, buf)
    files = {
        OBS_PATH: buf.getvalue(),
        REPORT_PATH: _dump({**_report_doc(), COPERNICUS_NOTICE_KEY: "whatever"}),
    }
    for path, data in files.items():
        store.write_bytes(path, data)
    write_spy.clear()
    result = _run(store)
    assert result.rewritten == ()
    assert result.skipped == (OBS_PATH, REPORT_PATH)
    assert write_spy == []
    for path, data in files.items():
        assert store.read_bytes(path) == data


def test_dry_run_lists_and_writes_nothing(
    store: OutputStore, write_spy: list[dict[str, Any]], fixture_scene: SceneItem
) -> None:
    files = _put_all_old(store, fixture_scene)
    write_spy.clear()
    result = _run(store, dry_run=True)
    assert result.dry_run is True
    assert result.rewritten == (OBS_PATH, CHG_PATH, REPORT_PATH, LEDGER_PATH)
    assert write_spy == []
    for path, data in files.items():
        assert store.read_bytes(path) == data


def test_a_junk_file_fails_without_stopping_the_others(
    store: OutputStore, fixture_scene: SceneItem
) -> None:
    files = _put_all_old(store, fixture_scene)
    junk = {
        observation_path(2026, "50HLK", "bad"): b"junk",
        "verification/badjson.json": b"{not json",
        "verification/array.json": b"[1, 2, 3]",
        "ledger/year=2026/ledger_bad.parquet": b"junk",
    }
    for path, data in junk.items():
        store.write_bytes(path, data)
    result = _run(store)
    assert result.scanned == len(files) + len(junk)
    failed = dict(result.failed)
    assert set(junk) <= set(failed)
    assert all(failed.values())
    assert failed["verification/array.json"] == "report is not a JSON object"
    assert OBS_PATH in result.rewritten
    for path, data in junk.items():
        assert store.read_bytes(path) == data


def test_unreadable_observation_history_fails_only_the_change_files(
    store: OutputStore,
) -> None:
    chg = _chg_bytes()
    store.write_bytes(CHG_PATH, chg)
    store.write_bytes(OBS_PATH, _obs_bytes())
    bad = observation_path(2026, "50HLK", "bad")
    store.write_bytes(bad, b"junk")
    result = _run(store)
    failed = dict(result.failed)
    assert failed[CHG_PATH] == "observation history could not be read"
    assert bad in failed
    assert OBS_PATH in result.rewritten
    assert store.read_bytes(CHG_PATH) == chg


def test_unreadable_ledger_fails_only_the_reports(store: OutputStore) -> None:
    report = _dump(_report_doc())
    store.write_bytes(REPORT_PATH, report)
    store.write_bytes(OBS_PATH, _obs_bytes())
    store.write_bytes("ledger/year=2026/ledger_bad.parquet", b"junk")
    result = _run(store)
    failed = dict(result.failed)
    assert failed[REPORT_PATH] == "ledger could not be read"
    assert OBS_PATH in result.rewritten
    assert store.read_bytes(REPORT_PATH) == report


def test_a_dropped_row_is_refused(
    store: OutputStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _obs_bytes()
    store.write_bytes(OBS_PATH, old)
    original = notice_backfill._with_metadata

    def drop_a_row(table: pa.Table, metadata: dict[bytes, bytes]) -> bytes:
        return original(table.slice(1), metadata)

    monkeypatch.setattr(notice_backfill, "_with_metadata", drop_a_row)
    result = _run(store)
    assert result.rewritten == ()
    assert [path for path, _ in result.failed] == [OBS_PATH]
    assert store.read_bytes(OBS_PATH) == old


def test_a_changed_json_value_is_refused(
    store: OutputStore, monkeypatch: pytest.MonkeyPatch, fixture_scene: SceneItem
) -> None:
    old = _dump(_report_doc())
    store.write_bytes(REPORT_PATH, old)
    _put_ledger(store, [_succeeded(_scene(fixture_scene, "S2A_A", _at(2026)))])

    def change_a_value(doc: dict[str, Any]) -> bytes:
        return _dump({**doc, "n_scored": 99})

    monkeypatch.setattr(notice_backfill, "_dump_json", change_a_value)
    result = _run(store)
    assert REPORT_PATH not in result.rewritten
    assert REPORT_PATH in dict(result.failed)
    assert store.read_bytes(REPORT_PATH) == old


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
    else:
        add_missing_notice(store, commit=COMMIT, on=ON)


def _entries(data: bytes) -> dict[bytes, bytes]:
    return {k: v for k, v in _meta(data).items() if k not in NOT_PROVENANCE}


def _after(tmp_path: Path, order: tuple[str, ...], path: str, data: bytes) -> bytes:
    store = OutputStore(str(tmp_path / "-".join(order)))
    store.write_bytes(path, data)
    for name in order:
        _apply(store, name)
    return store.read_bytes(path)


def test_the_three_backfills_commute_on_an_unfooted_observation_file(
    tmp_path: Path,
) -> None:
    old = _old_bytes(_rows(ITEM_A))
    path = observation_path(2026, "50HLK", ITEM_A)
    expected_keys = {
        *(key.encode() for key in FOOTER_KEYS),
        ADDED_KEY.encode(),
        DEA_ATTRIBUTION_KEY.encode(),
        DEA_ATTRIBUTION_ADDED_KEY.encode(),
        NOTICE,
        NOTICE_ADDED,
    }
    original = pq.read_table(BytesIO(old))
    finals = {
        order: _after(tmp_path, order, path, old)
        for order in itertools.permutations(("footers", "attribution", "notice"))
    }
    assert len(finals) == 6
    reference = _entries(next(iter(finals.values())))
    assert set(reference) == expected_keys
    for final in finals.values():
        assert _entries(final) == reference
        assert pq.read_table(BytesIO(final)).equals(original)


def test_attribution_and_notice_commute_on_a_change_file(tmp_path: Path) -> None:
    old = _chg_bytes()
    finals = [
        _after(tmp_path, order, CHG_PATH, old)
        for order in (("attribution", "notice"), ("notice", "attribution"))
    ]
    assert _entries(finals[0]) == _entries(finals[1])
    for final in finals:
        assert pq.read_table(BytesIO(final)).equals(pq.read_table(BytesIO(old)))
        for key, value in _meta(old).items():
            assert _meta(final)[key] == value
        assert set(_meta(final)) - set(_meta(old)) == {
            DEA_ATTRIBUTION_KEY.encode(),
            DEA_ATTRIBUTION_ADDED_KEY.encode(),
            NOTICE,
            NOTICE_ADDED,
        }


def test_attribution_and_notice_commute_on_a_report(
    tmp_path: Path, fixture_scene: SceneItem
) -> None:
    doc = _report_doc()
    finals: list[dict[str, Any]] = []
    for order in (("attribution", "notice"), ("notice", "attribution")):
        store = OutputStore(str(tmp_path / "-".join(order)))
        store.write_bytes(REPORT_PATH, _dump(doc))
        _put_ledger(store, [_succeeded(_scene(fixture_scene, "S2A_A", _at(2026)))])
        for name in order:
            _apply(store, name)
        finals.append(json.loads(store.read_bytes(REPORT_PATH)))
    assert finals[0] == finals[1]
    for final in finals:
        assert list(final)[: len(doc)] == list(doc)
        assert {key: final[key] for key in doc} == doc
        assert set(final) - set(doc) == {
            DEA_ATTRIBUTION_KEY,
            DEA_ATTRIBUTION_ADDED_KEY,
            COPERNICUS_NOTICE_KEY,
            COPERNICUS_NOTICE_ADDED_KEY,
        }


def test_write_content_types(
    store: OutputStore, write_spy: list[dict[str, Any]], fixture_scene: SceneItem
) -> None:
    _put_all_old(store, fixture_scene)
    write_spy.clear()
    _run(store)
    assert {call["relpath"]: call["content_type"] for call in write_spy} == {
        OBS_PATH: PARQUET,
        CHG_PATH: PARQUET,
        REPORT_PATH: JSON_TYPE,
        LEDGER_PATH: PARQUET,
    }


def test_only_expected_paths_are_scanned(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    ignored = {
        "observations/year=2026/tile=50HLK/notes.parquet": b"not parquet",
        "changes/year=2026/tile=50HLK/other.parquet": b"not parquet",
        "ledger/year=2026/readme.txt": b"not parquet",
        "verification/sub/x.json": b"{}",
        "verification/x.md": b"# report",
    }
    for path, data in ignored.items():
        store.write_bytes(path, data)
    store.write_bytes(OBS_PATH, _obs_bytes())
    write_spy.clear()
    result = _run(store)
    assert result.scanned == 1
    assert result.rewritten == (OBS_PATH,)
    assert result.failed == ()
    for path, data in ignored.items():
        assert store.read_bytes(path) == data
