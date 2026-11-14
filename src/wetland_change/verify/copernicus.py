"""Discovery completeness against the Copernicus Data Space STAC.

For each MGRS tile and month, the Sentinel-2 L2A scenes listed by Earth Search
Collection 1 are compared with those listed by the Copernicus Data Space
Ecosystem (CDSE) STAC. Only listings are read; no asset is accessed.

Scenes are matched on the datatake key. Collection 1 and CDSE products of one
datatake differ in processing baseline and generation time, so the key is the
product name without the `N0xxx` baseline token and the final generation-time
token. A CDSE listing may also hold the same datatake more than once; each
side is deduplicated on the key.

AOI membership is decided once per datatake. A datatake that both catalogues
list under the cloud limit in the window, and whose footprint intersects the AOI
in only one of them, is a footprint-edge case: it is reported under
`footprint_edge` in the check detail (CDSE product names) and is not counted as
a mismatch. A datatake listed by one catalogue only is kept only if its own
footprint intersects the AOI, and remains a mismatch if it is old enough.

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


def rfc3339(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Scene:
    name: str
    key: str
    tile: str
    month: str
    sensed: datetime
    in_aoi: bool = True


@dataclass(frozen=True)
class Reconciled:
    """Scenes per catalogue after AOI membership is decided once per datatake.

    `footprint_edge` maps the datatake key to the CDSE scene for datatakes both
    catalogues list whose footprint intersects the AOI in only one of them.
    """

    es: dict[str, Scene]
    cdse: dict[str, Scene]
    footprint_edge: dict[str, Scene]


def _tile(props: dict[str, Any], name: str) -> str:
    grid = props.get("grid:code")
    if grid:
        return str(grid)[-5:]
    match = _TILE_IN_NAME.search(name)
    if match is None:
        raise ValueError(f"no MGRS tile for {name!r}")
    return match.group(1)


def normalise_scenes(
    items: Sequence[dict[str, Any]],
    *,
    cloud_max: float,
    polygons: list[BaseGeometry],
    es_names: bool,
) -> dict[str, Scene]:
    """Cloud-filtered scenes keyed by datatake, one per datatake.

    Items without a usable cloud cover or that fail to parse are skipped. An
    item whose footprint misses every polygon is kept with `in_aoi` False, so
    the caller can decide AOI membership per datatake. Among duplicates of one
    datatake, a scene that intersects wins, then the lowest product name.
    """
    scenes: list[Scene] = []
    for item in items:
        try:
            props: dict[str, Any] = item["properties"]
            cloud = props.get("eo:cloud_cover")
            if cloud is None or float(cloud) >= cloud_max:
                continue
            footprint = shape(item["geometry"])
            in_aoi = any(footprint.intersects(poly) for poly in polygons)
            raw = str(props["s2:product_uri"] if es_names else item["id"])
            name = raw.removesuffix(".SAFE") if es_names else raw
            sensed = parse_timestamp(str(props["datetime"])).astimezone(UTC)
            scenes.append(
                Scene(
                    name=name,
                    key=datatake_key(name),
                    tile=_tile(props, name),
                    month=sensed.strftime("%Y-%m"),
                    sensed=sensed,
                    in_aoi=in_aoi,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "skipping %s in Copernicus comparison: %s", item.get("id"), exc
            )
    unique: dict[str, Scene] = {}
    for scene in sorted(scenes, key=lambda s: (not s.in_aoi, s.name)):
        unique.setdefault(scene.key, scene)
    return unique


def in_aoi_only(scenes: dict[str, Scene]) -> dict[str, Scene]:
    """The scenes whose own footprint intersects the AOI."""
    return {k: s for k, s in scenes.items() if s.in_aoi}


def reconcile_footprints(
    es_all: dict[str, Scene], cdse_all: dict[str, Scene]
) -> Reconciled:
    """Decide AOI membership once per datatake across both catalogues."""
    es: dict[str, Scene] = {}
    cdse: dict[str, Scene] = {}
    edge: dict[str, Scene] = {}
    for key in sorted(es_all.keys() | cdse_all.keys()):
        es_scene = es_all.get(key)
        cdse_scene = cdse_all.get(key)
        if es_scene is not None and cdse_scene is not None:
            if es_scene.in_aoi and cdse_scene.in_aoi:
                es[key] = es_scene
                cdse[key] = cdse_scene
            elif es_scene.in_aoi != cdse_scene.in_aoi:
                edge[key] = cdse_scene
        elif es_scene is not None and es_scene.in_aoi:
            es[key] = es_scene
        elif cdse_scene is not None and cdse_scene.in_aoi:
            cdse[key] = cdse_scene
    return Reconciled(es=es, cdse=cdse, footprint_edge=edge)


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
    window = f"{rfc3339(start)}/{rfc3339(end)}"
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
    es_all = normalise_scenes(
        es_items, cloud_max=cfg.cloud_cover_max, polygons=polygons_4326, es_names=True
    )
    cdse_all = normalise_scenes(
        cdse_items,
        cloud_max=cfg.cloud_cover_max,
        polygons=polygons_4326,
        es_names=False,
    )
    rec = reconcile_footprints(es_all, cdse_all)
    es, cdse, edge = rec.es, rec.cdse, rec.footprint_edge
    reference = f"{CDSE_STAC} {CDSE_COLLECTION}"
    if not es and not cdse and not edge:
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
    tiles = sorted(
        {s.tile for s in es.values()}
        | {s.tile for s in cdse.values()}
        | {s.tile for s in edge.values()}
    )
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
                    "footprint_edge": sorted(
                        s.name for s in edge.values() if s.tile == tile
                    ),
                },
            )
        )
    return checks
