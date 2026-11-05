"""Ledger of processed source items: one parquet file per run.

Fixed schema so files union cleanly, plus the full source item as JSON so
the catalogue can be rebuilt from the ledger alone. The latest entry per
item wins; a failed item is retried on the next runs until MAX_ATTEMPTS.

Every row carries `run_kind` ("run" for the daily run, "backfill" for a
backfill). The daily watermark ignores backfill rows, since backfilled items
can carry recent `created` values that would otherwise make the daily search
skip items it has never processed. Files written before a column existed
read it as null; a null `run_kind` counts as a daily row.

Compaction merges many small parts into one file under `ledger/compacted/`
so a read costs a bounded number of requests. It keeps every row and edits
none. The compacted file is written and read back (row count checked) before
any part is deleted, because the bucket is public and unversioned and a
delete is permanent. A crash between the write and the deletes therefore
leaves duplicates, never losses, and `read_ledger` drops whole-row
duplicates whenever a compacted file is listed beside other parts.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from io import BytesIO
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from wetland_change.catalogue.item import SceneItem
from wetland_change.store import OutputStore

MAX_ATTEMPTS = 3
COMPACT_MIN_PARTS = 25
COMPACTED_PREFIX = "ledger/compacted/"
RUN_KIND_RUN = "run"
RUN_KIND_BACKFILL = "backfill"
_TS = pa.timestamp("us", tz="UTC")
LEDGER_SCHEMA = pa.schema(
    [
        ("item_id", pa.string()),
        ("collection", pa.string()),
        ("datetime", _TS),
        ("created", _TS),
        ("updated", _TS),
        ("tile", pa.string()),
        ("cloud_cover", pa.float64()),
        ("product_uri", pa.string()),
        ("status", pa.string()),
        ("attempts", pa.int32()),
        ("error", pa.string()),
        ("run_id", pa.string()),
        ("processed_at", _TS),
        ("n_rows", pa.int32()),
        ("observation_path", pa.string()),
        ("source_item", pa.string()),
        ("run_kind", pa.string()),
    ]
)


@dataclass(frozen=True)
class LedgerEntry:
    item_id: str
    collection: str | None
    datetime: dt.datetime | None
    created: dt.datetime | None
    updated: dt.datetime | None
    tile: str | None
    cloud_cover: float | None
    product_uri: str | None
    status: str
    attempts: int
    error: str | None
    run_id: str
    processed_at: dt.datetime
    n_rows: int
    observation_path: str | None
    source_item: str | None
    run_kind: str = RUN_KIND_RUN


def entry_for(
    scene: SceneItem,
    *,
    status: str,
    attempts: int,
    run_id: str,
    processed_at: dt.datetime,
    n_rows: int = 0,
    observation_path: str | None = None,
    error: str | None = None,
    run_kind: str = RUN_KIND_RUN,
) -> LedgerEntry:
    return LedgerEntry(
        item_id=scene.item_id,
        collection=scene.collection,
        datetime=scene.datetime,
        created=scene.created,
        updated=scene.updated,
        tile=scene.tile,
        cloud_cover=scene.cloud_cover,
        product_uri=scene.product_uri,
        status=status,
        attempts=attempts,
        error=error,
        run_id=run_id,
        processed_at=processed_at,
        n_rows=n_rows,
        observation_path=observation_path,
        source_item=json.dumps(scene.raw, sort_keys=True),
        run_kind=run_kind,
    )


def rejected_entry(
    item_id: str,
    reason: str,
    *,
    run_id: str,
    processed_at: dt.datetime,
    run_kind: str = RUN_KIND_RUN,
) -> LedgerEntry:
    """An item the guard refused; never retried, re-logged while it is in range."""
    return LedgerEntry(
        item_id=item_id,
        collection=None,
        datetime=None,
        created=None,
        updated=None,
        tile=None,
        cloud_cover=None,
        product_uri=None,
        status="rejected",
        attempts=0,
        error=reason,
        run_id=run_id,
        processed_at=processed_at,
        n_rows=0,
        observation_path=None,
        source_item=None,
        run_kind=run_kind,
    )


def ledger_path(run_id: str, year: int, part: int | None = None) -> str:
    suffix = "" if part is None else f"_{part:05d}"
    return f"ledger/year={year}/ledger_{run_id}{suffix}.parquet"


def entries_to_table(entries: Sequence[LedgerEntry]) -> pa.Table:
    columns: dict[str, list[Any]] = {
        name: [getattr(entry, name) for entry in entries]
        for name in LEDGER_SCHEMA.names
    }
    return pa.table(columns, schema=LEDGER_SCHEMA)


def write_ledger(
    entries: Sequence[LedgerEntry],
    store: OutputStore,
    *,
    run_id: str,
    part: int | None = None,
) -> list[str]:
    """One file per run, or per part of a run (partitioned by the run's year)."""
    if not entries:
        return []
    year = entries[0].processed_at.year
    buffer = BytesIO()
    pq.write_table(entries_to_table(entries), buffer)
    return [store.write_bytes(ledger_path(run_id, year, part), buffer.getvalue())]


def _conform(table: pa.Table) -> pa.Table:
    """Add any column the file predates (as nulls) and cast to LEDGER_SCHEMA."""
    for field in LEDGER_SCHEMA:
        if field.name not in table.schema.names:
            table = table.append_column(
                field, pa.nulls(table.num_rows, type=field.type)
            )
    return table.select(LEDGER_SCHEMA.names).cast(LEDGER_SCHEMA)


def _list_parts(store: OutputStore) -> list[str]:
    return [p for p in store.list_files("ledger") if p.endswith(".parquet")]


def _read_parts(store: OutputStore, paths: list[str]) -> pa.Table:
    tables = [
        _conform(pq.read_table(BytesIO(store.read_bytes(path)))) for path in paths
    ]
    return pa.concat_tables(tables)


def _drop_duplicate_rows(table: pa.Table) -> pa.Table:
    """Drop rows equal across every column, keeping the first occurrence.

    Rows are keyed on `repr` of the whole row so null and NaN compare equal.
    Never a subset of columns: rows of one run share `processed_at`.
    """
    columns = [table[name].to_pylist() for name in table.schema.names]
    seen: set[str] = set()
    keep: list[bool] = []
    for row in zip(*columns, strict=True):
        key = repr(row)
        keep.append(key not in seen)
        seen.add(key)
    if all(keep):
        return table
    return table.filter(pa.array(keep, type=pa.bool_()))


def read_ledger_parts(store: OutputStore) -> tuple[pa.Table, list[str]]:
    """The whole ledger plus the part paths it was read from.

    A concurrent compaction can delete a listed part, so a missing part
    triggers one re-list and re-read; a second miss propagates.
    """
    for attempt in range(2):
        paths = _list_parts(store)
        if not paths:
            return LEDGER_SCHEMA.empty_table(), []
        try:
            table = _read_parts(store, paths)
        except FileNotFoundError:
            if attempt == 1:
                raise
            continue
        if len(paths) > 1 and any(p.startswith(COMPACTED_PREFIX) for p in paths):
            table = _drop_duplicate_rows(table)
        return table, paths
    raise AssertionError("unreachable")  # pragma: no cover


def read_ledger(store: OutputStore) -> pa.Table:
    return read_ledger_parts(store)[0]


def ledger_with(ledger: pa.Table, entries: Sequence[LedgerEntry]) -> pa.Table:
    """`ledger` plus `entries`, as a fresh read would give after they were written."""
    if not entries:
        return ledger
    return pa.concat_tables([ledger, entries_to_table(entries)])


def compact_ledger(
    store: OutputStore,
    ledger: pa.Table,
    paths: Sequence[str],
    *,
    run_id: str,
    min_parts: int = COMPACT_MIN_PARTS,
) -> list[str]:
    """Merge the listed parts into one compacted file; returns its path or [].

    `ledger` must be the table read from exactly `paths`. Every row is kept.
    The new file is written and read back before any delete, and only paths
    in `paths` are deleted, so a part written after the listing survives. A
    failed read-back removes the new file (unless it was already listed), so
    a bad compacted file never stays in the ledger.
    """
    if len(paths) < min_parts or ledger.num_rows == 0:
        return []
    new_path = f"{COMPACTED_PREFIX}ledger_compact_{run_id}.parquet"
    buffer = BytesIO()
    pq.write_table(ledger, buffer)
    store.write_bytes(new_path, buffer.getvalue())
    try:
        written = pq.read_metadata(BytesIO(store.read_bytes(new_path))).num_rows
        if written != ledger.num_rows:
            raise ValueError(
                f"compacted ledger {new_path} read back {written} rows, expected "
                f"{ledger.num_rows}; no part was deleted"
            )
    except Exception:
        if new_path not in paths:
            store.delete(new_path)
        raise
    for path in paths:
        if path != new_path:
            store.delete(path)
    return [new_path]


def observation_months(ledger: pa.Table) -> dict[str, set[int]]:
    """UTC months of each observation file's rows (non-null datetimes only)."""
    months: dict[str, set[int]] = {}
    paths = ledger["observation_path"].to_pylist()
    stamps = ledger["datetime"].to_pylist()
    for path, stamp in zip(paths, stamps, strict=True):
        if path is None:
            continue
        found = months.setdefault(path, set())
        if stamp is not None:
            found.add(stamp.astimezone(dt.UTC).month)
    return months


def watermark(ledger: pa.Table) -> dt.datetime | None:
    """Latest `created` seen in daily-run rows, succeeded or failed.

    Backfill rows are excluded: backfill works by acquisition date and its
    items can carry recent `created` values, which would push the watermark
    past items the daily run has never processed. A null `run_kind` (a file
    written before the column existed) counts as a daily row.
    """
    if ledger.num_rows == 0:
        return None
    mask = pc.fill_null(pc.not_equal(ledger["run_kind"], RUN_KIND_BACKFILL), True)
    created = ledger["created"].filter(mask)
    if len(created) == 0:
        return None
    value = pc.max(created).as_py()
    return value if isinstance(value, dt.datetime) else None


def unfinished_runs(
    ledger: pa.Table, finished_run_ids: Collection[str]
) -> dict[str, pd.DataFrame]:
    """Daily-run ledger rows of every run not in `finished_run_ids`, by run_id.

    A daily run with ledger rows and no manifest did not finish. Backfill rows
    are skipped, and a null `run_kind` counts as a daily row, as in
    `watermark`. All rows are used, not `latest_entries`, so a later attempt
    by another run does not hide what the crashed run did.
    """
    if ledger.num_rows == 0:
        return {}
    mask = pc.fill_null(pc.not_equal(ledger["run_kind"], RUN_KIND_BACKFILL), True)
    frame = ledger.filter(mask).to_pandas()
    finished = set(finished_run_ids)
    return {
        str(run_id): rows.reset_index(drop=True)
        for run_id, rows in frame.groupby("run_id", sort=True)
        if run_id not in finished
    }


def scored_dates(rows: pd.DataFrame) -> set[dt.date]:
    """UTC dates of succeeded rows that wrote observations.

    Matches the condition `run_once` uses to collect the dates it scores.
    """
    done = rows[
        (rows["status"] == "succeeded")
        & rows["observation_path"].notna()
        & rows["datetime"].notna()
    ]
    return {
        stamp.to_pydatetime().astimezone(dt.UTC).date() for stamp in done["datetime"]
    }


def latest_entries(ledger: pa.Table) -> pd.DataFrame:
    frame = ledger.to_pandas()
    if frame.empty:
        return frame
    ordered = frame.sort_values(["processed_at", "run_id"], kind="stable")
    return ordered.groupby("item_id", sort=False).tail(1)


def seen_keys(ledger: pa.Table) -> set[tuple[str, dt.datetime]]:
    latest = latest_entries(ledger)
    if latest.empty:
        return set()
    ok = latest[latest["status"] == "succeeded"]
    return {
        (str(row.item_id), row.updated.to_pydatetime())
        for row in ok.itertuples(index=False)
    }


def retry_ids(ledger: pa.Table, *, max_attempts: int = MAX_ATTEMPTS) -> list[str]:
    latest = latest_entries(ledger)
    if latest.empty:
        return []
    failed = latest[
        (latest["status"] == "failed") & (latest["attempts"] < max_attempts)
    ]
    return sorted(str(item_id) for item_id in failed["item_id"])


def exhausted_keys(
    ledger: pa.Table, *, max_attempts: int = MAX_ATTEMPTS
) -> set[tuple[str, dt.datetime]]:
    """Items that failed `max_attempts` times; skipped until republished."""
    latest = latest_entries(ledger)
    if latest.empty:
        return set()
    done = latest[(latest["status"] == "failed") & (latest["attempts"] >= max_attempts)]
    return {
        (str(row.item_id), row.updated.to_pydatetime())
        for row in done.itertuples(index=False)
    }


def exhausted_ids(ledger: pa.Table, *, max_attempts: int = MAX_ATTEMPTS) -> list[str]:
    """Sorted ids whose latest row is failed with `max_attempts` or more attempts."""
    latest = latest_entries(ledger)
    if latest.empty:
        return []
    done = latest[(latest["status"] == "failed") & (latest["attempts"] >= max_attempts)]
    return sorted(str(item_id) for item_id in done["item_id"])


def _nullable(value: Any) -> Any:
    return None if pd.isna(value) else value


def _nullable_str(value: Any) -> str | None:
    return None if pd.isna(value) else str(value)


def _nullable_time(value: Any) -> dt.datetime | None:
    if pd.isna(value):
        return None
    stamp = pd.Timestamp(value)
    stamp = (
        stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    )
    result: dt.datetime = stamp.to_pydatetime()
    return result


def _entry_from_row(row: Any) -> LedgerEntry:
    processed_at = _nullable_time(row.processed_at)
    if processed_at is None:
        raise ValueError(f"ledger row for {row.item_id} has no processed_at")
    cloud_cover = _nullable(row.cloud_cover)
    return LedgerEntry(
        item_id=str(row.item_id),
        collection=_nullable_str(row.collection),
        datetime=_nullable_time(row.datetime),
        created=_nullable_time(row.created),
        updated=_nullable_time(row.updated),
        tile=_nullable_str(row.tile),
        cloud_cover=None if cloud_cover is None else float(cloud_cover),
        product_uri=_nullable_str(row.product_uri),
        status=str(row.status),
        attempts=int(row.attempts),
        error=_nullable_str(row.error),
        run_id=str(row.run_id),
        processed_at=processed_at,
        n_rows=0 if pd.isna(row.n_rows) else int(row.n_rows),
        observation_path=_nullable_str(row.observation_path),
        source_item=_nullable_str(row.source_item),
        run_kind=_nullable_str(row.run_kind) or RUN_KIND_RUN,
    )


def requeue_entries(
    ledger: pa.Table,
    item_ids: Sequence[str],
    *,
    run_id: str,
    processed_at: dt.datetime,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[LedgerEntry]:
    """Fresh-attempt copies of the latest rows of exhausted items.

    Each copy keeps status 'failed' with attempts reset to 0, so `retry_ids`
    returns the item and the next daily run retries it. Requeue edits no
    existing row; the copies are appended as new rows, and compaction later
    merges parts without changing any row. `processed_at` must be after the
    item's latest row, otherwise the copy would sort before it and be ignored.
    """
    exhausted = set(exhausted_ids(ledger, max_attempts=max_attempts))
    missing = sorted(set(item_ids) - exhausted)
    if missing:
        raise ValueError(
            "not exhausted (unknown, succeeded, under the attempt cap or "
            f"rejected): {', '.join(missing)}"
        )
    latest = latest_entries(ledger)
    wanted = latest[latest["item_id"].isin(set(item_ids))]
    entries: list[LedgerEntry] = []
    for row in wanted.sort_values("item_id").itertuples(index=False):
        old = _entry_from_row(row)
        if processed_at <= old.processed_at:
            raise ValueError(
                f"processed_at {processed_at.isoformat()} is not after the latest "
                f"row of {old.item_id} ({old.processed_at.isoformat()}); rerun "
                "with a later --now"
            )
        entries.append(
            replace(
                old,
                attempts=0,
                error=f"requeued; previous error: {old.error}",
                run_id=run_id,
                processed_at=processed_at,
            )
        )
    return entries


def attempts_so_far(ledger: pa.Table, item_id: str) -> int:
    latest = latest_entries(ledger)
    if latest.empty:
        return 0
    match = latest[latest["item_id"] == item_id]
    return int(match["attempts"].iloc[0]) if not match.empty else 0
