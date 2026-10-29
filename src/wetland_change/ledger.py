"""Ledger of processed source items: one parquet file per run.

Fixed schema so files union cleanly, plus the full source item as JSON so
the catalogue can be rebuilt from the ledger alone. The latest entry per
item wins; a failed item is retried on the next runs until MAX_ATTEMPTS.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from wetland_change.catalogue.item import SceneItem
from wetland_change.store import OutputStore

MAX_ATTEMPTS = 3
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
    )


def rejected_entry(
    item_id: str, reason: str, *, run_id: str, processed_at: dt.datetime
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
    )


def ledger_path(run_id: str, year: int) -> str:
    return f"ledger/year={year}/ledger_{run_id}.parquet"


def entries_to_table(entries: Sequence[LedgerEntry]) -> pa.Table:
    columns: dict[str, list[Any]] = {
        name: [getattr(entry, name) for entry in entries]
        for name in LEDGER_SCHEMA.names
    }
    return pa.table(columns, schema=LEDGER_SCHEMA)


def write_ledger(
    entries: Sequence[LedgerEntry], store: OutputStore, *, run_id: str
) -> list[str]:
    """One file per run (partitioned by the run's year)."""
    if not entries:
        return []
    year = entries[0].processed_at.year
    buffer = BytesIO()
    pq.write_table(entries_to_table(entries), buffer)
    return [store.write_bytes(ledger_path(run_id, year), buffer.getvalue())]


def read_ledger(store: OutputStore) -> pa.Table:
    paths = [p for p in store.list_files("ledger") if p.endswith(".parquet")]
    if not paths:
        return LEDGER_SCHEMA.empty_table()
    tables = [
        pq.read_table(BytesIO(store.read_bytes(path))).cast(LEDGER_SCHEMA)
        for path in paths
    ]
    return pa.concat_tables(tables)


def watermark(ledger: pa.Table) -> dt.datetime | None:
    """Latest `created` seen, succeeded or failed."""
    if ledger.num_rows == 0:
        return None
    value = pc.max(ledger["created"]).as_py()
    return value if isinstance(value, dt.datetime) else None


def _latest(ledger: pa.Table) -> pd.DataFrame:
    frame = ledger.to_pandas()
    if frame.empty:
        return frame
    ordered = frame.sort_values(["processed_at", "run_id"], kind="stable")
    return ordered.groupby("item_id", sort=False).tail(1)


def seen_keys(ledger: pa.Table) -> set[tuple[str, dt.datetime]]:
    latest = _latest(ledger)
    if latest.empty:
        return set()
    ok = latest[latest["status"] == "succeeded"]
    return {
        (str(row.item_id), row.updated.to_pydatetime())
        for row in ok.itertuples(index=False)
    }


def retry_ids(ledger: pa.Table, *, max_attempts: int = MAX_ATTEMPTS) -> list[str]:
    latest = _latest(ledger)
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
    latest = _latest(ledger)
    if latest.empty:
        return set()
    done = latest[(latest["status"] == "failed") & (latest["attempts"] >= max_attempts)]
    return {
        (str(row.item_id), row.updated.to_pydatetime())
        for row in done.itertuples(index=False)
    }


def attempts_so_far(ledger: pa.Table, item_id: str) -> int:
    latest = _latest(ledger)
    if latest.empty:
        return 0
    match = latest[latest["item_id"] == item_id]
    return int(match["attempts"].iloc[0]) if not match.empty else 0
