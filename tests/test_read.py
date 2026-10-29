from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from rasterio.windows import Window

from tests.conftest import FIXTURE_DIR
from wetland_change.catalogue.item import SceneItem
from wetland_change.indices import ndwi
from wetland_change.raster.read import (
    BandStack,
    HttpStatusError,
    RasterioReader,
    read_stack,
)
from wetland_change.raster.retry import is_transient_error
from wetland_change.windows import Grid, plan_window


def test_open_grid_reads_fixture_header(fixture_grid: Grid) -> None:
    assert fixture_grid.epsg == 32750
    assert (fixture_grid.width, fixture_grid.height) == (64, 64)
    assert fixture_grid.transform.a == 10
    assert fixture_grid.transform.c % 20 == 0


def test_read_window_returns_uint16(fixture_scene: SceneItem) -> None:
    arr = RasterioReader().read(fixture_scene.bands["green"].href, Window(0, 0, 4, 4))
    assert arr.shape == (4, 4)
    assert arr.dtype == np.uint16


def test_read_overview(fixture_scene: SceneItem) -> None:
    arr = RasterioReader().read_overview(fixture_scene.scl_href, 4)
    assert arr.shape == (8, 8)


def test_read_text_local(fixture_scene: SceneItem) -> None:
    text = RasterioReader().read_text(fixture_scene.product_metadata_href)
    assert "BOA_QUANTIFICATION_VALUE" in text


def test_http_status_error_is_transient_for_5xx_only() -> None:
    assert is_transient_error(HttpStatusError("u", 503))
    assert not is_transient_error(HttpStatusError("u", 404))


def test_read_stack_from_fixture(
    fixture_scene: SceneItem, fixture_grid: Grid, fixture_polygon: Any
) -> None:
    planned = plan_window(fixture_polygon, fixture_grid)
    assert planned is not None
    stack = read_stack(fixture_scene, planned, RasterioReader())
    assert isinstance(stack, BandStack)
    assert stack.shape == (48, 48)
    for band in (stack.green, stack.red, stack.nir, stack.swir16):
        assert band.shape == (48, 48) and band.dtype == np.float32
        finite = band[np.isfinite(band)]
        assert finite.size > 0.99 * band.size
        assert finite.min() >= -0.1 and finite.max() <= 1.5
    assert stack.scl.shape == (48, 48) and stack.scl.dtype == np.uint8
    assert 6 in np.unique(stack.scl)
    assert stack.epsg == 32750
    assert stack.transform == planned.transform10
    water = stack.scl == 6
    assert np.nanmedian(ndwi(stack.green, stack.nir)[water]) > -0.2


class _WrongShapeReader:
    """Returns the SCL window one row short so the stack check must fire."""

    def __init__(self, real: RasterioReader) -> None:
        self._real = real

    def open_grid(self, href: str) -> Grid:
        return self._real.open_grid(href)

    def read(self, href: str, window: Window) -> np.ndarray:
        data = self._real.read(href, window)
        return data[:-1, :] if href.endswith("SCL.tif") else data

    def read_overview(self, href: str, factor: int) -> np.ndarray:
        return self._real.read_overview(href, factor)

    def read_text(self, href: str) -> str:
        return self._real.read_text(href)


def test_read_stack_rejects_shape_mismatch(
    fixture_scene: SceneItem, fixture_grid: Grid, fixture_polygon: Any
) -> None:
    planned = plan_window(fixture_polygon, fixture_grid)
    assert planned is not None
    with pytest.raises(ValueError, match="shape"):
        read_stack(fixture_scene, planned, _WrongShapeReader(RasterioReader()))


def test_fixture_files_present() -> None:
    for name in ("B03.tif", "B04.tif", "B08.tif", "B11.tif", "SCL.tif", "item.json"):
        assert (FIXTURE_DIR / name).exists()
