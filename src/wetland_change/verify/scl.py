"""Matrix row: SCL read and alignment against the ESA class percentages.

The item carries ESA's own class shares (`s2:water_percentage` and so on,
computed over SCL != 0). Recomputing them from the full-resolution SCL must
land within one percentage point, which proves the right SCL file was read
and the class codes are interpreted correctly.

Overviews are never used here. The Earth Search SCL COGs build their
overviews with mode resampling (OVR_RESAMPLING_ALG=MODE), which favours the
locally dominant class and biases the vegetation and not_vegetated shares by
2 to 3 pp at 1/16.
"""

from __future__ import annotations

import math

import numpy as np
from rasterio.windows import Window

from wetland_change.catalogue.item import SceneItem
from wetland_change.raster.read import RasterReader
from wetland_change.verify.checks import Check

_CLASSES: dict[str, tuple[int, ...]] = {
    "water": (6,),
    "vegetation": (4,),
    "not_vegetated": (5,),
    "cloud": (8, 9, 10),
}
_PROPERTIES = {
    "water": "s2:water_percentage",
    "vegetation": "s2:vegetation_percentage",
    "not_vegetated": "s2:not_vegetated_percentage",
    "cloud": "eo:cloud_cover",
}


def scl_shares(scl: np.ndarray) -> dict[str, float]:
    valid = scl[scl != 0]
    n = valid.size
    return {
        name: (100.0 * float(np.isin(valid, classes).sum()) / n) if n else float("nan")
        for name, classes in _CLASSES.items()
    }


def scl_checks(
    scene: SceneItem, reader: RasterReader, *, tolerance_pp: float = 1.0
) -> list[Check]:
    grid = reader.open_grid(scene.scl_href)
    scl = reader.read(scene.scl_href, Window(0, 0, grid.width, grid.height))
    shares = scl_shares(scl)
    checks: list[Check] = []
    for name, prop in _PROPERTIES.items():
        reference = scene.raw["properties"].get(prop)
        if reference is None:
            checks.append(
                Check(f"scl_share_{name}", None, shares[name], tolerance_pp, prop)
            )
            continue
        if math.isnan(shares[name]):
            checks.append(
                Check(
                    f"scl_share_{name}",
                    None,
                    None,
                    tolerance_pp,
                    f"{prop} = {reference}",
                    {"item": scene.item_id, "reason": "no valid SCL pixels"},
                )
            )
            continue
        diff = abs(shares[name] - float(reference))
        checks.append(
            Check(
                f"scl_share_{name}",
                passed=diff <= tolerance_pp,
                measured=shares[name],
                threshold=tolerance_pp,
                reference=f"{prop} = {reference}",
                detail={
                    "item": scene.item_id,
                    "resolution": "full",
                    "diff_pp": diff,
                },
            )
        )
    return checks
