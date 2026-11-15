"""Add the Copernicus Sentinel data notice to published files written before it.

Term T2 of docs/research/2026-11-14-public-release-licences.md found that
published files computed from Sentinel-2 data carry no Copernicus notice.
`add_missing_notice` rewrites each observation file, change file, verification
report and ledger part that lacks `copernicus_notice` through the store.
Parquet files gain two footer keys and reports gain two top-level fields:
`copernicus_notice` (the block from `sentinel_notice.py` for the kind of file,
with the UTC acquisition years of the file's content) and
`copernicus_notice_added_after_the_fact` (the commit and date of the backfill).

The years follow the rule of each kind in `sentinel_notice.py`. An observation
file uses the years of its `datetime` column and a ledger part those of its
`datetime` column when it has one. A change file adds the years of the stored
observations of its polygons, in the same calendar month on strictly earlier
UTC dates, the history its baselines were built from. That history is read once
from every observation file's `polygon_id` and `datetime` columns. A report
uses `verify.run.verification_years` on the ledger, read once. A file with no
acquisition year is skipped untouched, because a notice without a year would
be wrong.

The backfill is additive and independent of `add_missing_footers` and
`add_missing_attribution`: it adds only its own two keys, skips a file that
already holds `copernicus_notice`, whatever its value, and keeps every other
footer entry and JSON field with its value and position, `generated_at`
included. The three backfills therefore run in any order, and a second run
writes nothing.

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

import pandas as pd
import pyarrow.parquet as pq

from wetland_change.change import baseline_source_years
from wetland_change.ledger import read_ledger
from wetland_change.outputs.attribution_backfill import (
    _change_paths,
    _dump_json,
    _report_paths,
    _with_metadata,
)
from wetland_change.outputs.footer_backfill import added_footer_value
from wetland_change.outputs.geoparquet import observation_paths
from wetland_change.sentinel_notice import (
    COPERNICUS_NOTICE_ADDED_KEY,
    COPERNICUS_NOTICE_KEY,
    copernicus_notice,
    copernicus_notice_footer,
    utc_years,
)
from wetland_change.store import CONTENT_TYPES, OutputStore
from wetland_change.verify.run import verification_years

TargetKind = Literal["observation", "change", "verification", "ledger"]
ParquetKind = Literal["observation", "change", "ledger"]


@dataclass(frozen=True)
class NoticeBackfillResult:
    """Outcome of one backfill run; `rewritten` is the would-be list in a dry run."""

    scanned: int
    rewritten: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]
    dry_run: bool


class _StoredContext:
    """The observation history and the ledger, each read once and only if needed.

    A failed read is remembered, so every file that needs it fails with the
    same message and the store is not read again.
    """

    def __init__(self, store: OutputStore) -> None:
        self._store = store
        self._history: pd.DataFrame | None = None
        self._history_failed = False
        self._ledger: Any = None
        self._ledger_failed = False

    def history(self) -> pd.DataFrame:
        if self._history_failed:
            raise ValueError("observation history could not be read")
        if self._history is None:
            try:
                frames = [
                    pq.read_table(
                        BytesIO(self._store.read_bytes(path)),
                        columns=["polygon_id", "datetime"],
                    ).to_pandas()
                    for path in observation_paths(self._store)
                ]
                self._history = (
                    pd.concat(frames, ignore_index=True)
                    if frames
                    else pd.DataFrame({"polygon_id": [], "datetime": []})
                )
            except Exception as exc:
                self._history_failed = True
                raise ValueError("observation history could not be read") from exc
        return self._history

    def ledger(self) -> Any:
        if self._ledger_failed:
            raise ValueError("ledger could not be read")
        if self._ledger is None:
            try:
                self._ledger = read_ledger(self._store)
            except Exception as exc:
                self._ledger_failed = True
                raise ValueError("ledger could not be read") from exc
        return self._ledger


def _parquet_years(
    data: bytes, kind: ParquetKind, context: _StoredContext
) -> tuple[int, ...]:
    names = pq.read_schema(BytesIO(data)).names
    if kind == "ledger" and "datetime" not in names:
        return ()
    columns = ["datetime"] if kind != "change" else ["polygon_id", "datetime"]
    frame = pq.read_table(BytesIO(data), columns=columns).to_pandas()
    years = set(utc_years(frame["datetime"]))
    if kind == "change":
        history = context.history()
        stamps = pd.to_datetime(frame["datetime"], utc=True)
        polygon_ids = set(frame["polygon_id"])
        for day in sorted(set(stamps.dt.date)):
            years |= baseline_source_years(history, polygon_ids=polygon_ids, day=day)
    return tuple(sorted(years))


def _verify_parquet(
    old: bytes, new: bytes, years: tuple[int, ...], kind: ParquetKind
) -> None:
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
    added = {COPERNICUS_NOTICE_KEY.encode(), COPERNICUS_NOTICE_ADDED_KEY.encode()}
    if set(new_meta) != set(old_meta) | added:
        raise ValueError("footer keys are not the old keys plus the two added")
    expected = copernicus_notice_footer(kind, years)[COPERNICUS_NOTICE_KEY].encode()
    if new_meta[COPERNICUS_NOTICE_KEY.encode()] != expected:
        raise ValueError(f"footer key {COPERNICUS_NOTICE_KEY} does not match")


def _backfill_parquet(
    store: OutputStore,
    path: str,
    data: bytes,
    *,
    kind: ParquetKind,
    context: _StoredContext,
    added: str,
    dry_run: bool,
) -> bool:
    metadata = pq.read_schema(BytesIO(data)).metadata or {}
    if COPERNICUS_NOTICE_KEY.encode() in metadata:
        return False
    years = _parquet_years(data, kind, context)
    if not years:
        return False
    table = pq.read_table(BytesIO(data))
    new_meta = {
        **(table.schema.metadata or {}),
        COPERNICUS_NOTICE_KEY.encode(): copernicus_notice_footer(kind, years)[
            COPERNICUS_NOTICE_KEY
        ].encode(),
        COPERNICUS_NOTICE_ADDED_KEY.encode(): added.encode(),
    }
    new = _with_metadata(table, new_meta)
    _verify_parquet(data, new, years, kind)
    if not dry_run:
        store.write_bytes(path, new, content_type=CONTENT_TYPES[".parquet"])
    return True


def _verify_json(doc: dict[str, Any], new: bytes, years: tuple[int, ...]) -> None:
    parsed = json.loads(new)
    if not isinstance(parsed, dict):
        raise ValueError("rewritten report is not a JSON object")
    if list(parsed)[: len(doc)] != list(doc):
        raise ValueError("report keys changed or were reordered")
    for key, value in doc.items():
        if parsed[key] != value:
            raise ValueError(f"report field {key} changed")
    extra = list(parsed)[len(doc) :]
    if extra != [COPERNICUS_NOTICE_KEY, COPERNICUS_NOTICE_ADDED_KEY]:
        raise ValueError("report keys are not the old keys plus the two added")
    expected = json.loads(json.dumps(copernicus_notice("verification", years)))
    if parsed[COPERNICUS_NOTICE_KEY] != expected:
        raise ValueError(f"report field {COPERNICUS_NOTICE_KEY} does not match")


def _backfill_json(
    store: OutputStore,
    path: str,
    data: bytes,
    *,
    context: _StoredContext,
    commit: str,
    on: datetime.date,
    dry_run: bool,
) -> bool:
    doc = json.loads(data)
    if not isinstance(doc, dict):
        raise ValueError("report is not a JSON object")
    if COPERNICUS_NOTICE_KEY in doc:
        return False
    run_id = path.rsplit("/", 1)[-1].removesuffix(".json")
    years = verification_years(context.ledger(), run_id)
    if not years:
        return False
    new_doc = {
        **doc,
        COPERNICUS_NOTICE_KEY: copernicus_notice("verification", years),
        COPERNICUS_NOTICE_ADDED_KEY: {"commit": commit, "date": on.isoformat()},
    }
    new = _dump_json(new_doc)
    _verify_json(doc, new, years)
    if not dry_run:
        store.write_bytes(path, new, content_type=CONTENT_TYPES[".json"])
    return True


def add_missing_notice(
    store: OutputStore,
    *,
    commit: str,
    on: datetime.date,
    dry_run: bool = False,
) -> NoticeBackfillResult:
    """Add the Copernicus notice to every observation, change, report and ledger
    file lacking it that has an acquisition year."""
    added = added_footer_value(commit, on)
    context = _StoredContext(store)
    targets: list[tuple[str, TargetKind]] = [
        *((path, "observation") for path in observation_paths(store)),
        *((path, "change") for path in _change_paths(store)),
        *((path, "verification") for path in _report_paths(store)),
        *(
            (path, "ledger")
            for path in store.list_files("ledger")
            if path.endswith(".parquet")
        ),
    ]
    rewritten: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []
    for path, kind in targets:
        try:
            data = store.read_bytes(path)
            if kind == "verification":
                changed = _backfill_json(
                    store,
                    path,
                    data,
                    context=context,
                    commit=commit,
                    on=on,
                    dry_run=dry_run,
                )
            else:
                changed = _backfill_parquet(
                    store,
                    path,
                    data,
                    kind=kind,
                    context=context,
                    added=added,
                    dry_run=dry_run,
                )
        except Exception as exc:
            failed.append((path, str(exc)))
            continue
        (rewritten if changed else skipped).append(path)
    return NoticeBackfillResult(
        scanned=len(targets),
        rewritten=tuple(rewritten),
        skipped=tuple(skipped),
        failed=tuple(failed),
        dry_run=dry_run,
    )
