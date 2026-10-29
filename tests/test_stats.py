from __future__ import annotations

import numpy as np
import pytest
from affine import Affine
from rasterio.windows import Window
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from wetland_change.aoi import AoiPolygon
from wetland_change.catalogue.item import SceneItem
from wetland_change.config import WaterConfig
from wetland_change.raster.read import BandStack, RasterioReader, read_stack
from wetland_change.stats import PIXEL_AREA_HA, ObservationRow, rasterise, summarise
from wetland_change.windows import Grid, PlannedWindow, plan_window

T = Affine(10, 0, 0, 0, -10, 40)


def _stack() -> BandStack:
    scl = np.array(
        [[6, 6, 6, 6], [6, 6, 6, 6], [4, 4, 4, 4], [9, 9, 0, 0]], dtype=np.uint8
    )
    green = np.where(scl == 6, 0.3, np.where(scl == 4, 0.1, 0.2)).astype(np.float32)
    nir = np.where(scl == 6, 0.1, np.where(scl == 4, 0.5, 0.2)).astype(np.float32)
    red = np.full((4, 4), 0.1, dtype=np.float32)
    swir16 = np.full((4, 4), 0.05, dtype=np.float32)
    return BandStack(
        green=green, red=red, nir=nir, swir16=swir16, scl=scl, transform=T, epsg=32750
    )


def _polygon(geom: BaseGeometry) -> AoiPolygon:
    return AoiPolygon(
        "ramsar-52", "Forrestdale & Thomsons Lakes", "ramsar", geom, box(0, 0, 1, 1)
    )


def _planned() -> PlannedWindow:
    return PlannedWindow(Window(0, 0, 4, 4), Window(0, 0, 2, 2), T, scene_coverage=1.0)


def test_rasterise_uses_pixel_centres() -> None:
    assert rasterise(box(0, 0, 40, 40), T, (4, 4)).sum() == 16
    assert rasterise(box(0, 0, 20, 40), T, (4, 4)).sum() == 8
    assert rasterise(box(0, 0, 4, 4), T, (4, 4)).sum() == 0


def test_summarise_synthetic_ndwi(fixture_scene: SceneItem) -> None:
    row = summarise(
        _polygon(box(0, 0, 40, 40)),
        fixture_scene,
        _stack(),
        _planned(),
        water=WaterConfig(method="ndwi", threshold=0.0),
        run_id="run-1",
    )
    assert isinstance(row, ObservationRow)
    assert row.polygon_id == "ramsar-52"
    assert row.item_id == fixture_scene.item_id
    assert row.tile == "50HLK"
    assert (row.n_pixels, row.n_clear) == (16, 12)
    assert row.valid_fraction == pytest.approx(0.75)
    assert row.cloud_fraction == pytest.approx(0.125)
    assert row.water_ha_scl == pytest.approx(8 * PIXEL_AREA_HA)
    assert row.water_ha_index == pytest.approx(8 * PIXEL_AREA_HA)
    assert row.ndwi_median == pytest.approx(0.5, abs=1e-6)
    assert row.mndwi_median == pytest.approx(0.25 / 0.35, abs=1e-6)
    assert row.ndvi_median == pytest.approx(0.0, abs=1e-6)
    assert row.dea_wo_agreement is None
    assert row.run_id == "run-1"
    assert row.scene_coverage == 1.0


def test_summarise_mndwi_threshold(fixture_scene: SceneItem) -> None:
    row = summarise(
        _polygon(box(0, 0, 40, 40)),
        fixture_scene,
        _stack(),
        _planned(),
        water=WaterConfig(method="mndwi", threshold=0.5),
        run_id="run-1",
    )
    assert row.water_ha_index == pytest.approx(8 * PIXEL_AREA_HA)


def test_summarise_half_polygon(fixture_scene: SceneItem) -> None:
    row = summarise(
        _polygon(box(0, 0, 20, 40)),
        fixture_scene,
        _stack(),
        _planned(),
        water=WaterConfig(),
        run_id="run-1",
    )
    assert row.n_pixels == 8
    assert row.water_ha_scl == pytest.approx(4 * PIXEL_AREA_HA)


def test_summarise_no_clear_pixels_gives_nan_medians(fixture_scene: SceneItem) -> None:
    stack = _stack()
    cloudy = BandStack(
        green=stack.green,
        red=stack.red,
        nir=stack.nir,
        swir16=stack.swir16,
        scl=np.full((4, 4), 9, dtype=np.uint8),
        transform=T,
        epsg=32750,
    )
    row = summarise(
        _polygon(box(0, 0, 40, 40)),
        fixture_scene,
        cloudy,
        _planned(),
        water=WaterConfig(),
        run_id="r",
    )
    assert row.valid_fraction == 0.0
    assert row.cloud_fraction == 1.0
    assert np.isnan(row.ndwi_median)
    assert row.water_ha_index == 0.0


def test_summarise_fixture_lake(
    fixture_scene: SceneItem, fixture_grid: Grid, fixture_polygon: BaseGeometry
) -> None:
    planned = plan_window(fixture_polygon, fixture_grid)
    assert planned is not None
    stack = read_stack(fixture_scene, planned, RasterioReader())
    row = summarise(
        _polygon(fixture_polygon),
        fixture_scene,
        stack,
        planned,
        water=WaterConfig(),
        run_id="r",
    )
    assert row.n_pixels == 44 * 44
    assert row.valid_fraction > 0.9
    assert row.water_ha_scl > 5.0
    assert row.water_ha_scl <= row.n_pixels * PIXEL_AREA_HA
