"""Live contract tests against Earth Search, Planetary Computer and DEA.

Run with: uv run pytest -q -m live tests/test_live_verify.py
"""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import box

from tests.conftest import REQUIRED_ASSETS, load_fixture_item
from wetland_change.catalogue.item import parse_item
from wetland_change.config import load_config
from wetland_change.raster.read import RasterioReader, read_stack
from wetland_change.stats import rasterise
from wetland_change.verify.pixels import pixel_check
from wetland_change.verify.scl import scl_checks
from wetland_change.verify.wo import dea_reader, find_wo_href, wo_check
from wetland_change.windows import plan_window

pytestmark = pytest.mark.live

THOMSONS_32750 = box(388400, 6441050, 390800, 6443700)
THOMSONS_4326 = (115.8168, -32.1615, 115.8421, -32.1378)


@pytest.fixture(scope="module")
def remote_scene():  # type: ignore[no-untyped-def]
    return parse_item(
        load_fixture_item(local=False),
        collection="sentinel-2-c1-l2a",
        required_assets=REQUIRED_ASSETS,
    )


def test_scl_shares_match_esa_percentages(remote_scene) -> None:  # type: ignore[no-untyped-def]
    checks = scl_checks(remote_scene, RasterioReader())
    assert all(c.passed for c in checks), [
        (c.name, c.measured, c.reference) for c in checks
    ]


def test_pixels_match_planetary_computer(remote_scene) -> None:  # type: ignore[no-untyped-def]
    reader = RasterioReader()
    planned = plan_window(
        THOMSONS_32750, reader.open_grid(remote_scene.bands["green"].href)
    )
    assert planned is not None
    check = pixel_check(remote_scene, reader, planned.window10)
    if check.passed is None:
        pytest.skip(check.detail["reason"])
    assert check.passed, check.detail


def test_water_agrees_with_dea_wo(remote_scene) -> None:  # type: ignore[no-untyped-def]
    reader = RasterioReader()
    grid = reader.open_grid(remote_scene.bands["green"].href)
    planned = plan_window(THOMSONS_32750, grid)
    assert planned is not None
    wo_href = find_wo_href(remote_scene, THOMSONS_4326)
    assert wo_href is not None
    stack = read_stack(remote_scene, planned, reader)
    inside = rasterise(THOMSONS_32750, stack.transform, stack.shape)
    check = wo_check(
        remote_scene,
        stack,
        planned,
        inside,
        water=load_config(Path(__file__).parents[1] / "config" / "pipeline.toml").water,
        wo_href=wo_href,
        reader=dea_reader(),
    )
    assert check.detail["n_mutually_clear"] > 10000
    assert check.passed, check.detail
