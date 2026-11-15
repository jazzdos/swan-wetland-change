"""Add the DEA attribution to published files written before it existed.

Term T1 of docs/research/2026-11-14-public-release-licences.md found that
published files carrying Geoscience Australia DEA data (CC BY 4.0) have no
attribution. `add_missing_attribution` rewrites each observation file, change
file and verification report that lacks `dea_attribution` through the store.
Parquet files gain two footer keys and reports gain two top-level fields:
`dea_attribution` (the block from `attribution.py` for the kind of file) and
`dea_attribution_added_after_the_fact` (the commit and date of the backfill).

The backfill is additive. Every existing column, row, Arrow schema and footer
entry of a Parquet file is unchanged, and every existing field of a report
keeps its value and its position, `generated_at` included. A file that already
holds `dea_attribution` is skipped untouched, whatever its value, so a second
run writes nothing.

Each rewrite is verified against the original before it is written. A mismatch
fails that file and leaves it as it was. One failing file does not stop the
others. Error messages name keys or checks, never a value from the file, and
nothing is printed of file content.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq

from wetland_change.attribution import (
    DEA_ATTRIBUTION_ADDED_KEY,
    DEA_ATTRIBUTION_KEY,
    dea_attribution,
    dea_attribution_footer,
)
from wetland_change.outputs.footer_backfill import added_footer_value
from wetland_change.outputs.geoparquet import observation_paths
from wetland_change.store import CONTENT_TYPES, OutputStore

ParquetKind = Literal["observation", "change"]


@dataclass(frozen=True)
class AttributionBackfillResult:
    """Outcome of one backfill run; `rewritten` is the would-be list in a dry run."""

    scanned: int
    rewritten: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]
    dry_run: bool


def _change_paths(store: OutputStore) -> list[str]:
    return [
        path
        for path in store.list_files("changes")
        if path.rsplit("/", 1)[-1].startswith("chg_") and path.endswith(".parquet")
    ]


def _report_paths(store: OutputStore) -> list[str]:
    return [
        path
        for path in store.list_files("verification")
        if path.endswith(".json") and path.count("/") == 1
    ]


def _with_metadata(table: pa.Table, metadata: dict[bytes, bytes]) -> bytes:
    """Parquet bytes of `table` with `metadata` as its footer entries."""
    buf = BytesIO()
    pq.write_table(table.replace_schema_metadata(metadata), buf, compression="snappy")
    return buf.getvalue()


def _verify_parquet(old: bytes, new: bytes, kind: ParquetKind) -> None:
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
    added = {DEA_ATTRIBUTION_KEY.encode(), DEA_ATTRIBUTION_ADDED_KEY.encode()}
    if set(new_meta) != set(old_meta) | added:
        raise ValueError("footer keys are not the old keys plus the two added")
    expected = dea_attribution_footer(kind)[DEA_ATTRIBUTION_KEY].encode()
    if new_meta[DEA_ATTRIBUTION_KEY.encode()] != expected:
        raise ValueError(f"footer key {DEA_ATTRIBUTION_KEY} does not match")


def _backfill_parquet(
    store: OutputStore,
    path: str,
    data: bytes,
    *,
    kind: ParquetKind,
    added: str,
    dry_run: bool,
) -> bool:
    metadata = pq.read_schema(BytesIO(data)).metadata or {}
    if DEA_ATTRIBUTION_KEY.encode() in metadata:
        return False
    table = pq.read_table(BytesIO(data))
    old = dict(table.schema.metadata or {})
    new_meta = {
        **old,
        DEA_ATTRIBUTION_KEY.encode(): dea_attribution_footer(kind)[
            DEA_ATTRIBUTION_KEY
        ].encode(),
        DEA_ATTRIBUTION_ADDED_KEY.encode(): added.encode(),
    }
    new = _with_metadata(table, new_meta)
    _verify_parquet(data, new, kind)
    if not dry_run:
        store.write_bytes(path, new, content_type=CONTENT_TYPES[".parquet"])
    return True


def _dump_json(doc: dict[str, Any]) -> bytes:
    """The serialisation `verify.checks.write_report` uses."""
    return json.dumps(doc, indent=2, default=str, allow_nan=False).encode()


def _verify_json(doc: dict[str, Any], new: bytes) -> None:
    parsed = json.loads(new)
    if not isinstance(parsed, dict):
        raise ValueError("rewritten report is not a JSON object")
    if list(parsed)[: len(doc)] != list(doc):
        raise ValueError("report keys changed or were reordered")
    for key, value in doc.items():
        if parsed[key] != value:
            raise ValueError(f"report field {key} changed")
    extra = list(parsed)[len(doc) :]
    if (
        set(extra) != {DEA_ATTRIBUTION_KEY, DEA_ATTRIBUTION_ADDED_KEY}
        or len(extra) != 2
    ):
        raise ValueError("report keys are not the old keys plus the two added")
    if parsed[DEA_ATTRIBUTION_KEY] != dea_attribution("verification"):
        raise ValueError(f"report field {DEA_ATTRIBUTION_KEY} does not match")


def _backfill_json(
    store: OutputStore,
    path: str,
    data: bytes,
    *,
    commit: str,
    on: datetime.date,
    dry_run: bool,
) -> bool:
    doc = json.loads(data)
    if not isinstance(doc, dict):
        raise ValueError("report is not a JSON object")
    if DEA_ATTRIBUTION_KEY in doc:
        return False
    new_doc = {
        **doc,
        DEA_ATTRIBUTION_KEY: dea_attribution("verification"),
        DEA_ATTRIBUTION_ADDED_KEY: {"commit": commit, "date": on.isoformat()},
    }
    new = _dump_json(new_doc)
    _verify_json(doc, new)
    if not dry_run:
        store.write_bytes(path, new, content_type=CONTENT_TYPES[".json"])
    return True


def add_missing_attribution(
    store: OutputStore,
    *,
    commit: str,
    on: datetime.date,
    dry_run: bool = False,
) -> AttributionBackfillResult:
    """Add the DEA attribution to every observation, change and report lacking it."""
    added = added_footer_value(commit, on)
    targets: list[tuple[str, Literal["observation", "change", "verification"]]] = [
        *((path, "observation") for path in observation_paths(store)),
        *((path, "change") for path in _change_paths(store)),
        *((path, "verification") for path in _report_paths(store)),
    ]
    rewritten: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []
    for path, kind in targets:
        try:
            data = store.read_bytes(path)
            if kind == "verification":
                changed = _backfill_json(
                    store, path, data, commit=commit, on=on, dry_run=dry_run
                )
            else:
                changed = _backfill_parquet(
                    store, path, data, kind=kind, added=added, dry_run=dry_run
                )
        except Exception as exc:
            failed.append((path, str(exc)))
            continue
        (rewritten if changed else skipped).append(path)
    return AttributionBackfillResult(
        scanned=len(targets),
        rewritten=tuple(rewritten),
        skipped=tuple(skipped),
        failed=tuple(failed),
        dry_run=dry_run,
    )
