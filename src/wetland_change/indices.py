"""Normalised-difference indices on float reflectance.

NDWI (McFeeters 1996) = (green - nir) / (green + nir)
MNDWI (Xu 2006)       = (green - swir16) / (green + swir16)
NDVI                  = (nir - red) / (nir + red)

A zero denominator gives NaN. Integer input is refused: it would overflow
the sum (uint16 wraps) and treat the nodata DN as a value.
"""

from __future__ import annotations

import numpy as np


def reject_integer_bands(*, context: str, **bands: np.ndarray) -> None:
    for name, value in bands.items():
        if np.issubdtype(value.dtype, np.integer):
            raise TypeError(
                f"{context} received integer-typed {name!r} (dtype {value.dtype}); "
                "convert DN with to_reflectance() first"
            )


def normalised_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b) as float32, NaN where a + b is zero."""
    denominator = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(denominator != 0, (a - b) / denominator, np.nan)
    return np.asarray(result, dtype=np.float32)


def ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    reject_integer_bands(context="ndwi", green=green, nir=nir)
    return normalised_difference(green, nir)


def mndwi(green: np.ndarray, swir16: np.ndarray) -> np.ndarray:
    reject_integer_bands(context="mndwi", green=green, swir16=swir16)
    return normalised_difference(green, swir16)


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    reject_integer_bands(context="ndvi", nir=nir, red=red)
    return normalised_difference(nir, red)
