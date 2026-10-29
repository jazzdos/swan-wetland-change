"""Reflectance scaling checked against the ESA product metadata.

`raster:bands` on the item says reflectance = DN * scale + offset. The ESA
MTD_MSIL2A.xml states BOA_QUANTIFICATION_VALUE (Q) and BOA_ADD_OFFSET (A).
They must agree (scale = 1/Q, offset = A/Q) or the item is refused.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np

from wetland_change.catalogue.item import BandSpec


class ScalingMismatch(ValueError):
    """Item metadata and ESA metadata disagree on how to scale DN."""


@dataclass(frozen=True)
class EsaScaling:
    quantification: float
    add_offset: float

    @property
    def scale(self) -> float:
        return 1.0 / self.quantification

    @property
    def offset(self) -> float:
        return self.add_offset / self.quantification


def parse_product_metadata(xml_text: str) -> EsaScaling:
    """Read Q and A from MTD_MSIL2A.xml, namespace-agnostic."""
    root = ET.fromstring(xml_text)
    quantification: float | None = None
    offsets: set[float] = set()
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "BOA_QUANTIFICATION_VALUE" and element.text:
            quantification = float(element.text)
        elif tag == "BOA_ADD_OFFSET" and element.text:
            offsets.add(float(element.text))
    if quantification is None:
        raise ScalingMismatch("BOA_QUANTIFICATION_VALUE not found in product metadata")
    if len(offsets) != 1:
        raise ScalingMismatch(
            f"expected one BOA_ADD_OFFSET value, found {sorted(offsets)}"
        )
    return EsaScaling(quantification=quantification, add_offset=offsets.pop())


def check_band_scaling(
    band: BandSpec, esa: EsaScaling, *, rel_tol: float = 1e-9
) -> None:
    """Raise ScalingMismatch unless the band's scale and offset match the XML."""
    if not math.isclose(band.scale, esa.scale, rel_tol=rel_tol):
        raise ScalingMismatch(
            f"{band.key}: raster:bands scale {band.scale} != 1/{esa.quantification}"
        )
    if not math.isclose(band.offset, esa.offset, rel_tol=rel_tol, abs_tol=1e-12):
        raise ScalingMismatch(
            f"{band.key}: raster:bands offset {band.offset} != "
            f"{esa.add_offset}/{esa.quantification}"
        )


def to_reflectance(dn: np.ndarray, band: BandSpec) -> np.ndarray:
    """DN to float32 reflectance with the nodata DN as NaN.

    Computed in float64 then cast, so 1000 * 1e-4 - 0.1 is exactly 0.0.
    """
    if not np.issubdtype(dn.dtype, np.integer):
        raise TypeError(f"{band.key}: expected integer DN, got {dn.dtype}")
    out = (dn.astype(np.float64) * band.scale + band.offset).astype(np.float32)
    out[dn == band.nodata] = np.nan
    return out
