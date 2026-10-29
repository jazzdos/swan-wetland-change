import copy
from typing import Any

import pytest

from tests.conftest import REQUIRED_ASSETS
from wetland_change.catalogue.item import ItemGuardError, SceneItem, parse_item

ARGS: dict[str, Any] = {
    "collection": "sentinel-2-c1-l2a",
    "required_assets": REQUIRED_ASSETS,
}


def test_parse_fixture_item(fixture_item: dict[str, Any]) -> None:
    scene = parse_item(fixture_item, **ARGS)
    assert isinstance(scene, SceneItem)
    assert scene.item_id == "S2C_T50HLK_20261027T022351_L2A"
    assert scene.tile == "50HLK"
    assert scene.epsg == 32750
    assert scene.processing_baseline == "05.13"
    assert scene.datetime.tzinfo is not None
    assert scene.created <= scene.updated
    assert scene.bands["green"].scale == pytest.approx(1e-4)
    assert scene.bands["green"].offset == pytest.approx(-0.1)
    assert scene.bands["green"].nodata == 0
    assert scene.bands["swir16"].resolution == 20
    assert scene.product_uri.endswith(".SAFE")
    minx, _, maxx, _ = scene.geometry_4326.bounds
    assert minx < 115.83 < maxx
    assert scene.year == 2026


def test_rejects_other_collection(fixture_item: dict[str, Any]) -> None:
    item = copy.deepcopy(fixture_item)
    item["collection"] = "sentinel-2-l2a"
    with pytest.raises(ItemGuardError, match="collection"):
        parse_item(item, **ARGS)


def test_rejects_offset_applied_flag(fixture_item: dict[str, Any]) -> None:
    item = copy.deepcopy(fixture_item)
    item["properties"]["earthsearch:boa_offset_applied"] = True
    with pytest.raises(ItemGuardError, match="boa_offset_applied"):
        parse_item(item, **ARGS)


def test_rejects_missing_asset(fixture_item: dict[str, Any]) -> None:
    item = copy.deepcopy(fixture_item)
    del item["assets"]["scl"]
    with pytest.raises(ItemGuardError, match="scl"):
        parse_item(item, **ARGS)


def test_rejects_band_without_scale(fixture_item: dict[str, Any]) -> None:
    item = copy.deepcopy(fixture_item)
    del item["assets"]["nir"]["raster:bands"][0]["scale"]
    with pytest.raises(ItemGuardError, match="raster:bands"):
        parse_item(item, **ARGS)


def test_accepts_proj_code_form(fixture_item: dict[str, Any]) -> None:
    item = copy.deepcopy(fixture_item)
    item["properties"].pop("proj:epsg", None)
    item["properties"]["proj:code"] = "EPSG:32750"
    assert parse_item(item, **ARGS).epsg == 32750
