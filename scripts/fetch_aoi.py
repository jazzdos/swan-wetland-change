"""Download the AOI layers into data/external and print SOURCES.md rows.

Ramsar sites: DBCA-010 via the open SLIP ArcGIS REST service, layer 9.
DEA Waterbodies v3: WFS bbox query over the Swan Coastal Plain.
Both fetch without a login. Re-running overwrites the files.

The Ramsar checksum is the sha256 of the raw response bytes. The Waterbodies
checksum is the sha256 of canonical JSON with the top-level WFS timeStamp
removed, because that field changes on every request. The file is written only
after the checksum succeeds, so an error body never replaces a good download.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import requests

OUT = Path("data/external")
RAMSAR_URL = (
    "https://public-services.slip.wa.gov.au/public/rest/services/"
    "SLIP_Public_Services/Environment/MapServer/9/query"
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


def fetch(
    url: str,
    params: dict[str, str],
    dest: Path,
    *,
    checksum: Callable[[bytes], str] = raw_sha256,
) -> str:
    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()
    content = response.content
    digest = checksum(content)
    dest.write_bytes(content)
    return digest


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).date().isoformat()
    ramsar = OUT / "dbca_010_ramsar_sites.geojson"
    waterbodies = OUT / "dea_waterbodies_v3_swan.geojson"
    ramsar_sha = fetch(RAMSAR_URL, RAMSAR_PARAMS, ramsar)
    wb_sha = fetch(
        WATERBODIES_URL,
        WATERBODIES_PARAMS,
        waterbodies,
        checksum=stable_geojson_checksum,
    )
    print("Add or update these rows in data/SOURCES.md:")
    print(
        f"| DBCA-010 Ramsar Sites | {RAMSAR_URL} | CC BY-SA 4.0 (data.gov.au) | "
        f"{today} | {ramsar_sha} | EPSG:4326 (native GDA2020) | true |"
    )
    print(
        f"| DEA Waterbodies v3 (Swan subset) | {WATERBODIES_URL} | CC BY 4.0 | "
        f"{today} | {wb_sha} (sha256 of canonical JSON without timeStamp) | "
        "EPSG:4326 | true |"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
