from __future__ import annotations

import dataclasses
import io
import math
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from wetland_change.catalogue.item import SceneItem
from wetland_change.ledger import (
    COMPACT_MIN_PARTS,
    LEDGER_SCHEMA,
    MAX_ATTEMPTS,
    RUN_KIND_BACKFILL,
    RUN_KIND_RUN,
    LedgerEntry,
    attempts_so_far,
    compact_ledger,
    entries_to_table,
    entry_for,
    exhausted_ids,
    exhausted_keys,
    latest_entries,
    ledger_path,
    ledger_with,
    observation_months,
    read_ledger,
    read_ledger_parts,
    rejected_entry,
    rejected_keys,
    requeue_entries,
    retry_ids,
    scored_dates,
    seen_keys,
    unfinished_runs,
    watermark,
    write_ledger,
)
from wetland_change.store import OutputStore

T0 = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)


def test_empty_ledger(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    ledger = read_ledger(store)
    assert ledger.num_rows == 0
    assert ledger.schema.equals(LEDGER_SCHEMA)
    assert watermark(ledger) is None
    assert seen_keys(ledger) == set()
    assert retry_ids(ledger) == []
    assert exhausted_keys(ledger) == set()
    assert attempts_so_far(ledger, "x") == 0


def test_ledger_path_partitions_by_run_year() -> None:
    assert (
        ledger_path("20261028T100000Z", 2026)
        == "ledger/year=2026/ledger_20261028T100000Z.parquet"
    )


def test_roundtrip_watermark_seen_and_retries(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    ok = entry_for(
        fixture_scene,
        status="succeeded",
        attempts=1,
        run_id="r1",
        processed_at=T0,
        n_rows=3,
        observation_path="observations/x.parquet",
    )
    bad = rejected_entry("bad-id", "collection mismatch", run_id="r1", processed_at=T0)
    files = write_ledger([ok, bad], store, run_id="r1")
    assert files == [ledger_path("r1", 2026)]

    ledger = read_ledger(store)
    assert ledger.num_rows == 2
    assert watermark(ledger) == fixture_scene.created
    assert seen_keys(ledger) == {(fixture_scene.item_id, fixture_scene.updated)}
    assert retry_ids(ledger) == []
    assert attempts_so_far(ledger, fixture_scene.item_id) == 1


def test_failed_entries_retry_until_max_attempts(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        entry = entry_for(
            fixture_scene,
            status="failed",
            attempts=attempt,
            run_id=f"r{attempt}",
            processed_at=T0 + timedelta(days=attempt),
            error="boom",
        )
        write_ledger([entry], store, run_id=f"r{attempt}")
        ledger = read_ledger(store)
        assert attempts_so_far(ledger, fixture_scene.item_id) == attempt
        expected = [fixture_scene.item_id] if attempt < MAX_ATTEMPTS else []
        assert retry_ids(ledger) == expected
        assert seen_keys(ledger) == set()
        key = (fixture_scene.item_id, fixture_scene.updated)
        assert exhausted_keys(ledger) == ({key} if attempt == MAX_ATTEMPTS else set())


def test_later_success_supersedes_failure(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    failed = entry_for(
        fixture_scene,
        status="failed",
        attempts=1,
        run_id="r1",
        processed_at=T0,
        error="x",
    )
    ok = entry_for(
        fixture_scene,
        status="succeeded",
        attempts=2,
        run_id="r2",
        processed_at=T0 + timedelta(hours=1),
        n_rows=1,
    )
    write_ledger([failed], store, run_id="r1")
    write_ledger([ok], store, run_id="r2")
    ledger = read_ledger(store)
    assert retry_ids(ledger) == []
    assert exhausted_keys(ledger) == set()
    assert seen_keys(ledger) == {(fixture_scene.item_id, fixture_scene.updated)}


def _late(scene: SceneItem) -> SceneItem:
    return dataclasses.replace(
        scene,
        item_id="late",
        created=scene.created + timedelta(days=5),
        updated=scene.updated + timedelta(days=5),
    )


def test_ledger_path_with_part(fixture_scene: SceneItem, tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    assert ledger_path("r1", 2026, 3) == "ledger/year=2026/ledger_r1_00003.parquet"
    entry = entry_for(
        fixture_scene, status="succeeded", attempts=1, run_id="r1", processed_at=T0
    )
    files = write_ledger([entry], store, run_id="r1", part=3)
    assert files == ["ledger/year=2026/ledger_r1_00003.parquet"]


def test_run_kind_defaults_to_run_and_round_trips(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    replaced = dataclasses.replace(fixture_scene, item_id="other")
    entries = [
        entry_for(
            fixture_scene, status="succeeded", attempts=1, run_id="r1", processed_at=T0
        ),
        entry_for(
            replaced,
            status="succeeded",
            attempts=1,
            run_id="r1",
            processed_at=T0,
            run_kind=RUN_KIND_BACKFILL,
        ),
        rejected_entry(
            "bad-id",
            "collection mismatch",
            run_id="r1",
            processed_at=T0,
            run_kind=RUN_KIND_BACKFILL,
        ),
    ]
    write_ledger(entries, store, run_id="r1")
    kinds = read_ledger(store).column("run_kind").to_pylist()
    assert kinds == ["run", "backfill", "backfill"]


def test_watermark_ignores_backfill_rows(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    late = _late(fixture_scene)
    daily = entry_for(
        fixture_scene, status="succeeded", attempts=1, run_id="r1", processed_at=T0
    )
    backfill = entry_for(
        late,
        status="succeeded",
        attempts=1,
        run_id="b1",
        processed_at=T0,
        run_kind=RUN_KIND_BACKFILL,
    )
    write_ledger([daily], store, run_id="r1")
    write_ledger([backfill], store, run_id="b1")
    ledger = read_ledger(store)
    assert watermark(ledger) == fixture_scene.created
    keys = seen_keys(ledger)
    assert (fixture_scene.item_id, fixture_scene.updated) in keys
    assert ("late", late.updated) in keys


def test_watermark_is_none_with_only_backfill_rows(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    backfill = entry_for(
        _late(fixture_scene),
        status="succeeded",
        attempts=1,
        run_id="b1",
        processed_at=T0,
        run_kind=RUN_KIND_BACKFILL,
    )
    write_ledger([backfill], store, run_id="b1")
    assert watermark(read_ledger(store)) is None


def test_reads_ledger_files_written_before_run_kind(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    seed = entries_to_table(
        [
            entry_for(
                fixture_scene, status="seed", attempts=0, run_id="seed", processed_at=T0
            )
        ]
    ).drop_columns(["run_kind"])
    buffer = io.BytesIO()
    pq.write_table(seed, buffer)
    store.write_bytes("ledger/year=2026/ledger_seed.parquet", buffer.getvalue())
    backfill = entry_for(
        _late(fixture_scene),
        status="succeeded",
        attempts=1,
        run_id="b1",
        processed_at=T0,
        run_kind=RUN_KIND_BACKFILL,
    )
    write_ledger([backfill], store, run_id="b1")
    ledger = read_ledger(store)
    assert ledger.schema.equals(LEDGER_SCHEMA)
    kinds = ledger.column("run_kind").to_pylist()
    assert sorted(v or "" for v in kinds) == ["", "backfill"]
    assert watermark(ledger) == fixture_scene.created


def _failed(scene: SceneItem, attempts: int, run_id: str, hours: int) -> LedgerEntry:
    return entry_for(
        scene,
        status="failed",
        attempts=attempts,
        run_id=run_id,
        processed_at=T0 + timedelta(hours=hours),
        error="boom",
    )


def test_exhausted_ids_empty_ledger() -> None:
    assert exhausted_ids(LEDGER_SCHEMA.empty_table()) == []


def test_exhausted_ids_only_after_max_attempts(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        write_ledger(
            [_failed(fixture_scene, attempt, f"r{attempt}", attempt)],
            store,
            run_id=f"r{attempt}",
        )
        expected = [fixture_scene.item_id] if attempt == MAX_ATTEMPTS else []
        assert exhausted_ids(read_ledger(store)) == expected
    assert exhausted_ids(read_ledger(store), max_attempts=MAX_ATTEMPTS + 1) == []


def test_exhausted_ids_drops_item_with_later_success(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    write_ledger([_failed(fixture_scene, MAX_ATTEMPTS, "r1", 0)], store, run_id="r1")
    assert exhausted_ids(read_ledger(store)) == [fixture_scene.item_id]
    ok = entry_for(
        fixture_scene,
        status="succeeded",
        attempts=MAX_ATTEMPTS + 1,
        run_id="r2",
        processed_at=T0 + timedelta(hours=1),
        n_rows=1,
    )
    write_ledger([ok], store, run_id="r2")
    assert exhausted_ids(read_ledger(store)) == []


def test_exhausted_ids_are_sorted(fixture_scene: SceneItem, tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    entries = [
        dataclasses.replace(
            _failed(fixture_scene, MAX_ATTEMPTS, "r1", 0), item_id=item_id
        )
        for item_id in ("b", "a", "c")
    ]
    write_ledger(entries, store, run_id="r1")
    assert exhausted_ids(read_ledger(store)) == ["a", "b", "c"]


def _exhausted_store(scene: SceneItem, tmp_path: Path) -> OutputStore:
    store = OutputStore(str(tmp_path))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        write_ledger(
            [_failed(scene, attempt, f"r{attempt}", attempt)],
            store,
            run_id=f"r{attempt}",
        )
    return store


def test_requeue_entries_make_an_exhausted_item_retryable(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = _exhausted_store(fixture_scene, tmp_path)
    ledger = read_ledger(store)
    assert exhausted_ids(ledger) == [fixture_scene.item_id]
    when = T0 + timedelta(days=1)
    entries = requeue_entries(
        ledger, [fixture_scene.item_id], run_id="rq", processed_at=when
    )
    assert len(entries) == 1
    write_ledger(entries, store, run_id="rq", part=0)
    after = read_ledger(store)
    assert retry_ids(after) == [fixture_scene.item_id]
    assert exhausted_keys(after) == set()
    assert exhausted_ids(after) == []
    assert attempts_so_far(after, fixture_scene.item_id) == 0
    row = entries[0]
    assert row.status == "failed"
    assert row.run_id == "rq"
    assert row.processed_at == when
    assert row.error == "requeued; previous error: boom"
    assert row.run_kind == RUN_KIND_RUN
    assert row.updated == fixture_scene.updated
    assert row.cloud_cover == fixture_scene.cloud_cover


def test_requeue_entries_preserve_run_kind_and_nulls(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    bare = dataclasses.replace(
        _failed(fixture_scene, MAX_ATTEMPTS, "r1", 0),
        run_kind=RUN_KIND_BACKFILL,
        cloud_cover=None,
        error=None,
        product_uri=None,
    )
    write_ledger([bare], store, run_id="r1")
    (entry,) = requeue_entries(
        read_ledger(store),
        [fixture_scene.item_id],
        run_id="rq",
        processed_at=T0 + timedelta(days=1),
    )
    assert entry.run_kind == RUN_KIND_BACKFILL
    assert entry.cloud_cover is None
    assert entry.product_uri is None
    assert entry.error == "requeued; previous error: None"
    assert isinstance(entry.attempts, int)
    assert isinstance(entry.n_rows, int)
    assert entry.created is not None and entry.created.tzinfo is not None


def test_requeue_entries_reject_ids_that_are_not_exhausted(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    write_ledger(
        [_failed(fixture_scene, MAX_ATTEMPTS - 1, "r1", 0)], store, run_id="r1"
    )
    ledger = read_ledger(store)
    with pytest.raises(ValueError, match="not exhausted") as excinfo:
        requeue_entries(
            ledger,
            [fixture_scene.item_id, "unknown"],
            run_id="rq",
            processed_at=T0 + timedelta(days=1),
        )
    assert fixture_scene.item_id in str(excinfo.value)
    assert "unknown" in str(excinfo.value)


def test_requeue_entries_reject_a_succeeded_item(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    ok = entry_for(
        fixture_scene,
        status="succeeded",
        attempts=1,
        run_id="r1",
        processed_at=T0,
        n_rows=1,
    )
    write_ledger([ok], store, run_id="r1")
    with pytest.raises(ValueError, match=fixture_scene.item_id):
        requeue_entries(
            read_ledger(store),
            [fixture_scene.item_id],
            run_id="rq",
            processed_at=T0 + timedelta(days=1),
        )


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(hours=-1)])
def test_requeue_entries_need_a_strictly_later_processed_at(
    fixture_scene: SceneItem, tmp_path: Path, offset: timedelta
) -> None:
    store = _exhausted_store(fixture_scene, tmp_path)
    latest = T0 + timedelta(hours=MAX_ATTEMPTS)
    with pytest.raises(ValueError, match="processed_at"):
        requeue_entries(
            read_ledger(store),
            [fixture_scene.item_id],
            run_id="rq",
            processed_at=latest + offset,
        )


# --- compaction -----------------------------------------------------------


def _one(
    scene: SceneItem,
    item_id: str,
    *,
    hours: int = 0,
    status: str = "succeeded",
    attempts: int = 1,
    run_id: str | None = None,
    **changes: Any,
) -> LedgerEntry:
    entry = entry_for(
        dataclasses.replace(scene, item_id=item_id),
        status=status,
        attempts=attempts,
        run_id=run_id or f"run-{item_id}",
        processed_at=T0 + timedelta(hours=hours),
        n_rows=1,
    )
    return dataclasses.replace(entry, **changes) if changes else entry


def _many_parts(scene: SceneItem, store: OutputStore, count: int) -> list[LedgerEntry]:
    entries = [
        _one(
            scene,
            f"item-{i:03d}",
            hours=i,
            status="failed" if i % 7 == 0 else "succeeded",
            attempts=1 + i % 3,
        )
        for i in range(count)
    ]
    for entry in entries:
        write_ledger([entry], store, run_id=entry.run_id)
    return entries


def _sorted_rows(table: pa.Table) -> list[dict[str, Any]]:
    return sorted(
        table.to_pylist(), key=lambda r: (r["item_id"], r["processed_at"], r["status"])
    )


def _derived(table: pa.Table) -> tuple[Any, ...]:
    latest = latest_entries(table)
    ids = sorted(latest["item_id"]) if not latest.empty else []
    return (
        watermark(table),
        seen_keys(table),
        retry_ids(table),
        exhausted_ids(table),
        ids,
    )


class CountingStore(OutputStore):
    def __init__(self, root: str) -> None:
        super().__init__(root)
        self.reads = 0

    def read_bytes(self, relpath: str) -> bytes:
        self.reads += 1
        return super().read_bytes(relpath)


def test_read_ledger_parts_returns_paths_and_the_same_table(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    _many_parts(fixture_scene, store, 3)
    table, paths = read_ledger_parts(store)
    assert paths == [p for p in store.list_files("ledger") if p.endswith(".parquet")]
    assert len(paths) == 3
    assert table.equals(read_ledger(store))
    empty, no_paths = read_ledger_parts(OutputStore(str(tmp_path / "nothing")))
    assert empty.num_rows == 0
    assert no_paths == []


def test_ledger_with_matches_a_fresh_read(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    _many_parts(fixture_scene, store, 3)
    before = read_ledger(store)
    entries = [
        _one(fixture_scene, "new-a", hours=50),
        _one(fixture_scene, "new-b", hours=51, status="failed", error="boom"),
    ]
    merged = ledger_with(before, entries)
    write_ledger(entries, store, run_id="r-new")
    assert _sorted_rows(merged) == _sorted_rows(read_ledger(store))
    assert ledger_with(before, []) is before


def test_compaction_leaves_one_file_and_identical_state(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    _many_parts(fixture_scene, store, 30)
    ledger, paths = read_ledger_parts(store)
    assert len(paths) == 30
    new = compact_ledger(store, ledger, paths, run_id="c1")
    assert new == ["ledger/compacted/ledger_compact_c1.parquet"]
    assert store.list_files("ledger") == new
    after = read_ledger(store)
    assert _sorted_rows(after) == _sorted_rows(ledger)
    assert _derived(after) == _derived(ledger)


def test_default_threshold_compacts_at_25_parts(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    assert COMPACT_MIN_PARTS == 25
    store = OutputStore(str(tmp_path))
    _many_parts(fixture_scene, store, 25)
    ledger, paths = read_ledger_parts(store)
    assert len(compact_ledger(store, ledger, paths, run_id="c1")) == 1
    assert len(store.list_files("ledger")) == 1


def test_compaction_is_a_noop_below_threshold_and_when_empty(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    _many_parts(fixture_scene, store, 24)
    ledger, paths = read_ledger_parts(store)
    before = store.list_files("ledger")
    assert compact_ledger(store, ledger, paths, run_id="c1") == []
    assert store.list_files("ledger") == before
    empty = LEDGER_SCHEMA.empty_table()
    assert compact_ledger(store, empty, paths, run_id="c1", min_parts=1) == []
    assert store.list_files("ledger") == before


def _write_compacted_only(store: OutputStore, ledger: pa.Table, run_id: str) -> str:
    buffer = io.BytesIO()
    pq.write_table(ledger, buffer)
    return store.write_bytes(
        f"ledger/compacted/ledger_compact_{run_id}.parquet", buffer.getvalue()
    )


def test_crash_after_compacted_write_reads_without_duplicates(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    _many_parts(fixture_scene, store, 5)
    original = read_ledger(store)
    _write_compacted_only(store, original, "c1")
    table, paths = read_ledger_parts(store)
    assert len(paths) == 6
    assert paths[0].startswith("ledger/compacted/")
    assert table.num_rows == original.num_rows
    assert _sorted_rows(table) == _sorted_rows(original)


def test_crash_dedupe_keeps_rows_that_share_run_and_time(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    a = _one(fixture_scene, "same", run_id="r1", status="failed", error="x")
    b = _one(fixture_scene, "same", run_id="r1", status="succeeded")
    write_ledger([a, b], store, run_id="r1")
    original = read_ledger(store)
    _write_compacted_only(store, original, "c1")
    table = read_ledger(store)
    assert table.num_rows == 2
    assert sorted(table["status"].to_pylist()) == ["failed", "succeeded"]


def test_crash_dedupe_treats_null_and_nan_as_equal(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    entry = _one(
        fixture_scene,
        "odd",
        cloud_cover=math.nan,
        error=None,
        product_uri=None,
        datetime=None,
    )
    write_ledger([entry], store, run_id="r1")
    original = read_ledger(store)
    _write_compacted_only(store, original, "c1")
    table = read_ledger(store)
    assert table.num_rows == 1
    assert math.isnan(table["cloud_cover"].to_pylist()[0])


def test_no_dedupe_without_a_compacted_file(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    entry = _one(fixture_scene, "dup", run_id="r1")
    write_ledger([entry], store, run_id="r1")
    write_ledger([entry], store, run_id="r2")
    assert read_ledger(store).num_rows == 2


def test_reads_are_bounded_after_compaction(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = CountingStore(str(tmp_path))
    _many_parts(fixture_scene, store, 100)
    ledger, paths = read_ledger_parts(store)
    compact_ledger(store, ledger, paths, run_id="c1")
    for i in range(3):
        write_ledger(
            [_one(fixture_scene, f"late-{i}", hours=200 + i)],
            store,
            run_id=f"late-{i}",
        )
    store.reads = 0
    table = read_ledger(store)
    assert store.reads == 4
    assert table.num_rows == 103


class _VerifyStore(OutputStore):
    """Read-back of the compacted object returns a file with fewer rows."""

    def read_bytes(self, relpath: str) -> bytes:
        data = super().read_bytes(relpath)
        if "compacted" not in relpath:
            return data
        table = pq.read_table(io.BytesIO(data)).slice(0, 1)
        buffer = io.BytesIO()
        pq.write_table(table, buffer)
        return buffer.getvalue()


def test_compaction_refuses_to_delete_when_read_back_is_short(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = _VerifyStore(str(tmp_path))
    _many_parts(fixture_scene, store, 5)
    ledger, paths = read_ledger_parts(store)
    with pytest.raises(ValueError, match="rows"):
        compact_ledger(store, ledger, paths, run_id="c1", min_parts=1)
    for path in paths:
        assert store.exists(path)


class _TruncatingStore(OutputStore):
    """Truncates the first write under ledger/compacted/ (a partial upload)."""

    truncate = True

    def write_bytes(self, relpath: str, data: bytes) -> str:
        if self.truncate and "compacted" in relpath:
            data = data[: len(data) // 2]
        return super().write_bytes(relpath, data)


def test_failed_read_back_removes_the_bad_compacted_file(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = _TruncatingStore(str(tmp_path))
    _many_parts(fixture_scene, store, 5)
    ledger, paths = read_ledger_parts(store)
    with pytest.raises(Exception):  # noqa: B017
        compact_ledger(store, ledger, paths, run_id="c1", min_parts=1)
    assert not store.exists("ledger/compacted/ledger_compact_c1.parquet")
    for path in paths:
        assert store.exists(path)
    assert read_ledger(store).num_rows == ledger.num_rows
    store.truncate = False
    new = compact_ledger(store, ledger, paths, run_id="c2", min_parts=1)
    assert len(new) == 1
    assert store.list_files("ledger") == new
    assert read_ledger(store).num_rows == ledger.num_rows


def test_compaction_only_deletes_listed_paths(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    _many_parts(fixture_scene, store, 5)
    ledger, paths = read_ledger_parts(store)
    (late,) = write_ledger([_one(fixture_scene, "late")], store, run_id="late")
    new = compact_ledger(store, ledger, paths, run_id="c1", min_parts=1)
    assert sorted(store.list_files("ledger")) == sorted([late, *new])
    assert read_ledger(store).num_rows == 6


class _RacingStore(OutputStore):
    """Deletes a listed part right after the first listing (a concurrent compaction)."""

    def __init__(self, root: str, victim: str) -> None:
        super().__init__(root)
        self.victim = victim
        self.listings = 0

    def list_files(self, prefix: str) -> list[str]:
        files = super().list_files(prefix)
        self.listings += 1
        if self.listings == 1:
            self.delete(self.victim)
        return files


def test_a_part_deleted_after_listing_is_recovered_by_one_relist(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    plain = OutputStore(str(tmp_path))
    _many_parts(fixture_scene, plain, 5)
    original = read_ledger(plain)
    _write_compacted_only(plain, original, "c1")
    victim = "ledger/year=2026/ledger_run-item-002.parquet"
    store = _RacingStore(str(tmp_path), victim)
    table, paths = read_ledger_parts(store)
    assert store.listings == 2
    assert victim not in paths
    assert _sorted_rows(table) == _sorted_rows(original)


class _AlwaysMissingStore(OutputStore):
    def read_bytes(self, relpath: str) -> bytes:
        raise FileNotFoundError(relpath)


def test_a_second_missing_part_propagates(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    _many_parts(fixture_scene, OutputStore(str(tmp_path)), 2)
    with pytest.raises(FileNotFoundError):
        read_ledger(_AlwaysMissingStore(str(tmp_path)))


def test_second_compaction_after_a_crash_leaves_one_file(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    _many_parts(fixture_scene, store, 5)
    original = read_ledger(store)
    _write_compacted_only(store, original, "crashed")
    ledger, paths = read_ledger_parts(store)
    new = compact_ledger(store, ledger, paths, run_id="c2", min_parts=1)
    assert store.list_files("ledger") == new
    assert _sorted_rows(read_ledger(store)) == _sorted_rows(original)
    again, again_paths = read_ledger_parts(store)
    assert compact_ledger(store, again, again_paths, run_id="c2", min_parts=1) == new
    assert store.list_files("ledger") == new


def test_observation_months_uses_utc_and_skips_nulls(
    fixture_scene: SceneItem,
) -> None:
    perth = timezone(timedelta(hours=8))
    # 2026-02-01 05:00 +08:00 is 2026-01-31 21:00 UTC: month 1, not 2.
    entries = [
        _one(
            fixture_scene,
            "a",
            observation_path="obs/a.parquet",
            datetime=datetime(2026, 2, 1, 5, 0, tzinfo=perth),
        ),
        _one(
            fixture_scene,
            "b",
            observation_path="obs/a.parquet",
            datetime=datetime(2026, 3, 5, tzinfo=UTC),
        ),
        _one(
            fixture_scene,
            "c",
            observation_path="obs/a.parquet",
            datetime=None,
        ),
        _one(
            fixture_scene,
            "d",
            observation_path=None,
            datetime=datetime(2026, 7, 5, tzinfo=UTC),
        ),
        _one(
            fixture_scene,
            "e",
            observation_path="obs/nodate.parquet",
            datetime=None,
        ),
    ]
    months = observation_months(entries_to_table(entries))
    assert months == {"obs/a.parquet": {1, 3}, "obs/nodate.parquet": set()}
    assert observation_months(LEDGER_SCHEMA.empty_table()) == {}


# --- unfinished runs ------------------------------------------------------


def test_unfinished_runs_empty_ledger_is_empty() -> None:
    assert unfinished_runs(entries_to_table([]), set()) == {}


def test_unfinished_run_returns_all_its_rows(fixture_scene: SceneItem) -> None:
    entries = [
        _one(fixture_scene, "a", run_id="r1"),
        _one(fixture_scene, "b", run_id="r1", status="failed"),
        rejected_entry("bad", "collection mismatch", run_id="r1", processed_at=T0),
    ]
    found = unfinished_runs(entries_to_table(entries), set())
    assert list(found) == ["r1"]
    assert sorted(found["r1"]["item_id"]) == ["a", "b", "bad"]
    assert sorted(found["r1"]["status"]) == ["failed", "rejected", "succeeded"]


def test_finished_run_is_not_returned(fixture_scene: SceneItem) -> None:
    entries = [
        _one(fixture_scene, "a", run_id="r1"),
        _one(fixture_scene, "b", run_id="r2"),
    ]
    found = unfinished_runs(entries_to_table(entries), {"r1"})
    assert list(found) == ["r2"]


def test_backfill_rows_are_never_unfinished(fixture_scene: SceneItem) -> None:
    entries = [
        _one(fixture_scene, "a", run_id="b1", run_kind=RUN_KIND_BACKFILL),
        _one(fixture_scene, "b", run_id="r1"),
    ]
    found = unfinished_runs(entries_to_table(entries), set())
    assert list(found) == ["r1"]


def test_run_with_only_backfill_rows_is_absent(fixture_scene: SceneItem) -> None:
    entries = [_one(fixture_scene, "a", run_id="b1", run_kind=RUN_KIND_BACKFILL)]
    assert unfinished_runs(entries_to_table(entries), set()) == {}


def test_null_run_kind_counts_as_a_daily_row(fixture_scene: SceneItem) -> None:
    table = entries_to_table([_one(fixture_scene, "a", run_id="old")])
    nulls = pa.array([None], type=pa.string())
    table = table.set_column(
        table.schema.get_field_index("run_kind"), "run_kind", nulls
    )
    found = unfinished_runs(table, set())
    assert list(found) == ["old"]
    assert list(found["old"]["item_id"]) == ["a"]


def test_later_success_under_another_run_does_not_hide_the_crashed_run(
    fixture_scene: SceneItem,
) -> None:
    entries = [
        _one(fixture_scene, "a", run_id="r1", status="failed", hours=0),
        _one(fixture_scene, "a", run_id="r2", hours=1),
    ]
    found = unfinished_runs(entries_to_table(entries), {"r2"})
    assert list(found) == ["r1"]
    assert list(found["r1"]["item_id"]) == ["a"]
    assert list(found["r1"]["status"]) == ["failed"]


def test_unfinished_runs_are_ordered_by_run_id(fixture_scene: SceneItem) -> None:
    entries = [
        _one(fixture_scene, "a", run_id="20261029T000000Z"),
        _one(fixture_scene, "b", run_id="20261027T000000Z"),
        _one(fixture_scene, "c", run_id="20261028T000000Z"),
    ]
    found = unfinished_runs(entries_to_table(entries), set())
    assert list(found) == [
        "20261027T000000Z",
        "20261028T000000Z",
        "20261029T000000Z",
    ]


def test_unfinished_runs_accepts_any_collection_of_ids(
    fixture_scene: SceneItem,
) -> None:
    table = entries_to_table([_one(fixture_scene, "a", run_id="r1")])
    assert unfinished_runs(table, frozenset({"r1"})) == {}
    assert unfinished_runs(table, ["r1"]) == {}


# --- scored dates ---------------------------------------------------------


def test_scored_dates_uses_utc_and_skips_unscored_rows(
    fixture_scene: SceneItem,
) -> None:
    perth = timezone(timedelta(hours=8))
    entries = [
        # 2026-02-01 05:00 +08:00 is 2026-01-31 21:00 UTC.
        _one(
            fixture_scene,
            "a",
            observation_path="obs/a.parquet",
            datetime=datetime(2026, 2, 1, 5, 0, tzinfo=perth),
        ),
        # Just before UTC midnight stays on its own UTC date.
        _one(
            fixture_scene,
            "b",
            observation_path="obs/b.parquet",
            datetime=datetime(2026, 3, 5, 23, 59, 59, tzinfo=UTC),
        ),
        _one(
            fixture_scene,
            "failed",
            status="failed",
            observation_path="obs/f.parquet",
            datetime=datetime(2026, 4, 1, tzinfo=UTC),
        ),
        _one(
            fixture_scene,
            "nopath",
            observation_path=None,
            datetime=datetime(2026, 5, 1, tzinfo=UTC),
        ),
        _one(fixture_scene, "nodate", observation_path="obs/n.parquet", datetime=None),
    ]
    frame = entries_to_table(entries).to_pandas()
    assert scored_dates(frame) == {date(2026, 1, 31), date(2026, 3, 5)}


def test_scored_dates_of_an_empty_frame_is_empty() -> None:
    assert scored_dates(entries_to_table([]).to_pandas()) == set()


UPDATED = datetime(2026, 10, 27, 3, 4, 5, 123456, tzinfo=UTC)


def _rejected(
    item_id: str, run_id: str, hours: int, *, updated: datetime | None = UPDATED
) -> LedgerEntry:
    return rejected_entry(
        item_id,
        "ItemGuardError: wrong collection",
        run_id=run_id,
        processed_at=T0 + timedelta(hours=hours),
        updated=updated,
    )


def test_rejected_entry_stores_updated_and_defaults_to_none() -> None:
    assert _rejected("x", "r1", 0).updated == UPDATED
    legacy = rejected_entry("x", "why", run_id="r1", processed_at=T0)
    assert legacy.updated is None


def test_rejected_keys_empty_ledger() -> None:
    assert rejected_keys(LEDGER_SCHEMA.empty_table()) == set()


def test_rejected_keys_returns_newest_matching_rejection(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    write_ledger([_rejected("x", "r1", 0)], store, run_id="r1")
    assert rejected_keys(read_ledger(store)) == {
        ("x", UPDATED, "ItemGuardError: wrong collection")
    }


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_rejected_keys_excludes_item_with_later_non_rejected_row(
    fixture_scene: SceneItem, tmp_path: Path, status: str
) -> None:
    store = OutputStore(str(tmp_path))
    write_ledger([_rejected(fixture_scene.item_id, "r1", 0)], store, run_id="r1")
    later = entry_for(
        fixture_scene,
        status=status,
        attempts=1,
        run_id="r2",
        processed_at=T0 + timedelta(hours=1),
        n_rows=1 if status == "succeeded" else 0,
        error="boom" if status == "failed" else None,
    )
    write_ledger([later], store, run_id="r2")
    assert rejected_keys(read_ledger(store)) == set()


def test_rejected_keys_excludes_null_updated_rows(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    write_ledger([_rejected("x", "r1", 0, updated=None)], store, run_id="r1")
    assert rejected_keys(read_ledger(store)) == set()
