"""Polygon rasterisation and the per-polygon, per-scene summary row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from affine import Affine
from rasterio.features import geometry_mask
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from wetland_change.aoi import AoiPolygon
from wetland_change.catalogue.item import SceneItem
from wetland_change.config import WaterConfig
from wetland_change.indices import mndwi, ndvi, ndwi
from wetland_change.mask import clear_mask, cloud_mask, water_mask_scl
from wetland_change.raster.read import BandStack
from wetland_change.windows import PlannedWindow

PIXEL_AREA_HA = 0.01  # 10 m by 10 m


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


def summarise(
    polygon: AoiPolygon,
    scene: SceneItem,
    stack: BandStack,
    planned: PlannedWindow,
    *,
    water: WaterConfig,
    run_id: str,
) -> ObservationRow:
    """One observation row: areas in hectares, medians over clear pixels."""
    inside = rasterise(polygon.geometry, stack.transform, stack.shape)
    n_pixels = int(inside.sum())
    clear = (
        clear_mask(stack.scl, stack.green, stack.red, stack.nir, stack.swir16) & inside
    )
    n_clear = int(clear.sum())
    cloudy = cloud_mask(stack.scl) & inside
    ndwi_arr = ndwi(stack.green, stack.nir)
    mndwi_arr = mndwi(stack.green, stack.swir16)
    ndvi_arr = ndvi(stack.nir, stack.red)
    index_arr = ndwi_arr if water.method == "ndwi" else mndwi_arr
    with np.errstate(invalid="ignore"):
        water_index = clear & (index_arr > water.threshold)
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
        water_ha_index=float(water_index.sum()) * PIXEL_AREA_HA,
        water_ha_scl=float(water_scl.sum()) * PIXEL_AREA_HA,
        ndwi_median=_median(ndwi_arr, clear),
        mndwi_median=_median(mndwi_arr, clear),
        ndvi_median=_median(ndvi_arr, clear),
        dea_wo_agreement=None,
        geometry_4326=polygon.geometry_4326,
        run_id=run_id,
    )
