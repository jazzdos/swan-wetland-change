"""Matrix row: water extent against DEA Sentinel-2 Water Observations.

`ga_s2_wo_provisional_3` is on the same 10 m grid (EPSG:32750) for the same
pass. Only values 0 (clear dry) and 128 (clear wet) are clear; every other
flag bit excludes the pixel. Agreement is scored on pixels both products
call clear. Each polygon is scored with its own water setting and
agreement_min (`WaterConfig.for_polygon`,
docs/decisions/0005-per-polygon-water-settings.md), and `Check.threshold` is
that agreement_min.

`Check.passed` needs agreement at or above agreement_min and the wet area
within `WET_AREA_MAX_PP` percentage points of WO's (design line 226). Wet area
is the wet share of mutually clear pixels for each product. The two shares
differ by at most 1 - agreement, so the clause is implied by a 0.95 floor but
binds at the lower per-polygon floors. `Check.measured` stays the agreement.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any

import numpy as np
import requests

from wetland_change.catalogue.item import SceneItem
from wetland_change.config import WaterConfig
from wetland_change.mask import clear_mask
from wetland_change.raster.env import cog_env
from wetland_change.raster.read import BandStack, RasterioReader, RasterReader
from wetland_change.stats import water_pixels
from wetland_change.verify.checks import Check
from wetland_change.windows import Grid, PlannedWindow

DEA_STAC = "https://explorer.dea.ga.gov.au/stac"
WO_COLLECTION = "ga_s2_wo_provisional_3"
WO_WET = 128
# Only WO values 0 and 128 are clear, so every flag bit below 128 excludes.
WO_EXCLUDE = 1 | 2 | 4 | 8 | 16 | 32 | 64
# Largest allowed gap between pipeline and WO wet share, in percentage points.
WET_AREA_MAX_PP = 5.0
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


def wo_wet_area(
    pipeline_water: np.ndarray, pipeline_clear: np.ndarray, wo: np.ndarray
) -> tuple[int, int, int]:
    """(pipeline wet count, WO wet count, count) over mutually clear pixels.

    Integer counts, so the gap in percentage points is computed as
    `100 * (pipeline - wo) / n` and is exact at the 5 pp limit.
    """
    wo_clear = (wo & WO_EXCLUDE) == 0
    both = pipeline_clear & wo_clear
    n = int(both.sum())
    if n == 0:
        return 0, 0, 0
    wo_water = (wo & WO_WET) > 0
    return int(pipeline_water[both].sum()), int(wo_water[both].sum()), n


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


def wo_candidates(
    scenes: Iterable[SceneItem],
    bbox_4326: tuple[float, float, float, float],
    *,
    find: Callable[
        [SceneItem, tuple[float, float, float, float]], str | None
    ] = find_wo_href,
    limit: int | None = None,
) -> Iterator[tuple[SceneItem, str]]:
    """Scenes DEA still holds a WO product for, newest first, with the href.

    DEA keeps the provisional WO product for about three months, so a live
    check must choose from scenes DEA still holds rather than a pinned date
    (docs/research/2026-11-04-milestone-2-review.md finding L1). `find` is
    called lazily, one scene at a time, and never after `limit` pairs have
    been yielded; `limit=None` means no cap.
    """
    if limit is not None and limit <= 0:
        return
    yielded = 0
    for scene in sorted(scenes, key=lambda s: (s.datetime, s.item_id), reverse=True):
        href = find(scene, bbox_4326)
        if href is None:
            continue
        yield scene, href
        yielded += 1
        if limit is not None and yielded >= limit:
            return


def pooled_agreement(checks: Iterable[Check]) -> tuple[float, int] | None:
    """Pixel-weighted agreement over WO checks, with the pooled pixel count.

    Each check contributes its measured agreement weighted by its
    `n_mutually_clear`; checks with no measurement or no mutually clear pixels
    are skipped. Returns None when nothing contributes. ADR 0005 derives
    agreement_min from agreement pooled this way, not from a single pass.
    """
    agreed = 0.0
    total = 0
    for check in checks:
        n = int(check.detail.get("n_mutually_clear", 0))
        if check.measured is None or n <= 0:
            continue
        agreed += check.measured * n
        total += n
    if total == 0:
        return None
    return agreed / total, total


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
    polygon_id: str | None = None,
    min_clear_pixels: int = 1,
) -> Check:
    name = "water_vs_dea_s2_wo"
    setting = water.for_polygon(polygon_id)
    agreement_min = setting.agreement_min
    base: dict[str, Any] = {
        "item": scene.item_id,
        "method": setting.method,
        "threshold": setting.threshold,
        "agreement_min": agreement_min,
        "override": polygon_id is not None and polygon_id in water.overrides,
    }
    if polygon_id is not None:
        base["polygon_id"] = polygon_id
    wo_grid = reader.open_grid(wo_href)
    # `reader` is the DEA reader; the scene grid comes from the caller when it
    # already has it (it was read with the scene's own reader and environment).
    scene_grid = scene_grid or reader.open_grid(scene.bands["green"].href)
    if wo_grid.transform != scene_grid.transform:
        return Check(
            name,
            False,
            None,
            agreement_min,
            wo_href,
            {**base, "reason": "grid differs"},
        )
    wo = reader.read(wo_href, planned.window10)
    clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
    pipeline_water = water_pixels(setting, stack, clear)
    agreement, n = wo_agreement(pipeline_water, clear, wo)
    scl_agreement, _ = wo_agreement(clear & (stack.scl == 6), clear, wo)
    if 0 < n < min_clear_pixels:
        # Too few pixels to score: a reason skip, not an error. `measured`
        # stays None so pooled_agreement ignores it.
        return Check(
            name,
            None,
            None,
            agreement_min,
            wo_href,
            {
                **base,
                "n_mutually_clear": n,
                "min_clear_pixels": min_clear_pixels,
                "reason": f"fewer than {min_clear_pixels} mutually clear pixels",
            },
        )
    wet_pipeline, wet_wo, wet_n = wo_wet_area(pipeline_water, clear, wo)
    if wet_n:
        wet_diff_pp = 100 * (wet_pipeline - wet_wo) / wet_n
        wet_share_pipeline, wet_share_wo = wet_pipeline / wet_n, wet_wo / wet_n
    else:
        wet_diff_pp = wet_share_pipeline = wet_share_wo = float("nan")
    wet_passed = bool(abs(wet_diff_pp) <= WET_AREA_MAX_PP)
    return Check(
        name,
        passed=bool(agreement >= agreement_min and wet_passed) if n else None,
        measured=agreement if n else None,
        threshold=agreement_min,
        reference=wo_href,
        detail={
            **base,
            "n_mutually_clear": n,
            "scl_agreement": scl_agreement,
            "wet_area_pipeline": wet_share_pipeline,
            "wet_area_wo": wet_share_wo,
            "wet_area_diff_pp": wet_diff_pp,
            "wet_area_max_pp": WET_AREA_MAX_PP,
            "wet_area_passed": wet_passed if n else None,
        },
    )
