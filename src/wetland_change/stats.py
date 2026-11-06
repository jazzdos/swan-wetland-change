"""Polygon rasterisation and the per-polygon, per-scene summary row."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from affine import Affine
from pyproj import CRS
from rasterio.features import geometry_mask
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from wetland_change.aoi import AoiPolygon
from wetland_change.catalogue.item import SceneItem
from wetland_change.config import WaterConfig, WaterSetting
from wetland_change.indices import mndwi, ndvi, ndwi
from wetland_change.mask import CLEAR_BANDS, clear_mask, cloud_mask, water_mask_scl
from wetland_change.raster.read import BandStack
from wetland_change.windows import PlannedWindow

PIXEL_STEP_M = 10.0


def pixel_area_ha(transform: Affine, epsg: int) -> float:
    """Pixel area in hectares from the window transform, for a 10 m metric grid.

    Raises ValueError when the CRS is not projected, has axes that are not in
    metres, the transform is rotated, or the pixel step is not 10 m.
    """
    crs = CRS.from_epsg(epsg)
    if not crs.is_projected:
        raise ValueError(f"EPSG:{epsg} is not a projected CRS")
    if any(axis.unit_conversion_factor != 1.0 for axis in crs.axis_info):
        raise ValueError(f"EPSG:{epsg} axes are not in metres")
    if abs(transform.b) > 1e-9 or abs(transform.d) > 1e-9:
        raise ValueError(f"transform is rotated: {transform}")
    if not (
        math.isclose(abs(transform.a), PIXEL_STEP_M, abs_tol=1e-6)
        and math.isclose(abs(transform.e), PIXEL_STEP_M, abs_tol=1e-6)
    ):
        raise ValueError(
            f"pixel step must be 10 m, got {abs(transform.a)} by {abs(transform.e)}"
        )
    return abs(transform.a) * abs(transform.e) / 10_000


@dataclass(frozen=True)
class ObservationRow:
    polygon_id: str
    site: str
    aoi_layer: str
    item_id: str
    product_uri: str
    datetime: datetime
    tile: str
    processing_baseline: str
    scene_coverage: float
    n_pixels: int
    n_clear: int
    valid_fraction: float
    cloud_fraction: float
    water_ha_index: float
    water_ha_scl: float
    ndwi_median: float
    mndwi_median: float
    ndvi_median: float
    # None from summarise; pipeline.process_scene fills it from verify.wo.
    dea_wo_agreement: float | None
    geometry_4326: BaseGeometry
    run_id: str


def rasterise(
    geometry: BaseGeometry, transform: Affine, shape: tuple[int, int]
) -> np.ndarray:
    """True for pixels whose centre falls inside `geometry`."""
    mask: np.ndarray = geometry_mask(
        [mapping(geometry)], out_shape=shape, transform=transform, invert=True
    )
    return mask


def _median(values: np.ndarray, mask: np.ndarray) -> float:
    selected = values[mask]
    selected = selected[np.isfinite(selected)]
    return float(np.median(selected)) if selected.size else float("nan")


def water_pixels(
    setting: WaterSetting, stack: BandStack, clear: np.ndarray
) -> np.ndarray:
    """Clear pixels the setting calls water: SCL class 6 for scl6, else the
    setting's index (ndwi or mndwi) above its threshold."""
    if setting.method == "scl6":
        scl_water: np.ndarray = clear & water_mask_scl(stack.scl)
        return scl_water
    if setting.threshold is None:  # WaterSetting's validator forbids this
        raise ValueError(f"method {setting.method!r} needs a threshold")
    index = (
        ndwi(stack.green, stack.nir)
        if setting.method == "ndwi"
        else mndwi(stack.green, stack.swir16)
    )
    with np.errstate(invalid="ignore"):
        water: np.ndarray = clear & (index > setting.threshold)
    return water


def summarise(
    polygon: AoiPolygon,
    scene: SceneItem,
    stack: BandStack,
    planned: PlannedWindow,
    *,
    water: WaterConfig,
    run_id: str,
) -> ObservationRow:
    """One observation row: areas in hectares, medians over clear pixels.

    water_ha_index uses the polygon's override from water.overrides when it has
    one, else the global setting (decision 0005).

    Raises ValueError for a non-10 m or non-metric stack.

    dea_wo_agreement is left None here; `pipeline.process_scene` fills it from
    `verify.wo` when DEA holds a WO item for the scene.
    """
    pixel_ha = pixel_area_ha(stack.transform, stack.epsg)
    inside = rasterise(polygon.geometry, stack.transform, stack.shape)
    n_pixels = int(inside.sum())
    clear = (
        clear_mask(stack.scl, *(getattr(stack, band) for band in CLEAR_BANDS)) & inside
    )
    n_clear = int(clear.sum())
    cloudy = cloud_mask(stack.scl) & inside
    ndwi_arr = ndwi(stack.green, stack.nir)
    mndwi_arr = mndwi(stack.green, stack.swir16)
    ndvi_arr = ndvi(stack.nir, stack.red)
    water_index = water_pixels(water.for_polygon(polygon.polygon_id), stack, clear)
    water_scl = clear & water_mask_scl(stack.scl)
    return ObservationRow(
        polygon_id=polygon.polygon_id,
        site=polygon.site,
        aoi_layer=polygon.layer,
        item_id=scene.item_id,
        product_uri=scene.product_uri,
        datetime=scene.datetime,
        tile=scene.tile,
        processing_baseline=scene.processing_baseline,
        scene_coverage=planned.scene_coverage,
        n_pixels=n_pixels,
        n_clear=n_clear,
        valid_fraction=n_clear / n_pixels if n_pixels else 0.0,
        cloud_fraction=int(cloudy.sum()) / n_pixels if n_pixels else 0.0,
        water_ha_index=float(water_index.sum()) * pixel_ha,
        water_ha_scl=float(water_scl.sum()) * pixel_ha,
        ndwi_median=_median(ndwi_arr, clear),
        mndwi_median=_median(mndwi_arr, clear),
        ndvi_median=_median(ndvi_arr, clear),
        dea_wo_agreement=None,
        geometry_4326=polygon.geometry_4326,
        run_id=run_id,
    )
