from __future__ import annotations

import dataclasses
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from wetland_change.catalogue.item import SceneItem
from wetland_change.ledger import (
    LEDGER_SCHEMA,
    MAX_ATTEMPTS,
    RUN_KIND_BACKFILL,
    RUN_KIND_RUN,
    LedgerEntry,
    attempts_so_far,
    entries_to_table,
    entry_for,
    exhausted_ids,
    exhausted_keys,
    ledger_path,
    read_ledger,
    rejected_entry,
    requeue_entries,
    retry_ids,
    seen_keys,
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
