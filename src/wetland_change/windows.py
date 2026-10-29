"""Pixel windows on the scene grid, snapped to the 20 m SCL lattice.

Sentinel-2 tiles put the 10 m and 20 m grids on the same origin, so a 10 m
window with even offsets and even lengths maps exactly 2:1 onto a 20 m
window. That is what lets SCL and swir16 be upsampled by repetition with
no resampling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from affine import Affine
from rasterio.windows import Window
from rasterio.windows import transform as window_transform
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class Grid:
    transform: Affine
    width: int
    height: int
    epsg: int

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        t = self.transform
        return (t.c, t.f + t.e * self.height, t.c + t.a * self.width, t.f)


@dataclass(frozen=True)
class PlannedWindow:
    window10: Window
    window20: Window
    transform10: Affine
    scene_coverage: float

    @property
    def shape10(self) -> tuple[int, int]:
        return (int(self.window10.height), int(self.window10.width))


def _require_10m_on_20m_lattice(grid: Grid) -> None:
    t = grid.transform
    if t.a != 10 or t.e != -10 or t.b or t.d:
        raise ValueError(f"expected an axis-aligned 10 m grid, got {t!r}")
    if t.c % 20 or t.f % 20:
        raise ValueError(f"grid origin ({t.c}, {t.f}) is not on the 20 m lattice")


def plan_window(
    polygon: BaseGeometry, grid: Grid, *, pad_px: int = 2
) -> PlannedWindow | None:
    """Smallest even-aligned 10 m window around `polygon`, clipped to the
    scene, or None when the polygon misses the scene entirely.

    `polygon` must already be in the grid's CRS. `scene_coverage` is the
    share of the polygon's area inside the scene extent; a polygon on a
    tile seam gets one row per scene with coverage below 1.
    """
    _require_10m_on_20m_lattice(grid)
    overlap = polygon.intersection(box(*grid.bounds))
    if overlap.is_empty or polygon.area == 0:
        return None
    t = grid.transform
    minx, miny, maxx, maxy = polygon.bounds
    col0 = math.floor((minx - t.c) / t.a) - pad_px
    col1 = math.ceil((maxx - t.c) / t.a) + pad_px
    row0 = math.floor((t.f - maxy) / -t.e) - pad_px
    row1 = math.ceil((t.f - miny) / -t.e) + pad_px
    col0 = max(0, col0 - col0 % 2)
    row0 = max(0, row0 - row0 % 2)
    col1 = min(grid.width, col1 + col1 % 2)
    row1 = min(grid.height, row1 + row1 % 2)
    if col1 <= col0 or row1 <= row0:
        return None
    window10 = Window(col0, row0, col1 - col0, row1 - row0)
    window20 = Window(col0 // 2, row0 // 2, (col1 - col0) // 2, (row1 - row0) // 2)
    return PlannedWindow(
        window10=window10,
        window20=window20,
        transform10=window_transform(window10, t),
        scene_coverage=overlap.area / polygon.area,
    )
