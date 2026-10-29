"""Discovery completeness against the Copernicus Data Space STAC.

For each MGRS tile and month, the Sentinel-2 L2A scenes listed by Earth Search
Collection 1 are compared with those listed by the Copernicus Data Space
Ecosystem (CDSE) STAC. Only listings are read; no asset is accessed.

Scenes are matched on the datatake key. Collection 1 and CDSE products of one
datatake differ in processing baseline and generation time, so the key is the
product name without the `N0xxx` baseline token and the final generation-time
token. A CDSE listing may also hold the same datatake more than once; each
side is deduplicated on the key.

A scene listed by only one catalogue is not a mismatch while it was sensed
less than `LATENCY` (24 h) before the check time, because the two archives
ingest at different speeds. Such scenes are reported as `pending_latency`.

The compared window is the verified run's own window, not the full history:
CDSE holds 2022 items that Collection 1 lacks, so an unbounded comparison
would always fail.

Known limit: both listings are filtered on `eo:cloud_cover` below the
configured maximum, and the value can differ between processing baselines, so
a scene whose cloud cover straddles the threshold can appear one-sided.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from wetland_change.catalogue.item import parse_timestamp
from wetland_change.catalogue.search import StacClient
from wetland_change.config import StacConfig
from wetland_change.verify.checks import Check

logger = logging.getLogger(__name__)

CDSE_STAC = "https://stac.dataspace.copernicus.eu/v1"
CDSE_COLLECTION = "sentinel-2-l2a"
CHECK_NAME = "discovery_vs_copernicus"
LATENCY = timedelta(hours=24)

_NAME_TOKENS = 7
_TILE_IN_NAME = re.compile(r"_T(\d{2}[A-Z]{3})_")


def datatake_key(product_name: str) -> str:
    """Product name without the processing baseline and generation time."""
    stem = product_name.removesuffix(".SAFE")
    tokens = stem.split("_")
    baselines = [t for t in tokens if t.startswith("N0")]
    if len(tokens) != _NAME_TOKENS or len(baselines) != 1:
        raise ValueError(f"not a Sentinel-2 L2A product name: {product_name!r}")
    return "_".join(t for t in tokens[:-1] if t != baselines[0])


def run_window(
    scene_datetimes: Sequence[datetime], started_at: datetime
) -> tuple[datetime, datetime]:
    """From the start of the earliest scene's UTC day to the run start."""
    earliest = min(scene_datetimes).astimezone(UTC)
    start = earliest.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, started_at


def _rfc3339(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class _Scene:
    name: str
    key: str
    tile: str
    month: str
    sensed: datetime


def _tile(props: dict[str, Any], name: str) -> str:
    grid = props.get("grid:code")
    if grid:
        return str(grid)[-5:]
    match = _TILE_IN_NAME.search(name)
    if match is None:
        raise ValueError(f"no MGRS tile for {name!r}")
    return match.group(1)


def _normalise(
    items: Sequence[dict[str, Any]],
    *,
    cloud_max: float,
    polygons: list[BaseGeometry],
    es_names: bool,
) -> dict[str, _Scene]:
    """Locally filtered scenes keyed by datatake, one per datatake."""
    scenes: list[_Scene] = []
    for item in items:
        try:
            props: dict[str, Any] = item["properties"]
            cloud = props.get("eo:cloud_cover")
            if cloud is None or float(cloud) >= cloud_max:
                continue
            footprint = shape(item["geometry"])
            if not any(footprint.intersects(poly) for poly in polygons):
                continue
            raw = str(props["s2:product_uri"] if es_names else item["id"])
            name = raw.removesuffix(".SAFE") if es_names else raw
            sensed = parse_timestamp(str(props["datetime"])).astimezone(UTC)
            scenes.append(
                _Scene(
                    name=name,
                    key=datatake_key(name),
                    tile=_tile(props, name),
                    month=sensed.strftime("%Y-%m"),
                    sensed=sensed,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "skipping %s in Copernicus comparison: %s", item.get("id"), exc
            )
    unique: dict[str, _Scene] = {}
    for scene in sorted(scenes, key=lambda s: s.name):
        unique.setdefault(scene.key, scene)
    return unique


def discovery_checks(
    es_client: StacClient,
    cdse_client: StacClient,
    cfg: StacConfig,
    *,
    bbox: tuple[float, float, float, float],
    polygons_4326: list[BaseGeometry],
    start: datetime,
    end: datetime,
    now: datetime,
) -> list[Check]:
    """One check per tile comparing Earth Search with CDSE over the window."""
    window = f"{_rfc3339(start)}/{_rfc3339(end)}"
    es_items = list(
        es_client.search(
            collections=[cfg.collection],
            bbox=list(bbox),
            datetime=window,
            query={"eo:cloud_cover": {"lt": cfg.cloud_cover_max}},
        ).items_as_dicts()
    )
    cdse_items = list(
        cdse_client.search(
            collections=[CDSE_COLLECTION], bbox=list(bbox), datetime=window
        ).items_as_dicts()
    )
    es = _normalise(
        es_items, cloud_max=cfg.cloud_cover_max, polygons=polygons_4326, es_names=True
    )
    cdse = _normalise(
        cdse_items,
        cloud_max=cfg.cloud_cover_max,
        polygons=polygons_4326,
        es_names=False,
    )
    reference = f"{CDSE_STAC} {CDSE_COLLECTION}"
    if not es and not cdse:
        return [
            Check(
                name=CHECK_NAME,
                passed=None,
                measured=None,
                threshold=None,
                reference=reference,
                detail={
                    "reason": "no items listed by either catalogue in the run window"
                },
            )
        ]

    cutoff = now - LATENCY
    checks: list[Check] = []
    tiles = sorted({s.tile for s in es.values()} | {s.tile for s in cdse.values()})
    for tile in tiles:
        es_t = {k: s for k, s in es.items() if s.tile == tile}
        cdse_t = {k: s for k, s in cdse.items() if s.tile == tile}
        months: dict[str, dict[str, int]] = {}
        for side, scenes in (("earth_search", es_t), ("cdse", cdse_t)):
            for scene in scenes.values():
                counts = months.setdefault(scene.month, {"earth_search": 0, "cdse": 0})
                counts[side] += 1
        one_sided_cdse = [s for k, s in cdse_t.items() if k not in es_t]
        one_sided_es = [s for k, s in es_t.items() if k not in cdse_t]
        pending = [s for s in one_sided_cdse + one_sided_es if s.sensed > cutoff]
        missing_es = sorted(s.name for s in one_sided_cdse if s.sensed <= cutoff)
        missing_cdse = sorted(s.name for s in one_sided_es if s.sensed <= cutoff)
        mismatched = len(missing_es) + len(missing_cdse)
        checks.append(
            Check(
                name=CHECK_NAME,
                passed=mismatched == 0,
                measured=float(mismatched),
                threshold=0.0,
                reference=reference,
                detail={
                    "tile": tile,
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "latency_hours": int(LATENCY.total_seconds() // 3600),
                    "months": dict(sorted(months.items())),
                    "missing_from_earth_search": missing_es,
                    "missing_from_cdse": missing_cdse,
                    "pending_latency": sorted(s.name for s in pending),
                },
            )
        )
    return checks
