"""Add the DBCA-010 attribution to published files written before it existed.

Term T3 of docs/research/2026-11-14-public-release-licences.md covers the
published files that carry DBCA-010 Ramsar Sites material, treated as CC BY-NC
4.0. `add_missing_dbca_attribution` rewrites each observation file and change
file that lacks `dbca_attribution` through the store. Each rewritten file gains
two footer keys: `dbca_attribution` (the block from `dbca_attribution.py` for
the kind of file, as sorted JSON) and `dbca_attribution_added_after_the_fact`
(the commit and date of the backfill, from `added_footer_value`).

The backfill is additive and independent of the other backfills. Rows, schema
and every other footer key are unchanged. A file that already holds
`dbca_attribution` is skipped untouched, whatever its value, so a second run
writes nothing.

Each rewrite is verified against the original before it is written. A mismatch
fails that file and leaves it as it was. One failing file does not stop the
others. Error messages name keys or checks, never a value from the file.

The verification JSON, ledger, run manifests and STAC objects hold no DBCA-010
material (the verification JSON holds polygon ids only) and are not scanned.
`build-catalogue` gives the collection and items the attribution.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from io import BytesIO

import pyarrow.parquet as pq

from wetland_change.dbca_attribution import (
    DBCA_ATTRIBUTION_ADDED_KEY,
    DBCA_ATTRIBUTION_KEY,
    DbcaKind,
    dbca_attribution_footer,
)
from wetland_change.outputs.attribution_backfill import (
    _change_paths,
    _with_metadata,
)
from wetland_change.outputs.footer_backfill import added_footer_value
from wetland_change.outputs.geoparquet import observation_paths
from wetland_change.store import CONTENT_TYPES, OutputStore


@dataclass(frozen=True)
class DbcaBackfillResult:
    """Outcome of one backfill run; `rewritten` is the would-be list in a dry run."""

    scanned: int
    rewritten: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]
    dry_run: bool


def _verify(old: bytes, new: bytes, kind: DbcaKind, added: str) -> None:
    old_table = pq.read_table(BytesIO(old))
    new_table = pq.read_table(BytesIO(new))
    if not old_table.schema.equals(new_table.schema, check_metadata=False):
        raise ValueError("schema changed")
    if not old_table.equals(new_table):
        raise ValueError("table contents changed")
    old_meta = old_table.schema.metadata or {}
    new_meta = new_table.schema.metadata or {}
    for key, value in old_meta.items():
        if key not in new_meta:
            raise ValueError(f"footer key {key.decode()} missing")
        if new_meta[key] != value:
            raise ValueError(f"footer key {key.decode()} changed")
    key_block = DBCA_ATTRIBUTION_KEY.encode()
    key_added = DBCA_ATTRIBUTION_ADDED_KEY.encode()
    if set(new_meta) != set(old_meta) | {key_block, key_added}:
        raise ValueError("footer keys are not the old keys plus the two added")
    expected = dbca_attribution_footer(kind)[DBCA_ATTRIBUTION_KEY].encode()
    if new_meta[key_block] != expected:
        raise ValueError(f"footer key {DBCA_ATTRIBUTION_KEY} does not match")
    if new_meta[key_added] != added.encode():
        raise ValueError(f"footer key {DBCA_ATTRIBUTION_ADDED_KEY} does not match")
    new_file_meta = pq.read_schema(BytesIO(new)).metadata or {}
    if new_file_meta != new_meta:
        raise ValueError("file footer differs from the table schema metadata")


def _backfill_file(
    store: OutputStore,
    path: str,
    data: bytes,
    *,
    kind: DbcaKind,
    added: str,
    dry_run: bool,
) -> bool:
    metadata = pq.read_schema(BytesIO(data)).metadata or {}
    if DBCA_ATTRIBUTION_KEY.encode() in metadata:
        return False
    table = pq.read_table(BytesIO(data))
    old = dict(table.schema.metadata or {})
    new_meta = {
        **old,
        DBCA_ATTRIBUTION_KEY.encode(): dbca_attribution_footer(kind)[
            DBCA_ATTRIBUTION_KEY
        ].encode(),
        DBCA_ATTRIBUTION_ADDED_KEY.encode(): added.encode(),
    }
    new = _with_metadata(table, new_meta)
    _verify(data, new, kind, added)
    if not dry_run:
        store.write_bytes(path, new, content_type=CONTENT_TYPES[".parquet"])
    return True


def add_missing_dbca_attribution(
    store: OutputStore,
    *,
    commit: str,
    on: datetime.date,
    dry_run: bool = False,
) -> DbcaBackfillResult:
    """Add the DBCA-010 attribution to every observation and change file lacking it."""
    added = added_footer_value(commit, on)
    targets: list[tuple[str, DbcaKind]] = [
        *((path, "observation") for path in observation_paths(store)),
        *((path, "change") for path in _change_paths(store)),
    ]
    rewritten: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []
    for path, kind in targets:
        try:
            data = store.read_bytes(path)
            changed = _backfill_file(
                store, path, data, kind=kind, added=added, dry_run=dry_run
            )
        except Exception as exc:
            failed.append((path, str(exc)))
            continue
        (rewritten if changed else skipped).append(path)
    return DbcaBackfillResult(
        scanned=len(targets),
        rewritten=tuple(rewritten),
        skipped=tuple(skipped),
        failed=tuple(failed),
        dry_run=dry_run,
    )
