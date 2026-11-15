"""Add the provenance footer to observation files written before it existed.

Observation files written before story st-2bfd lack the footer keys of
`outputs.provenance`. `add_missing_footers` rewrites each such file through the
store with the nine keys added, plus `footer_added_after_the_fact` naming the
commit and date of the backfill. A file that already carries all nine keys is
skipped, so a second run writes nothing.

Rows and the `geo` and `pandas` metadata are unchanged. Other footer keys, such
as `dea_attribution`, are kept unchanged; this backfill does not add them. Each
rewrite is checked against the original table and the kept keys before it is
written; a mismatch fails that file and leaves it as it was. One failing file
does not stop the others.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from io import BytesIO

import geopandas as gpd
import pyarrow.parquet as pq

from wetland_change.config import WaterConfig
from wetland_change.outputs.geoparquet import observation_paths, to_geoparquet_bytes
from wetland_change.outputs.provenance import FOOTER_KEYS, footer_metadata
from wetland_change.store import CONTENT_TYPES, OutputStore

ADDED_KEY = "footer_added_after_the_fact"


def added_footer_value(commit: str, on: datetime.date) -> str:
    """JSON naming the commit and date of a backfill."""
    return json.dumps({"commit": commit, "date": on.isoformat()}, sort_keys=True)


@dataclass(frozen=True)
class FooterBackfillResult:
    """Outcome of one backfill run; `rewritten` is the would-be list in a dry run."""

    scanned: int
    rewritten: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]
    dry_run: bool


def _has_all_keys(data: bytes) -> bool:
    metadata = pq.read_schema(BytesIO(data)).metadata or {}
    return all(key.encode() in metadata for key in FOOTER_KEYS)


_RESERVED_KEYS = frozenset(
    {b"geo", b"pandas", b"ARROW:schema", *(k.encode() for k in FOOTER_KEYS)}
    | {ADDED_KEY.encode()}
)


def _kept_metadata(data: bytes) -> dict[str, str]:
    """Footer entries of `data` other than the ones the rewrite sets itself."""
    metadata = pq.read_schema(BytesIO(data)).metadata or {}
    return {
        key.decode(): value.decode()
        for key, value in metadata.items()
        if key not in _RESERVED_KEYS
    }


def _verify(
    old: bytes, new: bytes, footer: dict[str, str], kept: dict[str, str]
) -> None:
    old_table = pq.read_table(BytesIO(old))
    new_table = pq.read_table(BytesIO(new))
    if not old_table.schema.equals(new_table.schema, check_metadata=False):
        raise ValueError("schema changed")
    if not old_table.equals(new_table):
        raise ValueError("table contents changed")
    old_meta = old_table.schema.metadata or {}
    new_meta = new_table.schema.metadata or {}
    for raw in (b"geo", b"pandas"):
        if old_meta.get(raw) != new_meta.get(raw):
            raise ValueError(f"{raw.decode()} metadata changed")
    for key in FOOTER_KEYS:
        if new_meta.get(key.encode()) != footer[key].encode():
            raise ValueError(f"footer key {key} does not match footer_metadata")
    for key, value in kept.items():
        if new_meta.get(key.encode()) != value.encode():
            raise ValueError(f"footer key {key} changed")


def _backfill_one(
    store: OutputStore,
    path: str,
    *,
    water: WaterConfig,
    operation_epsg: int,
    added: str,
    dry_run: bool,
) -> bool:
    """Rewrite one file; False when it already has every key."""
    data = store.read_bytes(path)
    if _has_all_keys(data):
        return False
    frame = gpd.read_parquet(BytesIO(data))
    footer = footer_metadata(
        frame, kind="observation", water=water, operation_epsg=operation_epsg
    )
    kept = _kept_metadata(data)
    new = to_geoparquet_bytes(frame, {**kept, **footer, ADDED_KEY: added})
    _verify(data, new, footer, kept)
    if not dry_run:
        store.write_bytes(path, new, content_type=CONTENT_TYPES[".parquet"])
    return True


def add_missing_footers(
    store: OutputStore,
    *,
    water: WaterConfig,
    operation_epsg: int,
    commit: str,
    on: datetime.date,
    dry_run: bool = False,
) -> FooterBackfillResult:
    """Add the footer keys to every observation file missing any of them."""
    added = added_footer_value(commit, on)
    rewritten: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []
    paths = observation_paths(store)
    for path in paths:
        try:
            changed = _backfill_one(
                store,
                path,
                water=water,
                operation_epsg=operation_epsg,
                added=added,
                dry_run=dry_run,
            )
        except Exception as exc:
            failed.append((path, str(exc)))
            continue
        (rewritten if changed else skipped).append(path)
    return FooterBackfillResult(
        scanned=len(paths),
        rewritten=tuple(rewritten),
        skipped=tuple(skipped),
        failed=tuple(failed),
        dry_run=dry_run,
    )
