"""Download the AOI layers into data/external and print SOURCES.md rows.

Ramsar sites: DBCA-010 via the open SLIP ArcGIS REST service, layer 9.
DEA Waterbodies v3: WFS bbox query over the Swan Coastal Plain.
Both fetch without a login. Re-running overwrites the files.
"""

from __future__ import annotations

import hashlib
import sys
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


def fetch(url: str, params: dict[str, str], dest: Path) -> str:
    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return hashlib.sha256(response.content).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).date().isoformat()
    ramsar = OUT / "dbca_010_ramsar_sites.geojson"
    waterbodies = OUT / "dea_waterbodies_v3_swan.geojson"
    ramsar_sha = fetch(RAMSAR_URL, RAMSAR_PARAMS, ramsar)
    wb_sha = fetch(WATERBODIES_URL, WATERBODIES_PARAMS, waterbodies)
    print("Add or update these rows in data/SOURCES.md:")
    print(
        f"| DBCA-010 Ramsar Sites | {RAMSAR_URL} | CC BY-SA 4.0 (data.gov.au) | "
        f"{today} | {ramsar_sha} | EPSG:4326 (native GDA2020) | true |"
    )
    print(
        f"| DEA Waterbodies v3 (Swan subset) | {WATERBODIES_URL} | CC BY 4.0 | "
        f"{today} | {wb_sha} | EPSG:4326 | true |"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
