from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from wetland_change.catalogue.item import SceneItem
from wetland_change.ledger import (
    LEDGER_SCHEMA,
    MAX_ATTEMPTS,
    attempts_so_far,
    entry_for,
    exhausted_keys,
    ledger_path,
    read_ledger,
    rejected_entry,
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
