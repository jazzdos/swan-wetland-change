from __future__ import annotations

import json
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from geopandas.testing import assert_geodataframe_equal

from tests.test_change_outputs import GEOMETRIES, ITEM, _scores
from tests.test_footer_backfill import _old_bytes, _rows
from tests.test_geoparquet import ROWS
from wetland_change.attribution import (
    DEA_ATTRIBUTION_ADDED_KEY,
    DEA_ATTRIBUTION_KEY,
    dea_attribution,
    dea_attribution_footer,
)
from wetland_change.config import WaterConfig
from wetland_change.outputs import attribution_backfill
from wetland_change.outputs.attribution_backfill import add_missing_attribution
from wetland_change.outputs.changes import change_path, changes_to_frame
from wetland_change.outputs.geoparquet import (
    observation_path,
    rows_to_frame,
    to_geoparquet_bytes,
)
from wetland_change.outputs.provenance import FOOTER_KEYS, footer_metadata
from wetland_change.store import OutputStore

COMMIT = "abc1234"
ON = date(2026, 11, 15)
WATER = WaterConfig(method="mndwi", threshold=-0.1)
PARQUET = "application/vnd.apache.parquet"
JSON_TYPE = "application/json"
RUN_ID = "20261115T000000Z"
REPORT_PATH = f"verification/{RUN_ID}.json"
OBS_PATH = observation_path(2026, "50HLK", "S2A_A")
CHG_PATH = change_path(2026, "50HLK", ITEM)


def _meta(data: bytes) -> dict[bytes, bytes]:
    return dict(pq.read_schema(BytesIO(data)).metadata or {})


def _obs_bytes(*, attributed: bool = False) -> bytes:
    frame = rows_to_frame(ROWS)
    footer = footer_metadata(
        frame, kind="observation", water=WATER, operation_epsg=32750
    )
    if attributed:
        footer = {**footer, **dea_attribution_footer("observation")}
    return to_geoparquet_bytes(frame, footer)


def _chg_bytes(*, attributed: bool = False) -> bytes:
    frame = changes_to_frame(_scores(), GEOMETRIES)
    footer = footer_metadata(frame, kind="change", water=WATER, operation_epsg=32750)
    if attributed:
        footer = {**footer, **dea_attribution_footer("change")}
    return to_geoparquet_bytes(frame, footer)


def _report_doc() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "generated_at": "2026-11-10T01:02:03+00:00",
        "n_scored": 2,
        "n_skipped": 0,
        "n_errored": 0,
        "n_warned": 0,
        "n_advisory": 1,
        "all_passed": True,
        "matrix": {"water": ["a", "b"]},
        "advisory": [{"check": "x", "value": 0.5}],
        "runtime": {"python": "3.13.0"},
        "uv_lock_sha256": "f" * 8,
        "git_commit": "deadbee",
        "checks": [
            {
                "name": "ndvi_vs_dea",
                "passed": True,
                "value": 0.8539,
                "detail": {"n": 12, "median": 0.8539, "nested": {"ok": True}},
            }
        ],
    }


def _dump(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, indent=2, default=str, allow_nan=False).encode()


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
    return add_missing_attribution(store, commit=COMMIT, on=ON, dry_run=dry_run)


def _put_all_old(store: OutputStore) -> dict[str, bytes]:
    files = {
        OBS_PATH: _obs_bytes(),
        CHG_PATH: _chg_bytes(),
        REPORT_PATH: _dump(_report_doc()),
    }
    for path, data in files.items():
        store.write_bytes(path, data)
    return files


def test_footered_observation_gains_only_the_two_keys(store: OutputStore) -> None:
    old = _obs_bytes()
    store.write_bytes(OBS_PATH, old)
    result = _run(store)
    assert result.rewritten == (OBS_PATH,)
    new = store.read_bytes(OBS_PATH)
    old_table, new_table = pq.read_table(BytesIO(old)), pq.read_table(BytesIO(new))
    assert new_table.equals(old_table)
    assert new_table.schema.equals(old_table.schema, check_metadata=False)
    old_meta, new_meta = _meta(old), _meta(new)
    for key in (b"geo", b"pandas", *(k.encode() for k in FOOTER_KEYS)):
        assert key in old_meta
        assert new_meta[key] == old_meta[key]
    for key, value in old_meta.items():
        assert new_meta[key] == value
    assert set(new_meta) == set(old_meta) | {
        DEA_ATTRIBUTION_KEY.encode(),
        DEA_ATTRIBUTION_ADDED_KEY.encode(),
    }
    assert json.loads(new_meta[DEA_ATTRIBUTION_KEY.encode()]) == dea_attribution(
        "observation"
    )
    assert json.loads(new_meta[DEA_ATTRIBUTION_ADDED_KEY.encode()]) == {
        "commit": COMMIT,
        "date": "2026-11-15",
    }
    assert_geodataframe_equal(
        gpd.read_parquet(BytesIO(new)), gpd.read_parquet(BytesIO(old))
    )


def test_unfooted_observation_adds_no_provenance_key(store: OutputStore) -> None:
    old = _old_bytes(_rows("S2A_A"))
    store.write_bytes(OBS_PATH, old)
    result = _run(store)
    assert result.rewritten == (OBS_PATH,)
    old_meta, new_meta = _meta(old), _meta(store.read_bytes(OBS_PATH))
    assert set(new_meta) - set(old_meta) == {
        DEA_ATTRIBUTION_KEY.encode(),
        DEA_ATTRIBUTION_ADDED_KEY.encode(),
    }
    assert not any(k.encode() in new_meta for k in FOOTER_KEYS)
    for key, value in old_meta.items():
        assert new_meta[key] == value


def test_change_file_gets_the_change_attribution(store: OutputStore) -> None:
    old = _chg_bytes()
    store.write_bytes(CHG_PATH, old)
    result = _run(store)
    assert result.rewritten == (CHG_PATH,)
    new = store.read_bytes(CHG_PATH)
    assert pq.read_table(BytesIO(new)).equals(pq.read_table(BytesIO(old)))
    new_meta = _meta(new)
    assert (
        new_meta[DEA_ATTRIBUTION_KEY.encode()]
        == dea_attribution_footer("change")[DEA_ATTRIBUTION_KEY].encode()
    )
    for key, value in _meta(old).items():
        assert new_meta[key] == value


def test_verification_json_keeps_order_and_values(store: OutputStore) -> None:
    doc = _report_doc()
    store.write_bytes(REPORT_PATH, _dump(doc))
    result = _run(store)
    assert result.rewritten == (REPORT_PATH,)
    new = json.loads(store.read_bytes(REPORT_PATH))
    assert list(new)[: len(doc)] == list(doc)
    for key, value in doc.items():
        assert new[key] == value
    assert new["generated_at"] == doc["generated_at"]
    assert list(new)[len(doc) :] == [DEA_ATTRIBUTION_KEY, DEA_ATTRIBUTION_ADDED_KEY]
    assert new[DEA_ATTRIBUTION_KEY] == dea_attribution("verification")
    assert new[DEA_ATTRIBUTION_ADDED_KEY] == {"commit": COMMIT, "date": "2026-11-15"}


def test_already_attributed_files_are_skipped_untouched(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    doc = {**_report_doc(), DEA_ATTRIBUTION_KEY: "whatever"}
    files = {
        OBS_PATH: _obs_bytes(attributed=True),
        CHG_PATH: _chg_bytes(attributed=True),
        REPORT_PATH: _dump(doc),
    }
    for path, data in files.items():
        store.write_bytes(path, data)
    write_spy.clear()
    result = _run(store)
    assert result.rewritten == ()
    assert result.skipped == (OBS_PATH, CHG_PATH, REPORT_PATH)
    assert result.scanned == 3
    assert write_spy == []
    for path, data in files.items():
        assert store.read_bytes(path) == data


def test_second_run_rewrites_nothing(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    _put_all_old(store)
    first = _run(store)
    assert len(first.rewritten) == 3
    after_first = {p: store.read_bytes(p) for p in first.rewritten}
    write_spy.clear()
    again = _run(store)
    assert again.rewritten == ()
    assert len(again.skipped) == 3
    assert again.failed == ()
    assert write_spy == []
    assert {p: store.read_bytes(p) for p in first.rewritten} == after_first


def test_dry_run_lists_and_writes_nothing(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    files = _put_all_old(store)
    write_spy.clear()
    result = _run(store, dry_run=True)
    assert result.dry_run is True
    assert result.rewritten == (OBS_PATH, CHG_PATH, REPORT_PATH)
    assert write_spy == []
    for path, data in files.items():
        assert store.read_bytes(path) == data


def test_bad_files_fail_without_stopping_the_others(store: OutputStore) -> None:
    files = _put_all_old(store)
    junk = {
        observation_path(2026, "50HLK", "bad"): b"junk",
        "verification/badjson.json": b"{not json",
        "verification/array.json": b"[1, 2, 3]",
    }
    for path, data in junk.items():
        store.write_bytes(path, data)
    result = _run(store)
    assert result.scanned == 6
    assert set(result.rewritten) == set(files)
    assert {path for path, _ in result.failed} == set(junk)
    assert all(message for _, message in result.failed)
    assert dict(result.failed)["verification/array.json"] == (
        "report is not a JSON object"
    )
    for path, data in junk.items():
        assert store.read_bytes(path) == data


def test_dropped_row_is_refused(
    store: OutputStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _obs_bytes()
    store.write_bytes(OBS_PATH, old)
    original = attribution_backfill._with_metadata

    def drop_a_row(table: pa.Table, metadata: dict[bytes, bytes]) -> bytes:
        return original(table.slice(1), metadata)

    monkeypatch.setattr(attribution_backfill, "_with_metadata", drop_a_row)
    result = _run(store)
    assert result.rewritten == ()
    assert [path for path, _ in result.failed] == [OBS_PATH]
    assert store.read_bytes(OBS_PATH) == old


def test_changed_json_value_is_refused(
    store: OutputStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _dump(_report_doc())
    store.write_bytes(REPORT_PATH, old)

    def change_a_value(doc: dict[str, Any]) -> bytes:
        return _dump({**doc, "n_scored": 99})

    monkeypatch.setattr(attribution_backfill, "_dump_json", change_a_value)
    result = _run(store)
    assert result.rewritten == ()
    assert [path for path, _ in result.failed] == [REPORT_PATH]
    assert store.read_bytes(REPORT_PATH) == old


def test_reordered_json_keys_are_refused(
    store: OutputStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _dump(_report_doc())
    store.write_bytes(REPORT_PATH, old)

    def reverse(doc: dict[str, Any]) -> bytes:
        return _dump(dict(reversed(list(doc.items()))))

    monkeypatch.setattr(attribution_backfill, "_dump_json", reverse)
    result = _run(store)
    assert [path for path, _ in result.failed] == [REPORT_PATH]
    assert store.read_bytes(REPORT_PATH) == old


def test_only_expected_paths_are_scanned(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    ignored = {
        "observations/year=2026/tile=50HLK/notes.parquet": b"not parquet",
        "changes/year=2026/tile=50HLK/other.parquet": b"not parquet",
        "changes/year=2026/tile=50HLK/chg_x.txt": b"not parquet",
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
    assert [call["relpath"] for call in write_spy] == [OBS_PATH]
    for path, data in ignored.items():
        assert store.read_bytes(path) == data


def test_write_content_types(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    _put_all_old(store)
    write_spy.clear()
    _run(store)
    assert {call["relpath"]: call["content_type"] for call in write_spy} == {
        OBS_PATH: PARQUET,
        CHG_PATH: PARQUET,
        REPORT_PATH: JSON_TYPE,
    }
