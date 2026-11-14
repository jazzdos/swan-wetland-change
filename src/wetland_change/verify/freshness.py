"""Scheduled job alive check: the ledger against the catalogues.

Two kinds of check run over the last `WINDOW` (30 days).

`freshness_newest_item` fails when the newest processed item was acquired
`MAX_AGE` (7 days) or more before the check time, which means the scheduled
job has stopped or the catalogue has stopped publishing.

`freshness_count_vs_earth_search` and `freshness_count_vs_copernicus` compare,
per MGRS tile, the items the ledger holds as succeeded with the items each
catalogue lists for the same window. Earth Search is matched on the product
name (the ledger `product_uri` without `.SAFE`). Copernicus is matched on the
datatake key, because its products differ in processing baseline and
generation time. A scene listed on only one side is not a mismatch while it
was sensed less than `LATENCY` (24 h) before the check time; it is reported
as `pending_latency`.

Copernicus scope is decided once per datatake together with Earth Search (see
`copernicus.reconcile_footprints`). A datatake both catalogues list whose
footprint intersects the AOI in only one of them is reported as
`footprint_edge` in `freshness_count_vs_copernicus` and not counted.
`freshness_count_vs_earth_search` keeps Earth Search's own footprint filter.

`freshness_exhausted_items` fails when any ledger item failed `MAX_ATTEMPTS`
times and has no later succeeded row. Such an item is no longer retried or
re-discovered, so nothing else reports it. It is not windowed: it fails until
the item succeeds or is requeued.

All `SWAN_TILES` are always checked, plus any other tile seen on either side.
A catalogue search that raises gives skipped checks for that source only.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pyarrow as pa
from shapely.geometry.base import BaseGeometry

from wetland_change.catalogue.search import StacClient
from wetland_change.config import StacConfig
from wetland_change.ledger import MAX_ATTEMPTS, exhausted_ids, latest_entries
from wetland_change.verify.checks import Check
from wetland_change.verify.copernicus import (
    CDSE_COLLECTION,
    CDSE_STAC,
    LATENCY,
    Scene,
    datatake_key,
    in_aoi_only,
    normalise_scenes,
    reconcile_footprints,
    rfc3339,
)

CHECK_NEWEST = "freshness_newest_item"
CHECK_EXHAUSTED = "freshness_exhausted_items"
CHECK_ES = "freshness_count_vs_earth_search"
CHECK_CDSE = "freshness_count_vs_copernicus"
WINDOW = timedelta(days=30)
MAX_AGE = timedelta(days=7)
SWAN_TILES = ("50HLJ", "50HLK", "50HMJ", "50HMK", "50JLL", "50JML")

# One side of a comparison: match key -> (display name, sensed time).
_Side = dict[str, tuple[str, datetime]]


def _succeeded(ledger: pa.Table) -> pd.DataFrame:
    latest = latest_entries(ledger)
    if latest.empty:
        return latest
    return latest[latest["status"] == "succeeded"]


def newest_item_check(ledger: pa.Table, now: datetime) -> Check:
    """Fail when the newest processed item is `MAX_AGE` or older."""
    reference = "ledger newest processed item"
    ok = _succeeded(ledger)
    acquired = ok["datetime"].dropna() if not ok.empty else ok
    if acquired.empty:
        return Check(
            name=CHECK_NEWEST,
            passed=False,
            measured=None,
            threshold=MAX_AGE.total_seconds() / 86400,
            reference=reference,
            detail={"reason": "the ledger holds no succeeded item"},
        )
    newest = acquired.max().to_pydatetime()
    age = now - newest
    return Check(
        name=CHECK_NEWEST,
        passed=age < MAX_AGE,
        measured=age.total_seconds() / 86400,
        threshold=MAX_AGE.total_seconds() / 86400,
        reference=reference,
        detail={"newest_item_datetime": newest.isoformat(), "now": now.isoformat()},
    )


def exhausted_items_check(ledger: pa.Table) -> Check:
    """Fail when any item failed `MAX_ATTEMPTS` times and has not succeeded since."""
    item_ids = exhausted_ids(ledger)
    return Check(
        name=CHECK_EXHAUSTED,
        passed=not item_ids,
        measured=float(len(item_ids)),
        threshold=0.0,
        reference="ledger items failed MAX_ATTEMPTS times and not yet succeeded "
        "or requeued",
        detail={"item_ids": item_ids, "max_attempts": MAX_ATTEMPTS},
    )


def _scenes(
    client: StacClient,
    cfg: StacConfig,
    *,
    bbox: tuple[float, float, float, float],
    polygons_4326: list[BaseGeometry],
    start: datetime,
    end: datetime,
    cdse: bool,
) -> dict[str, Scene]:
    """Scenes of one catalogue sensed within [start, end], with `in_aoi` set.

    Scenes whose own footprint misses the AOI are kept so the caller decides
    AOI membership.
    """
    window = f"{rfc3339(start)}/{rfc3339(end)}"
    if cdse:
        search = client.search(
            collections=[CDSE_COLLECTION], bbox=list(bbox), datetime=window
        )
    else:
        search = client.search(
            collections=[cfg.collection],
            bbox=list(bbox),
            datetime=window,
            query={"eo:cloud_cover": {"lt": cfg.cloud_cover_max}},
        )
    scenes = normalise_scenes(
        list(search.items_as_dicts()),
        cloud_max=cfg.cloud_cover_max,
        polygons=polygons_4326,
        es_names=not cdse,
    )
    return {k: s for k, s in scenes.items() if start <= s.sensed <= end}


def list_tile_counts(
    client: StacClient,
    cfg: StacConfig,
    *,
    bbox: tuple[float, float, float, float],
    polygons_4326: list[BaseGeometry],
    start: datetime,
    end: datetime,
    cdse: bool,
) -> dict[str, int]:
    """Deduplicated scene count per MGRS tile listed by one catalogue."""
    scenes = _scenes(
        client,
        cfg,
        bbox=bbox,
        polygons_4326=polygons_4326,
        start=start,
        end=end,
        cdse=cdse,
    )
    counts: dict[str, int] = {}
    for scene in in_aoi_only(scenes).values():
        counts[scene.tile] = counts.get(scene.tile, 0) + 1
    return counts


def _ledger_sides(
    ledger: pa.Table, start: datetime, end: datetime
) -> dict[str, tuple[_Side, _Side]]:
    """Per tile, the ledger's succeeded items keyed for Earth Search and CDSE."""
    sides: dict[str, tuple[_Side, _Side]] = {}
    ok = _succeeded(ledger)
    if ok.empty:
        return sides
    for row in ok.itertuples(index=False):
        if pd.isna(row.tile) or pd.isna(row.datetime):
            continue
        sensed = row.datetime.to_pydatetime().astimezone(UTC)
        if not start <= sensed <= end:
            continue
        item_id = str(row.item_id)
        uri = None if pd.isna(row.product_uri) else str(row.product_uri)
        product = uri.removesuffix(".SAFE") if uri else item_id
        try:
            cdse_key, cdse_name = datatake_key(product), product
        except ValueError:
            cdse_key, cdse_name = item_id, item_id
        es_side, cdse_side = sides.setdefault(str(row.tile), ({}, {}))
        es_side[product] = (product, sensed)
        cdse_side[cdse_key] = (cdse_name, sensed)
    return sides


def _compare(
    check_name: str,
    reference: str,
    tile: str,
    ledger_side: _Side,
    reference_side: _Side,
    *,
    start: datetime,
    end: datetime,
    now: datetime,
    footprint_edge: dict[str, Scene] | None = None,
) -> Check:
    edge_names: list[str] | None = None
    if footprint_edge is not None:
        # A footprint-edge datatake is out of scope on both sides.
        edge = {k: sc for k, sc in footprint_edge.items() if sc.tile == tile}
        ledger_side = {k: v for k, v in ledger_side.items() if k not in edge}
        reference_side = {k: v for k, v in reference_side.items() if k not in edge}
        edge_names = sorted(sc.name for sc in edge.values())
    cutoff = now - LATENCY
    only_ledger = [v for k, v in ledger_side.items() if k not in reference_side]
    only_reference = [v for k, v in reference_side.items() if k not in ledger_side]
    pending = [v for v in only_ledger + only_reference if v[1] > cutoff]
    missing_reference = sorted(n for n, s in only_ledger if s <= cutoff)
    missing_ledger = sorted(n for n, s in only_reference if s <= cutoff)
    mismatched = len(missing_reference) + len(missing_ledger)
    detail: dict[str, Any] = {
        "tile": tile,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "latency_hours": int(LATENCY.total_seconds() // 3600),
        "ledger_count": len(ledger_side),
        "reference_count": len(reference_side),
        "missing_from_ledger": missing_ledger,
        "missing_from_reference": missing_reference,
        "pending_latency": sorted(n for n, _ in pending),
    }
    if edge_names is not None:
        detail["footprint_edge"] = edge_names
    return Check(
        name=check_name,
        passed=mismatched == 0,
        measured=float(mismatched),
        threshold=0.0,
        reference=reference,
        detail=detail,
    )


def _skipped(check_name: str, tile: str, exc: Exception) -> Check:
    return Check(
        name=check_name,
        passed=None,
        measured=None,
        threshold=None,
        reference="check did not run",
        detail={"tile": tile, "error": f"{type(exc).__name__}: {exc}"},
    )


def _as_side(scenes: Sequence[Scene], *, by_key: bool) -> _Side:
    return {(s.key if by_key else s.name): (s.name, s.sensed) for s in scenes}


def count_checks(
    ledger: pa.Table,
    es_client: StacClient,
    cdse_client: StacClient,
    cfg: StacConfig,
    *,
    bbox: tuple[float, float, float, float],
    polygons_4326: list[BaseGeometry],
    now: datetime,
) -> list[Check]:
    """Per tile, ledger-vs-Earth Search then ledger-vs-CDSE count checks."""
    start, end = now - WINDOW, now
    ledger_sides = _ledger_sides(ledger, start, end)
    raw: dict[str, dict[str, Scene] | Exception] = {}
    for source, client, is_cdse in (
        (CHECK_ES, es_client, False),
        (CHECK_CDSE, cdse_client, True),
    ):
        try:
            raw[source] = _scenes(
                client,
                cfg,
                bbox=bbox,
                polygons_4326=polygons_4326,
                start=start,
                end=end,
                cdse=is_cdse,
            )
        except Exception as exc:  # a dead catalogue must not hide the other checks
            raw[source] = exc

    es_all, cdse_all = raw[CHECK_ES], raw[CHECK_CDSE]
    listings: dict[str, dict[str, Scene] | Exception] = {}
    edge: dict[str, Scene] = {}
    # Earth Search keeps its own footprint filter: the pipeline discovers from it.
    listings[CHECK_ES] = (
        es_all if isinstance(es_all, Exception) else in_aoi_only(es_all)
    )
    if isinstance(cdse_all, Exception):
        listings[CHECK_CDSE] = cdse_all
    elif isinstance(es_all, Exception):
        # No Earth Search listing to reconcile against: own footprint only.
        listings[CHECK_CDSE] = in_aoi_only(cdse_all)
    else:
        rec = reconcile_footprints(es_all, cdse_all)
        listings[CHECK_CDSE] = rec.cdse
        edge = rec.footprint_edge

    tiles = set(SWAN_TILES) | set(ledger_sides)
    for found in listings.values():
        if not isinstance(found, Exception):
            tiles |= {s.tile for s in found.values()}
    tiles |= {s.tile for s in edge.values()}

    references = {
        CHECK_ES: f"{cfg.endpoint} {cfg.collection}",
        CHECK_CDSE: f"{CDSE_STAC} {CDSE_COLLECTION}",
    }
    checks: list[Check] = []
    for source in (CHECK_ES, CHECK_CDSE):
        found = listings[source]
        for tile in sorted(tiles):
            if isinstance(found, Exception):
                checks.append(_skipped(source, tile, found))
                continue
            ledger_es, ledger_cdse = ledger_sides.get(tile, ({}, {}))
            tile_scenes = [s for s in found.values() if s.tile == tile]
            is_es = source == CHECK_ES
            checks.append(
                _compare(
                    source,
                    references[source],
                    tile,
                    ledger_es if is_es else ledger_cdse,
                    _as_side(tile_scenes, by_key=not is_es),
                    start=start,
                    end=end,
                    now=now,
                    footprint_edge=None if is_es else edge,
                )
            )
    return checks


def freshness_checks(
    ledger: pa.Table,
    es_client: StacClient,
    cdse_client: StacClient,
    cfg: StacConfig,
    *,
    bbox: tuple[float, float, float, float],
    polygons_4326: list[BaseGeometry],
    now: datetime,
) -> list[Check]:
    """Newest-item, exhausted-items, then Earth Search and CDSE count checks."""
    return [
        newest_item_check(ledger, now),
        exhausted_items_check(ledger),
        *count_checks(
            ledger,
            es_client,
            cdse_client,
            cfg,
            bbox=bbox,
            polygons_4326=polygons_4326,
            now=now,
        ),
    ]
