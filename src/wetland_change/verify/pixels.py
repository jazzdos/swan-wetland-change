"""Matrix row: reads the right bytes, against Planetary Computer.

Planetary Computer hosts the same ESA product under an id without the
`N0513` baseline token and signs asset hrefs with a SAS token. The same
window must give the same transform and bit-identical DN.
"""

from __future__ import annotations

import numpy as np
from rasterio.windows import Window

from wetland_change.catalogue.item import SceneItem
from wetland_change.raster.env import cog_env
from wetland_change.raster.read import RasterioReader, RasterReader
from wetland_change.verify.checks import Check

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_COLLECTION = "sentinel-2-l2a"


def pc_item_id(product_uri: str) -> str:
    stem = product_uri.removesuffix(".SAFE")
    return "_".join(token for token in stem.split("_") if not token.startswith("N0"))


def pixel_check(scene: SceneItem, reader: RasterReader, window: Window) -> Check:
    import planetary_computer
    import pystac_client

    name = "pixels_vs_planetary_computer"
    reference = f"{PC_STAC} {PC_COLLECTION} {pc_item_id(scene.product_uri)} B03"
    catalog = pystac_client.Client.open(
        PC_STAC, modifier=planetary_computer.sign_inplace
    )
    items = list(
        catalog.search(
            collections=[PC_COLLECTION], ids=[pc_item_id(scene.product_uri)]
        ).items()
    )
    if not items:
        return Check(
            name,
            None,
            None,
            None,
            reference,
            {"reason": "not on Planetary Computer yet"},
        )
    pc_baseline = str(items[0].properties.get("s2:processing_baseline"))
    if pc_baseline != scene.processing_baseline:
        return Check(
            name,
            None,
            None,
            None,
            reference,
            {
                "reason": "different processing baseline",
                "earth_search_baseline": scene.processing_baseline,
                "planetary_computer_baseline": pc_baseline,
            },
        )
    pc_href = str(items[0].assets["B03"].href)
    env = {
        k: v for k, v in cog_env().items() if k != "CPL_VSIL_CURL_ALLOWED_EXTENSIONS"
    }
    pc_reader = RasterioReader(env={**env, "AWS_NO_SIGN_REQUEST": "NO"})
    es_grid = reader.open_grid(scene.bands["green"].href)
    pc_grid = pc_reader.open_grid(pc_href)
    es_dn = reader.read(scene.bands["green"].href, window)
    pc_dn = pc_reader.read(pc_href, window)
    same_transform = es_grid.transform == pc_grid.transform
    identical = bool(np.array_equal(es_dn, pc_dn))
    return Check(
        name,
        passed=same_transform and identical,
        measured=float(np.mean(es_dn == pc_dn)),
        threshold=1.0,
        reference=reference,
        detail={
            "item": scene.item_id,
            "same_transform": same_transform,
            "window": [window.col_off, window.row_off, window.width, window.height],
        },
    )
