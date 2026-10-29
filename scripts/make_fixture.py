"""Write a 64 by 64 pixel (10 m) window of one real scene as test fixtures.

Window: a 640 m square centred on the Thomsons Lake centroid (389620 E,
6442400 N in EPSG:32750) on tile 50HLK, scene
S2C_T50HLK_20261027T022351_L2A. Bands at 10 m are 64 by 64; SCL and B11 at
20 m are 32 by 32. Offsets are even so the window sits on the 20 m lattice.
The STAC item JSON and the ESA product XML are saved alongside so scaling
and SCL tests have their references.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import rasterio
import requests
from rasterio.windows import Window

ITEM_URL = (
    "https://earth-search.aws.element84.com/v1/collections/"
    "sentinel-2-c1-l2a/items/S2C_T50HLK_20261027T022351_L2A"
)
OUT = Path("tests/fixtures/thomsons_20261027")
# Pixel offsets on the 10 m grid: tile origin (300000, 6500020), so column
# 8930 is 389300 E and row 5730 is 6442720 N. Both even (20 m lattice).
COL10, ROW10, SIZE10 = 8930, 5730, 64
ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "AWS_NO_SIGN_REQUEST": "YES",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
}


def save_window(href: str, dest: Path, window: Window) -> None:
    with rasterio.Env(**ENV), rasterio.open(href) as src:
        data = src.read(1, window=window)
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            transform=src.window_transform(window),
            compress="deflate",
            tiled=False,
        )
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
    with rasterio.open(dest, "w", **profile) as dst:
        dst.write(data, 1)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    item = requests.get(ITEM_URL, timeout=60).json()
    (OUT / "item.json").write_text(json.dumps(item, indent=1))
    xml = requests.get(item["assets"]["product_metadata"]["href"], timeout=60).text
    (OUT / "product_metadata.xml").write_text(xml)
    w10 = Window(COL10, ROW10, SIZE10, SIZE10)
    w20 = Window(COL10 // 2, ROW10 // 2, SIZE10 // 2, SIZE10 // 2)
    for key, name, window in (
        ("green", "B03", w10),
        ("red", "B04", w10),
        ("nir", "B08", w10),
        ("swir16", "B11", w20),
        ("scl", "SCL", w20),
    ):
        save_window(item["assets"][key]["href"], OUT / f"{name}.tif", window)
        print("wrote", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
