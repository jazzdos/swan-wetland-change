"""Scene Classification Layer handling.

ESA SCL classes: 0 no data, 1 saturated or defective, 2 dark area (cast
shadow), 3 cloud shadow, 4 vegetation, 5 not vegetated, 6 water, 7
unclassified, 8 cloud medium probability, 9 cloud high probability, 10 thin
cirrus, 11 snow or ice. Clear means 4, 5, 6, 7 and 11. Cloud means 8, 9 and
10, which is the ESA definition behind `eo:cloud_cover`.
"""

from __future__ import annotations

import numpy as np

SCL_NODATA = 0
SCL_WATER = 6
CLEAR_CLASSES: tuple[int, ...] = (4, 5, 6, 7, 11)
CLOUD_CLASSES: tuple[int, ...] = (8, 9, 10)
EXCLUDED_CLASSES: tuple[int, ...] = (0, 1, 2, 3, 8, 9, 10)


def upsample_2x(array: np.ndarray) -> np.ndarray:
    """Nearest-neighbour 2:1 upsampling of a 20 m array onto the 10 m grid."""
    return np.repeat(np.repeat(array, 2, axis=0), 2, axis=1)


def clear_mask(scl: np.ndarray, *bands: np.ndarray) -> np.ndarray:
    """True where SCL is a clear class and every given band is finite."""
    clear = np.isin(scl, CLEAR_CLASSES)
    for band in bands:
        clear &= np.isfinite(band)
    return clear


def cloud_mask(scl: np.ndarray) -> np.ndarray:
    return np.isin(scl, CLOUD_CLASSES)


def water_mask_scl(scl: np.ndarray) -> np.ndarray:
    return np.asarray(scl == SCL_WATER, dtype=bool)
