"""Download the AOI layers into data/external and print SOURCES.md rows.

Ramsar sites: DBCA-010 via the open SLIP ArcGIS REST service, layer 9.
DEA Waterbodies v3: WFS bbox query over the Swan Coastal Plain.
Both fetch without a login. Re-running overwrites the files.

The Ramsar checksum is the sha256 of the raw response bytes. The Waterbodies
checksum is the sha256 of canonical JSON with the top-level WFS timeStamp
removed, because that field changes on every request. The file is written only
after the checksum succeeds, so an error body never replaces a good download.

A second Waterbodies checksum, ``geometry_checksum``, covers only the uid and
geometry of every feature, sorted by uid. A DEA refresh of ``dt_wetobs``,
``dt_satpass``, ``dt_updated`` or ``wet_sa_m2`` changes the first checksum but
not this one, so it confirms the same polygons across fetches.

Validation. Both responses must be non-empty GeoJSON FeatureCollections, so an
HTTP 200 error body (ArcGIS ``{"error": ...}`` or HTML) fails the run. Polygon
ids come from live data (``ramsar-<objectid>``, ``dea-<uid>``), so every id
used by ``[water.overrides.*]`` in config/pipeline.toml must exist in the
fetched layers. Each Ramsar override must also still match the site name and
bounding box pinned in ``OVERRIDE_POLYGONS``, because a renumbering would
usually leave the id present on a different polygon of the same site. On any
failure the script exits 1 and writes neither file.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import requests
from shapely.geometry import shape

from wetland_change.config import load_config

OUT = Path("data/external")
CONFIG = Path("config/pipeline.toml")
RAMSAR_URL = (
    "https://public-services.slip.wa.gov.au/public/rest/services/"
    "SLIP_Public_Services/Environment/MapServer/9/query"
)
RAMSAR_LICENCE = (
    "CC BY-NC 4.0, non-commercial use only (the custodian's catalogue entry, "
    "catalogue.data.wa.gov.au; adopted 2026-11-15, not confirmed in writing by "
    "DBCA; the SLIP service terms differ, see "
    "docs/research/2026-11-14-public-release-licences.md)"
)
RAMSAR_PARAMS = {
    "where": "1=1",
    "outFields": "*",
    "returnGeometry": "true",
    "outSR": "4326",
    "f": "geojson",
}
WATERBODIES_URL = "https://geoserver.dea.ga.gov.au/geoserver/wfs"
WATERBODIES_PARAMS = {
    "service": "WFS",
    "version": "1.0.0",
    "request": "GetFeature",
    "typeName": "dea:DigitalEarthAustraliaWaterbodies_v3",
    "outputFormat": "application/json",
    "srsName": "EPSG:4326",
    "bbox": "115.4,-33.2,116.2,-31.5,EPSG:4326",
}


class PolygonIdentity(NamedTuple):
    """Site name and EPSG:4326 bounding box (min lon, min lat, max lon, max lat)."""

    site_name: str
    bbox: tuple[float, float, float, float]


# Ramsar ids come from live SLIP objectids. If SLIP renumbers them, an override in
# config/pipeline.toml would silently attach to another polygon, and the
# Peel-Yalgorup System alone holds 16 polygons, so the id would still exist with
# the same site name. Pinning the bounding box catches that. A new
# `[water.overrides.ramsar-N]` entry must add a row here (values from the DBCA-010
# polygon). DEA uids are geohashes of the polygon, so they need no row.
OVERRIDE_POLYGONS: dict[str, PolygonIdentity] = {
    "ramsar-15": PolygonIdentity(
        "Peel-Yalgorup System", (115.7098, -32.688, 115.7165, -32.6734)
    ),
    "ramsar-28": PolygonIdentity(
        "Peel-Yalgorup System", (115.6838, -32.5718, 115.7086, -32.5599)
    ),
    "ramsar-56": PolygonIdentity(
        "Forrestdale & Thomsons Lakes", (115.9283, -32.1677, 115.9459, -32.1499)
    ),
}
BBOX_TOLERANCE_DEG = 0.001


def raw_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def stable_geojson_checksum(content: bytes) -> str:
    """Return the sha256 of the GeoJSON payload without its top-level timeStamp.

    The DEA Waterbodies WFS adds a top-level ``timeStamp`` that changes on every
    request, so a raw-bytes checksum differs between fetches of identical
    features. The payload is parsed, ``timeStamp`` is dropped, and the rest is
    serialised with sorted keys and compact separators before hashing. Every
    feature and every other top-level field stays covered.

    Raises:
        ValueError: If the bytes are not valid JSON or not a JSON object.
    """
    try:
        payload = json.loads(content)
    except ValueError as err:
        raise ValueError("payload is not valid JSON") from err
    if not isinstance(payload, dict):
        raise ValueError("payload is not a JSON object")
    payload.pop("timeStamp", None)
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def geometry_checksum(content: bytes) -> str:
    """Return the sha256 over the uid and geometry of every feature.

    Only ``properties.uid`` and ``geometry`` are hashed, so a DEA refresh of
    ``dt_wetobs``, ``dt_satpass``, ``dt_updated`` or ``wet_sa_m2`` leaves the
    result unchanged. Features are sorted by uid then canonical geometry, so
    feature order and JSON formatting do not matter. Coordinates are hashed as
    delivered, with no rounding.

    Raises:
        ValueError: If the bytes are not valid JSON or not a JSON object, if
            ``features`` is not a list, or if a feature lacks a uid or a
            geometry.
    """
    try:
        payload = json.loads(content)
    except ValueError as err:
        raise ValueError("payload is not valid JSON") from err
    if not isinstance(payload, dict):
        raise ValueError("payload is not a JSON object")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("payload features is not a list")
    records: list[tuple[str, str, Any]] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise ValueError(f"feature {index} is not a JSON object")
        properties = feature.get("properties")
        if not isinstance(properties, dict) or properties.get("uid") is None:
            raise ValueError(f"feature {index} has no properties.uid")
        geometry = feature.get("geometry")
        if geometry is None:
            raise ValueError(f"feature {index} has no geometry")
        uid = str(properties["uid"])
        key = json.dumps(
            geometry, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        records.append((uid, key, geometry))
    records.sort(key=lambda record: (record[0], record[1]))
    canonical = json.dumps(
        [[uid, geometry] for uid, _key, geometry in records],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def require_feature_collection(content: bytes) -> dict[str, Any]:
    """Parse a response body and require a non-empty GeoJSON FeatureCollection.

    Raises:
        ValueError: If the body is not JSON, not an object, not a
            FeatureCollection, or has no features. A service ``error`` entry is
            quoted in the message.
    """
    try:
        payload = json.loads(content)
    except ValueError as err:
        raise ValueError("payload is not valid JSON") from err
    if not isinstance(payload, dict):
        raise ValueError("payload is not a JSON object")
    problem = None
    features = payload.get("features")
    if payload.get("type") != "FeatureCollection":
        problem = f"payload type is {payload.get('type')!r}, not 'FeatureCollection'"
    elif not isinstance(features, list) or not features:
        problem = "payload 'features' is missing or not a non-empty list"
    elif not all(isinstance(f, dict) for f in features):
        problem = "payload 'features' holds an entry that is not an object"
    if problem is not None:
        if "error" in payload:
            problem += f"; service error: {json.dumps(payload['error'])}"
        raise ValueError(problem)
    return payload


def _expected_ids(
    ramsar: dict[str, Any],
    waterbodies: dict[str, Any],
    site_prefixes: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Map each id the loaders would build to its feature."""
    found: dict[str, dict[str, Any]] = {}
    for feature in ramsar.get("features", []):
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict):
            continue
        name, objectid = props.get("ram_ramsarname"), props.get("objectid")
        if objectid is None or not isinstance(name, str):
            continue
        if name.startswith(tuple(site_prefixes)):
            found[f"ramsar-{objectid}"] = feature
    for feature in waterbodies.get("features", []):
        props = feature.get("properties") if isinstance(feature, dict) else None
        if isinstance(props, dict) and props.get("uid") is not None:
            found[f"dea-{props['uid']}"] = feature
    return found


def _bounds(feature: dict[str, Any]) -> tuple[float, float, float, float] | None:
    try:
        minx, miny, maxx, maxy = shape(feature["geometry"]).bounds
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not all(map(_finite, (minx, miny, maxx, maxy))):
        return None
    return (minx, miny, maxx, maxy)


def _finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def check_override_ids(
    ramsar: dict[str, Any],
    waterbodies: dict[str, Any],
    overrides: Collection[str],
    site_prefixes: Sequence[str],
    identities: Mapping[str, PolygonIdentity],
) -> None:
    """Require every override id to exist and, for Ramsar, to be the same polygon.

    Raises:
        ValueError: One message listing every problem found.
    """
    expected = _expected_ids(ramsar, waterbodies, site_prefixes)
    problems: list[str] = []
    for key in sorted(overrides):
        feature = expected.get(key)
        if feature is None:
            problems.append(
                f"{key}: override id is not in the fetched layers "
                "(Ramsar ids are limited to the configured site prefixes)"
            )
            continue
        if not key.startswith("ramsar-"):
            continue
        identity = identities.get(key)
        if identity is None:
            problems.append(f"{key}: no pinned identity row in OVERRIDE_POLYGONS")
            continue
        found_name = feature["properties"]["ram_ramsarname"]
        if found_name != identity.site_name:
            problems.append(
                f"{key}: site name expected {identity.site_name!r}, "
                f"found {found_name!r}"
            )
        bounds = _bounds(feature)
        if bounds is None:
            problems.append(
                f"{key}: feature has no usable geometry for its bounding box"
            )
        elif any(
            abs(a - b) > BBOX_TOLERANCE_DEG
            for a, b in zip(bounds, identity.bbox, strict=True)
        ):
            problems.append(
                f"{key}: bounding box expected {identity.bbox}, found "
                f"{tuple(round(v, 4) for v in bounds)} "
                f"(tolerance {BBOX_TOLERANCE_DEG} deg)"
            )
    if problems:
        raise ValueError(
            "water override ids do not match the fetched layers; the source ids "
            "may have changed. Review [water.overrides.*] in config/pipeline.toml "
            "and OVERRIDE_POLYGONS in scripts/fetch_aoi.py:\n  " + "\n  ".join(problems)
        )


def fetch_bytes(url: str, params: dict[str, str]) -> bytes:
    """GET a layer and return its body after requiring a FeatureCollection."""
    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()
    content = response.content
    require_feature_collection(content)
    return content


def main() -> int:
    today = datetime.now(UTC).date().isoformat()
    ramsar = OUT / "dbca_010_ramsar_sites.geojson"
    waterbodies = OUT / "dea_waterbodies_v3_swan.geojson"
    try:
        cfg = load_config(CONFIG)
        ramsar_bytes = fetch_bytes(RAMSAR_URL, RAMSAR_PARAMS)
        wb_bytes = fetch_bytes(WATERBODIES_URL, WATERBODIES_PARAMS)
        check_override_ids(
            require_feature_collection(ramsar_bytes),
            require_feature_collection(wb_bytes),
            cfg.water.overrides.keys(),
            cfg.aoi.site_prefixes,
            OVERRIDE_POLYGONS,
        )
        ramsar_sha = raw_sha256(ramsar_bytes)
        wb_sha = stable_geojson_checksum(wb_bytes)
        geo_sha = geometry_checksum(wb_bytes)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    ramsar.write_bytes(ramsar_bytes)
    waterbodies.write_bytes(wb_bytes)
    print("Add or update these rows in data/SOURCES.md:")
    print(
        f"| DBCA-010 Ramsar Sites | {RAMSAR_URL} | {RAMSAR_LICENCE} | "
        f"{today} | {ramsar_sha} | EPSG:4326 (native GDA2020) | true |"
    )
    print(
        f"| DEA Waterbodies v3 (Swan subset) | {WATERBODIES_URL} | CC BY 4.0 | "
        f"{today} | {wb_sha} (sha256 of canonical JSON without timeStamp; covers "
        "all properties, so a DEA refresh changes it); "
        f"geometry {geo_sha} (sha256 of the uid-sorted uid and geometry of every "
        "feature; unchanged by property refreshes) | EPSG:4326 | true |"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
