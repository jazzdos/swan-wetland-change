"""Matrix row: water extent against DEA Sentinel-2 Water Observations.

`ga_s2_wo_provisional_3` is on the same 10 m grid (EPSG:32750) for the same
pass. Bit 128 is wet; bits 1 (nodata), 2 (non-contiguous), 32 (cloud
shadow) and 64 (cloud) exclude a pixel. Agreement is scored on pixels both
products call clear.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import requests

from wetland_change.catalogue.item import SceneItem
from wetland_change.config import WaterConfig
from wetland_change.indices import mndwi, ndwi
from wetland_change.mask import clear_mask
from wetland_change.raster.env import cog_env
from wetland_change.raster.read import BandStack, RasterioReader, RasterReader
from wetland_change.verify.checks import Check
from wetland_change.windows import Grid, PlannedWindow

DEA_STAC = "https://explorer.dea.ga.gov.au/stac"
WO_COLLECTION = "ga_s2_wo_provisional_3"
WO_WET = 128
WO_EXCLUDE = 1 | 2 | 32 | 64
_S3 = "s3://dea-public-data/"
_HTTPS = "https://dea-public-data.s3.ap-southeast-2.amazonaws.com/"


def wo_agreement(
    pipeline_water: np.ndarray, pipeline_clear: np.ndarray, wo: np.ndarray
) -> tuple[float, int]:
    """(share of mutually clear pixels where the two agree, count)."""
    wo_clear = (wo & WO_EXCLUDE) == 0
    both = pipeline_clear & wo_clear
    n = int(both.sum())
    if n == 0:
        return float("nan"), 0
    wo_water = (wo & WO_WET) > 0
    return float(np.mean(pipeline_water[both] == wo_water[both])), n


def find_wo_href(
    scene: SceneItem, bbox_4326: tuple[float, float, float, float]
) -> str | None:
    """The WO `water` asset for the same date and MGRS tile, as https."""
    day = scene.datetime.date().isoformat()
    body: dict[str, Any] = {
        "collections": [WO_COLLECTION],
        "bbox": list(bbox_4326),
        "datetime": f"{day}T00:00:00Z/{day}T23:59:59Z",
        "limit": 50,
    }
    response = requests.post(f"{DEA_STAC}/search", json=body, timeout=60)
    response.raise_for_status()
    tile_token = f"/{scene.tile[2:]}/"
    for feature in response.json().get("features", []):
        href = str(feature["assets"]["water"]["href"])
        if tile_token in href:
            return href.replace(_S3, _HTTPS)
    return None


def dea_reader() -> RasterioReader:
    return RasterioReader(env=cog_env(AWS_REGION="ap-southeast-2"))


def wo_check(
    scene: SceneItem,
    stack: BandStack,
    planned: PlannedWindow,
    inside: np.ndarray,
    *,
    water: WaterConfig,
    wo_href: str,
    reader: RasterReader,
    scene_grid: Grid | None = None,
    agreement_min: float = 0.91,
) -> Check:
    name = "water_vs_dea_s2_wo"
    wo_grid = reader.open_grid(wo_href)
    # `reader` is the DEA reader; the scene grid comes from the caller when it
    # already has it (it was read with the scene's own reader and environment).
    scene_grid = scene_grid or reader.open_grid(scene.bands["green"].href)
    if wo_grid.transform != scene_grid.transform:
        return Check(
            name, False, None, agreement_min, wo_href, {"reason": "grid differs"}
        )
    wo = reader.read(wo_href, planned.window10)
    clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
    index = (
        ndwi(stack.green, stack.nir)
        if water.method == "ndwi"
        else mndwi(stack.green, stack.swir16)
    )
    with np.errstate(invalid="ignore"):
        pipeline_water = clear & (index > water.threshold)
    agreement, n = wo_agreement(pipeline_water, clear, wo)
    scl_agreement, _ = wo_agreement(clear & (stack.scl == 6), clear, wo)
    return Check(
        name,
        passed=bool(agreement >= agreement_min) if n else None,
        measured=agreement if n else None,
        threshold=agreement_min,
        reference=wo_href,
        detail={
            "item": scene.item_id,
            "n_mutually_clear": n,
            "method": water.method,
            "threshold": water.threshold,
            "scl_agreement": scl_agreement,
        },
    )
