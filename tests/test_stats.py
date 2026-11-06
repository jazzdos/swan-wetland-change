from __future__ import annotations

import numpy as np
import pytest
from affine import Affine
from rasterio.windows import Window
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from wetland_change.aoi import AoiPolygon
from wetland_change.catalogue.item import SceneItem
from wetland_change.config import WaterConfig, WaterSetting
from wetland_change.mask import clear_mask
from wetland_change.pipeline import process_scene
from wetland_change.raster.read import BandStack, RasterioReader, read_stack
from wetland_change.stats import (
    PIXEL_AREA_HA,
    ObservationRow,
    rasterise,
    summarise,
    water_pixels,
)
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


def test_summarise_synthetic_ndwi_leaves_wo_agreement_for_process_scene(
    fixture_scene: SceneItem,
) -> None:
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


def _poly(polygon_id: str, geom: BaseGeometry) -> AoiPolygon:
    return AoiPolygon(
        polygon_id, "Forrestdale & Thomsons Lakes", "ramsar", geom, box(0, 0, 1, 1)
    )


def test_summarise_applies_the_polygon_override_on_the_fixture(
    fixture_scene: SceneItem, fixture_grid: Grid, fixture_polygon: BaseGeometry
) -> None:
    planned = plan_window(fixture_polygon, fixture_grid)
    assert planned is not None
    stack = read_stack(fixture_scene, planned, RasterioReader())
    water = WaterConfig(
        method="mndwi",
        threshold=-0.1,
        overrides={
            "ramsar-52": WaterSetting(method="ndwi", threshold=0.0, agreement_min=0.9)
        },
    )

    def run(polygon_id: str, cfg: WaterConfig) -> ObservationRow:
        return summarise(
            _poly(polygon_id, fixture_polygon),
            fixture_scene,
            stack,
            planned,
            water=cfg,
            run_id="r",
        )

    overridden = run("ramsar-52", water)
    plain = run("ramsar-53", water)
    assert overridden.water_ha_index == pytest.approx(1125 * PIXEL_AREA_HA)
    assert (
        overridden.water_ha_index
        == run("ramsar-52", WaterConfig(method="ndwi", threshold=0.0)).water_ha_index
    )
    assert plain.water_ha_index == pytest.approx(1936 * PIXEL_AREA_HA)
    assert (
        plain.water_ha_index
        == run("ramsar-53", WaterConfig(method="mndwi", threshold=-0.1)).water_ha_index
    )
    assert overridden.water_ha_index != plain.water_ha_index
    assert overridden.n_clear == plain.n_clear
    assert overridden.water_ha_scl == plain.water_ha_scl
    assert overridden.ndwi_median == plain.ndwi_median
    assert overridden.mndwi_median == plain.mndwi_median


def test_summarise_scl6_override_counts_scl_class_6(
    fixture_scene: SceneItem, fixture_grid: Grid, fixture_polygon: BaseGeometry
) -> None:
    planned = plan_window(fixture_polygon, fixture_grid)
    assert planned is not None
    stack = read_stack(fixture_scene, planned, RasterioReader())
    water = WaterConfig(
        method="ndwi",
        threshold=0.0,
        overrides={"ramsar-15": WaterSetting(method="scl6", agreement_min=0.94)},
    )
    scl_row = summarise(
        _poly("ramsar-15", fixture_polygon),
        fixture_scene,
        stack,
        planned,
        water=water,
        run_id="r",
    )
    assert scl_row.water_ha_index == scl_row.water_ha_scl
    assert scl_row.water_ha_index == pytest.approx(1936 * PIXEL_AREA_HA)
    other = summarise(
        _poly("ramsar-52", fixture_polygon),
        fixture_scene,
        stack,
        planned,
        water=water,
        run_id="r",
    )
    assert other.water_ha_index == pytest.approx(1125 * PIXEL_AREA_HA)


def test_process_scene_applies_overrides_per_polygon(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    rows = process_scene(
        fixture_scene,
        [_poly("ramsar-52", fixture_polygon), _poly("ramsar-53", fixture_polygon)],
        reader=RasterioReader(),
        water=WaterConfig(
            method="mndwi",
            threshold=-0.1,
            overrides={
                "ramsar-52": WaterSetting(
                    method="ndwi", threshold=0.0, agreement_min=0.9
                )
            },
        ),
        operation_epsg=32750,
        run_id="r",
    )
    by_id = {row.polygon_id: row for row in rows}
    assert by_id["ramsar-52"].water_ha_index == pytest.approx(1125 * PIXEL_AREA_HA)
    assert by_id["ramsar-53"].water_ha_index == pytest.approx(1936 * PIXEL_AREA_HA)


def test_water_pixels_respects_clear_and_method() -> None:
    stack = _stack()
    clear = clear_mask(stack.scl, stack.green, stack.red, stack.nir, stack.swir16)
    scl6 = WaterSetting(method="scl6", agreement_min=0.94)
    ndwi_low = WaterSetting(method="ndwi", threshold=0.0, agreement_min=0.9)
    ndwi_high = WaterSetting(method="ndwi", threshold=0.9, agreement_min=0.9)
    mndwi_low = WaterSetting(method="mndwi", threshold=0.0, agreement_min=0.9)
    assert water_pixels(scl6, stack, clear).sum() == 8
    assert (water_pixels(scl6, stack, clear) == (clear & (stack.scl == 6))).all()
    assert water_pixels(ndwi_low, stack, clear).sum() == 8
    assert water_pixels(ndwi_high, stack, clear).sum() == 0
    none = np.zeros_like(clear)
    for setting in (scl6, ndwi_low, mndwi_low):
        assert water_pixels(setting, stack, none).sum() == 0
