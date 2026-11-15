from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import geopandas as gpd
import pyarrow.parquet as pq
import pytest
from geopandas.testing import assert_geodataframe_equal

from tests.test_geoparquet import ROWS, WATER, _row
from tests.test_store import _s3_store, _StubS3, stub_s3  # noqa: F401
from wetland_change.attribution import DEA_ATTRIBUTION_ADDED_KEY, DEA_ATTRIBUTION_KEY
from wetland_change.config import WaterConfig, WaterSetting
from wetland_change.outputs import footer_backfill
from wetland_change.outputs.footer_backfill import (
    ADDED_KEY,
    add_missing_footers,
    added_footer_value,
)
from wetland_change.outputs.geoparquet import (
    observation_path,
    rows_to_frame,
    to_geoparquet_bytes,
    write_observations,
)
from wetland_change.outputs.provenance import FOOTER_KEYS, footer_metadata
from wetland_change.stats import ObservationRow
from wetland_change.store import OutputStore

OPERATION_EPSG = 32750
COMMIT = "abc1234"
ON = date(2026, 11, 6)
PARQUET = "application/vnd.apache.parquet"
OVERRIDE_WATER = WaterConfig(
    method="mndwi",
    threshold=-0.1,
    overrides={
        "ramsar-56": WaterSetting(method="mndwi", threshold=0.05, agreement_min=0.9)
    },
)
ITEM_A = "S2C_T50HLK_20261027T022351_L2A"
ITEM_B = "S2C_T50HLK_20261030T022351_L2A"


def _rows(item_id: str) -> list[ObservationRow]:
    return [
        _row("ramsar-56", 115.93, item_id),
        _row("ramsar-52", 115.82, item_id),
    ]


def _old_bytes(rows: list[ObservationRow]) -> bytes:
    buf = BytesIO()
    rows_to_frame(rows).to_parquet(
        buf, index=False, schema_version="1.1.0", write_covering_bbox=True
    )
    return buf.getvalue()


def _put_old(store: OutputStore, item_id: str, data: bytes | None = None) -> str:
    path = observation_path(2026, "50HLK", item_id)
    store.write_bytes(path, data if data is not None else _old_bytes(_rows(item_id)))
    return path


def _run(store: OutputStore, *, dry_run: bool = False) -> Any:
    return add_missing_footers(
        store,
        water=OVERRIDE_WATER,
        operation_epsg=OPERATION_EPSG,
        commit=COMMIT,
        on=ON,
        dry_run=dry_run,
    )


def _meta(data: bytes) -> dict[bytes, bytes]:
    return dict(pq.read_schema(BytesIO(data)).metadata or {})


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


def test_footer_keys_match_footer_metadata() -> None:
    frame = rows_to_frame(ROWS)
    footer = footer_metadata(
        frame, kind="observation", water=WATER, operation_epsg=OPERATION_EPSG
    )
    assert FOOTER_KEYS == tuple(footer)
    assert len(FOOTER_KEYS) == 9


def test_rewrite_keeps_schema_rows_and_geo(store: OutputStore) -> None:
    path = _put_old(store, ITEM_A)
    old = store.read_bytes(path)
    result = _run(store)
    assert result.rewritten == (path,)
    new = store.read_bytes(path)
    old_table, new_table = pq.read_table(BytesIO(old)), pq.read_table(BytesIO(new))
    assert old_table.schema.equals(new_table.schema, check_metadata=False)
    assert old_table.equals(new_table)
    for key in (b"geo", b"pandas"):
        assert _meta(old)[key] == _meta(new)[key]
    assert_geodataframe_equal(
        gpd.read_parquet(BytesIO(old)), gpd.read_parquet(BytesIO(new))
    )


def test_footer_values_equal_footer_metadata(store: OutputStore) -> None:
    path = _put_old(store, ITEM_A)
    _run(store)
    new = store.read_bytes(path)
    expected = footer_metadata(
        gpd.read_parquet(BytesIO(new)),
        kind="observation",
        water=OVERRIDE_WATER,
        operation_epsg=OPERATION_EPSG,
    )
    meta = _meta(new)
    for key in FOOTER_KEYS:
        assert meta[key.encode()].decode() == expected[key]


def test_added_key_names_date_and_commit(store: OutputStore) -> None:
    path = _put_old(store, ITEM_A)
    _run(store)
    value = _meta(store.read_bytes(path))[ADDED_KEY.encode()].decode()
    assert json.loads(value) == {"commit": COMMIT, "date": "2026-11-06"}
    assert value == added_footer_value(COMMIT, ON)


def test_file_with_all_keys_is_skipped(store: OutputStore) -> None:
    path = observation_path(2026, "50HLK", ITEM_A)
    write_observations(
        _rows(ITEM_A), store, water=OVERRIDE_WATER, operation_epsg=OPERATION_EPSG
    )
    before = store.read_bytes(path)
    result = _run(store)
    assert result.skipped == (path,)
    assert result.rewritten == ()
    assert store.read_bytes(path) == before


def test_second_run_rewrites_nothing(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    paths = [_put_old(store, ITEM_A), _put_old(store, ITEM_B)]
    write_spy.clear()
    first = _run(store)
    assert first.rewritten == tuple(sorted(paths))
    after_first = {p: store.read_bytes(p) for p in paths}
    write_spy.clear()
    second = _run(store)
    assert second.rewritten == ()
    assert second.skipped == tuple(sorted(paths))
    assert second.scanned == 2
    assert {p: store.read_bytes(p) for p in paths} == after_first
    assert write_spy == []


def test_partial_footer_is_rewritten(store: OutputStore) -> None:
    frame = rows_to_frame(_rows(ITEM_A))
    units = footer_metadata(
        frame, kind="observation", water=OVERRIDE_WATER, operation_epsg=OPERATION_EPSG
    )["units"]
    path = _put_old(store, ITEM_A, to_geoparquet_bytes(frame, {"units": units}))
    result = _run(store)
    assert result.rewritten == (path,)
    meta = _meta(store.read_bytes(path))
    assert all(key.encode() in meta for key in FOOTER_KEYS)


def test_dry_run_lists_and_writes_nothing(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    paths = [_put_old(store, ITEM_A), _put_old(store, ITEM_B)]
    before = {p: store.read_bytes(p) for p in paths}
    write_spy.clear()
    result = _run(store, dry_run=True)
    assert result.dry_run is True
    assert result.rewritten == tuple(sorted(paths))
    assert {p: store.read_bytes(p) for p in paths} == before
    assert write_spy == []


def test_one_failure_does_not_stop_the_rest(store: OutputStore) -> None:
    bad = _put_old(store, ITEM_A, b"not a parquet file")
    good = _put_old(store, ITEM_B)
    result = _run(store)
    assert result.rewritten == (good,)
    assert [path for path, _ in result.failed] == [bad]
    assert result.failed[0][1]
    assert store.read_bytes(bad) == b"not a parquet file"
    assert ADDED_KEY.encode() in _meta(store.read_bytes(good))
    assert result.scanned == 2


def test_mismatch_is_refused(
    store: OutputStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _put_old(store, ITEM_A)
    before = store.read_bytes(path)
    real: Callable[..., bytes] = footer_backfill.to_geoparquet_bytes

    def drop_a_row(frame: gpd.GeoDataFrame, metadata: Any) -> bytes:
        return real(frame.iloc[:-1], metadata)

    monkeypatch.setattr(footer_backfill, "to_geoparquet_bytes", drop_a_row)
    result = _run(store)
    assert result.rewritten == ()
    assert [p for p, _ in result.failed] == [path]
    assert store.read_bytes(path) == before


def _put_old_with_extra_keys(store: OutputStore) -> tuple[str, dict[bytes, bytes]]:
    extras = {
        DEA_ATTRIBUTION_KEY.encode(): b'{"licence_uri": "x", "z": 1}',
        DEA_ATTRIBUTION_ADDED_KEY.encode(): (
            b'{"commit": "def5678", "date": "2026-11-14"}'
        ),
    }
    table = pq.read_table(BytesIO(_old_bytes(_rows(ITEM_A))))
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), **extras})
    buf = BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return _put_old(store, ITEM_A, buf.getvalue()), extras


def test_other_footer_keys_are_kept_unchanged(store: OutputStore) -> None:
    path, extras = _put_old_with_extra_keys(store)
    result = _run(store)
    assert result.rewritten == (path,)
    assert result.failed == ()
    meta = _meta(store.read_bytes(path))
    assert all(key.encode() in meta for key in FOOTER_KEYS)
    assert ADDED_KEY.encode() in meta
    for key, value in extras.items():
        assert meta[key] == value


def test_a_dropped_other_footer_key_is_refused(
    store: OutputStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, extras = _put_old_with_extra_keys(store)
    before = store.read_bytes(path)
    real: Callable[..., bytes] = footer_backfill.to_geoparquet_bytes
    dropped = {key.decode() for key in extras}

    def drop_kept(frame: gpd.GeoDataFrame, metadata: Any) -> bytes:
        return real(frame, {k: v for k, v in metadata.items() if k not in dropped})

    monkeypatch.setattr(footer_backfill, "to_geoparquet_bytes", drop_kept)
    result = _run(store)
    assert result.rewritten == ()
    assert [p for p, _ in result.failed] == [path]
    assert "footer key" in result.failed[0][1]
    assert store.read_bytes(path) == before


def test_only_obs_files_are_scanned(store: OutputStore) -> None:
    path = _put_old(store, ITEM_A)
    other = "observations/year=2026/tile=50HLK/notes.parquet"
    change = "changes/year=2026/obs_x.parquet"
    data = _old_bytes(_rows(ITEM_B))
    store.write_bytes(other, data)
    store.write_bytes(change, data)
    result = _run(store)
    assert result.scanned == 1
    assert result.rewritten == (path,)
    assert store.read_bytes(other) == data
    assert store.read_bytes(change) == data


def test_write_uses_the_store_with_the_parquet_content_type(
    store: OutputStore, write_spy: list[dict[str, Any]]
) -> None:
    path = _put_old(store, ITEM_A)
    write_spy.clear()
    _run(store)
    assert write_spy == [{"relpath": path, "content_type": PARQUET}]


def test_s3_write_keeps_the_parquet_content_type(
    stub_s3: _StubS3,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    s3 = _s3_store(stub_s3, monkeypatch, tmp_path)
    path = observation_path(2026, "50HLK", ITEM_A)
    old = _old_bytes(_rows(ITEM_A))
    monkeypatch.setattr(s3, "list_files", lambda prefix: [path])
    monkeypatch.setattr(s3, "read_bytes", lambda relpath: old)
    result = _run(s3)
    assert result.rewritten == (path,)
    creating = [
        ctype
        for method, req, ctype in stub_s3.requests
        if f"/prefix/{path}" in unquote(req)
        and "partNumber" not in req
        and (method == "PUT" or (method == "POST" and "uploads" in req))
    ]
    assert creating == [PARQUET], stub_s3.requests
    markers = [
        (method, key)
        for method, key in stub_s3.calls
        if method not in ("GET", "HEAD") and key.endswith("/")
    ]
    assert markers == [], stub_s3.calls
