"""Shared fixtures. The Thomsons fixture item points at the local GeoTIFFs."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from wetland_change.catalogue.item import SceneItem, parse_item
from wetland_change.raster.read import RasterioReader
from wetland_change.windows import Grid

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "thomsons_20261027"
LOCAL_ASSETS = {
    "green": "B03.tif",
    "red": "B04.tif",
    "nir": "B08.tif",
    "swir16": "B11.tif",
    "scl": "SCL.tif",
    "product_metadata": "product_metadata.xml",
}
REQUIRED_ASSETS = ["green", "red", "nir", "swir16", "scl", "product_metadata"]


def load_fixture_item(*, local: bool = True) -> dict[str, Any]:
    """The saved Earth Search item; with `local`, asset hrefs are local paths."""
    item: dict[str, Any] = json.loads((FIXTURE_DIR / "item.json").read_text())
    if local:
        for key, name in LOCAL_ASSETS.items():
            item["assets"][key]["href"] = str(FIXTURE_DIR / name)
    return item


@pytest.fixture
def fixture_item() -> dict[str, Any]:
    return copy.deepcopy(load_fixture_item())


@pytest.fixture
def fixture_scene(fixture_item: dict[str, Any]) -> SceneItem:
    return parse_item(
        fixture_item, collection="sentinel-2-c1-l2a", required_assets=REQUIRED_ASSETS
    )


@pytest.fixture
def fixture_grid(fixture_scene: SceneItem) -> Grid:
    return RasterioReader().open_grid(fixture_scene.bands["green"].href)


@pytest.fixture
def fixture_polygon(fixture_grid: Grid) -> BaseGeometry:
    """A box 100 m inside the fixture extent, in EPSG:32750."""
    minx, miny, maxx, maxy = fixture_grid.bounds
    return box(minx + 100, miny + 100, maxx - 100, maxy - 100)
