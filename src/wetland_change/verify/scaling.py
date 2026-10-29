"""Matrix row: reflectance scaling against the ESA product XML."""

from __future__ import annotations

from wetland_change.catalogue.item import SceneItem
from wetland_change.raster.scaling import (
    ScalingMismatch,
    check_band_scaling,
    parse_product_metadata,
)
from wetland_change.verify.checks import Check


def scaling_check(scene: SceneItem, xml_text: str) -> Check:
    reference = "ESA MTD_MSIL2A.xml BOA_QUANTIFICATION_VALUE and BOA_ADD_OFFSET"
    try:
        esa = parse_product_metadata(xml_text)
        for band in scene.bands.values():
            check_band_scaling(band, esa)
    except ScalingMismatch as exc:
        return Check(
            "reflectance_scaling",
            passed=False,
            measured=None,
            threshold=None,
            reference=reference,
            detail={"item": scene.item_id, "error": str(exc)},
        )
    return Check(
        "reflectance_scaling",
        passed=True,
        measured=None,
        threshold=None,
        reference=reference,
        detail={"item": scene.item_id, "scale": esa.scale, "offset": esa.offset},
    )
