from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from rasterio.windows import Window
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from tests.test_live_verify import THOMSONS_4326, THOMSONS_32750
from wetland_change.aoi import AoiPolygon
from wetland_change.catalogue.item import SceneItem, parse_item
from wetland_change.catalogue.search import open_client
from wetland_change.config import WaterConfig, load_config
from wetland_change.raster.read import RasterioReader, read_stack
from wetland_change.stats import rasterise, summarise
from wetland_change.verify import ndvi as ndvi_module
from wetland_change.verify.ndvi import (
    DEA_ARD_COLLECTIONS,
    MATURITY_PREFERENCE,
    NbartItem,
    NbartMetadataError,
    dea_ndvi_median,
    find_nbart_item,
    nbart_reflectance,
    ndvi_correlation_check,
    ndvi_median_check,
    ndvi_scene_check,
    parse_nbart_item,
    same_acquisition,
    select_nbart_item,
)
from wetland_change.verify.wo import dea_reader
from wetland_change.windows import Grid, plan_window

PRODUCT_NAME = "S2C_MSIL1C_20261027T021211_N0513_R060_T50HLK_20261027T061900"
HREF_BASE = (
    "s3://dea-public-data/baseline/ga_s2cm_ard_3/50/HLK/2026/10/27_nrt/"
    "20261027T061900/ga_s2cm_nbart_3-2-1_50HLK_2026-10-27_nrt_"
)


def dea_feature(
    *,
    maturity: str = "nrt",
    product_name: str = PRODUCT_NAME,
    item_id: str = "155b809a-5595-41b4-a1c2-09bd487347c6",
    collection: str = "ga_s2cm_ard_3",
    **band_overrides: Any,
) -> dict[str, Any]:
    raster_band: dict[str, Any] = {
        "nodata": -999,
        "data_type": "int16",
        "unit": "1",
        **band_overrides,
    }

    def asset(band: str) -> dict[str, Any]:
        return {
            "href": f"{HREF_BASE}{band}.tif",
            "proj:code": "EPSG:32750",
            "raster:bands": [dict(raster_band)],
        }

    return {
        "id": item_id,
        "collection": collection,
        "properties": {
            "datetime": "2026-10-27T02:26:39.012923Z",
            "dea:dataset_maturity": maturity,
            "sentinel:product_name": product_name,
            "odc:region_code": "50HLK",
        },
        "assets": {"nbart_red": asset("band04"), "nbart_nir_1": asset("band08")},
    }


def test_median_tolerance_boundaries() -> None:
    red = np.full((4, 5), 1000, np.int16)
    nir = np.full((4, 5), 3000, np.int16)
    clear = np.ones((4, 5), bool)
    check = ndvi_median_check(0.54, red, nir, clear)
    assert check.name == "ndvi_vs_dea_nbart"
    assert check.passed is True
    assert check.measured == pytest.approx(0.04, abs=1e-6)
    assert check.threshold == 0.05
    assert check.detail["dea_ndvi_median"] == pytest.approx(0.5)
    assert ndvi_median_check(0.46, red, nir, clear).passed is True
    assert ndvi_median_check(0.56, red, nir, clear).passed is False
    assert ndvi_median_check(0.44, red, nir, clear).passed is False


def test_dea_nodata_pixels_are_excluded() -> None:
    red = np.array([1000] * 4 + [-999] * 3 + [1000] * 3, np.int16)
    nir = np.array([3000] * 4 + [3000] * 3 + [-999] * 3, np.int16)
    clear = np.ones(10, bool)
    naive = (nir * 1e-4 - red * 1e-4) / (nir * 1e-4 + red * 1e-4)
    # The 3 low and 3 high artefacts straddle the 4 true values, so the median
    # alone would not move; the guard is that scaling -999 gives impossible NDVI.
    assert np.count_nonzero(np.abs(naive) > 1) == 6
    median, n_compared, n_nodata = dea_ndvi_median(red, nir, clear)
    assert median == pytest.approx(0.5)
    assert (n_compared, n_nodata) == (4, 6)
    check = ndvi_median_check(0.54, red, nir, clear)
    assert check.passed is True
    assert check.detail["n_compared"] == 4
    assert check.detail["n_dea_nodata"] == 6


def test_clear_mask_limits_the_pixels() -> None:
    red = np.array([1000, 1000, 1000, 9000, 9000], np.int16)
    nir = np.array([3000, 3000, 3000, 1000, 1000], np.int16)
    clear = np.array([True, True, True, False, False])
    median, n_compared, n_nodata = dea_ndvi_median(red, nir, clear)
    assert median == pytest.approx(0.5)
    assert (n_compared, n_nodata) == (3, 0)


def test_skips_without_comparable_pixels() -> None:
    red = np.full((2, 2), -999, np.int16)
    nir = np.full((2, 2), -999, np.int16)
    clear = np.ones((2, 2), bool)
    empty = ndvi_median_check(0.5, red, nir, clear)
    assert empty.passed is None and empty.measured is None
    assert empty.detail["reason"] == "no clear pixels with DEA data"
    red = np.full((2, 2), 1000, np.int16)
    nir = np.full((2, 2), 3000, np.int16)
    nan = ndvi_median_check(float("nan"), red, nir, clear)
    assert nan.passed is None and nan.measured is None
    assert nan.detail["reason"] == "pipeline ndvi_median is not finite"


def test_nbart_reflectance() -> None:
    out = nbart_reflectance(np.array([1000, -999], np.int16))
    assert out.dtype == np.float32
    assert out[0] == pytest.approx(0.1)
    assert np.isnan(out[1])
    with pytest.raises(TypeError):
        nbart_reflectance(np.array([0.1], np.float32))


PIPELINE = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60]
NOISE = np.array([1, -1, 1, -1, 1, -1])


def test_correlation_threshold() -> None:
    near = ndvi_correlation_check(PIPELINE, list(PIPELINE + 0.04 * NOISE))
    assert near.name == "ndvi_correlation_vs_dea_nbart"
    assert near.passed is True
    assert near.measured == pytest.approx(0.9723, abs=1e-4)
    far = ndvi_correlation_check(PIPELINE, list(PIPELINE + 0.06 * NOISE))
    assert far.passed is False
    assert far.measured == pytest.approx(0.9365, abs=1e-4)


def test_correlation_skips() -> None:
    few = ndvi_correlation_check(PIPELINE[:4], PIPELINE[:4])
    assert few.passed is None and "5" in few.detail["reason"]
    reference = list(PIPELINE)
    reference[2] = float("nan")
    scored = ndvi_correlation_check(PIPELINE, reference)
    assert scored.detail["n_rows"] == 5 and scored.passed is True
    constant = ndvi_correlation_check(PIPELINE, [0.5] * 6)
    assert constant.passed is None
    assert constant.detail["reason"] == "correlation undefined (constant values)"


def test_same_acquisition() -> None:
    uri = "S2C_MSIL2A_20261027T021211_N0513_R060_T50HLK_20261027T071801.SAFE"
    assert same_acquisition(uri, PRODUCT_NAME)
    assert not same_acquisition(uri, PRODUCT_NAME.replace("T50HLK", "T50HLJ"))
    assert not same_acquisition(uri, PRODUCT_NAME.replace("20261027T021211", "x"))
    assert not same_acquisition(uri, PRODUCT_NAME.replace("S2C", "S2A"))
    assert not same_acquisition(uri, PRODUCT_NAME.replace("R060", "R061"))
    assert not same_acquisition(uri, "S2C_MSIL1C")
    assert not same_acquisition("S2C_MSIL2A", PRODUCT_NAME)


def test_parse_nbart_item() -> None:
    item = parse_nbart_item(dea_feature())
    prefix = "https://dea-public-data.s3.ap-southeast-2.amazonaws.com/baseline/"
    assert item.red_href.startswith(prefix) and item.red_href.endswith("band04.tif")
    assert item.nir_href.endswith("band08.tif")
    assert item.epsg == 32750
    assert item.maturity == "nrt" and item.product_name == PRODUCT_NAME
    assert "ga_s2cm_ard_3" in item.reference and "(nrt)" in item.reference
    ok = parse_nbart_item(dea_feature(scale=1e-4, offset=0))
    assert ok.epsg == 32750


@pytest.mark.parametrize(
    "overrides", [{"scale": 0.001}, {"offset": -0.1}, {"nodata": 0}]
)
def test_parse_nbart_item_refuses_unexpected_bands(overrides: dict[str, Any]) -> None:
    with pytest.raises(NbartMetadataError):
        parse_nbart_item(dea_feature(**overrides))


def test_parse_nbart_item_refuses_missing_band_or_epsg() -> None:
    feature = dea_feature()
    del feature["assets"]["nbart_nir_1"]
    with pytest.raises(NbartMetadataError):
        parse_nbart_item(feature)
    feature = dea_feature()
    del feature["assets"]["nbart_red"]["proj:code"]
    with pytest.raises(NbartMetadataError):
        parse_nbart_item(feature)
    feature = dea_feature()
    feature["assets"]["nbart_red"]["proj:code"] = "EPSG:32650"
    with pytest.raises(NbartMetadataError):
        parse_nbart_item(feature)


def test_select_nbart_item(fixture_scene: SceneItem) -> None:
    features = [
        dea_feature(maturity="nrt", item_id="n"),
        dea_feature(maturity="final", item_id="f"),
        dea_feature(
            maturity="final",
            item_id="other",
            product_name=PRODUCT_NAME.replace("T50HLK", "T50HLJ"),
        ),
    ]
    picked = select_nbart_item(fixture_scene, features)
    assert picked is not None and picked.item_id == "f"
    assert select_nbart_item(fixture_scene, [features[2]]) is None
    assert select_nbart_item(fixture_scene, []) is None


def test_find_nbart_item_queries_dea_stac(
    fixture_scene: SceneItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any], float]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "features": [
                    dea_feature(maturity="nrt"),
                    dea_feature(maturity="final", item_id="f"),
                ]
            }

    def fake_post(url: str, *, json: dict[str, Any], timeout: float) -> Response:
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr(ndvi_module.requests, "post", fake_post)
    bbox = (115.0, -32.0, 116.0, -31.0)
    item = find_nbart_item(fixture_scene, bbox)
    assert item is not None and item.item_id == "f"
    url, body, _ = calls[0]
    assert url == "https://explorer.dea.ga.gov.au/stac/search"
    assert body["collections"] == list(DEA_ARD_COLLECTIONS)
    assert body["datetime"] == "2026-10-27T00:00:00Z/2026-10-27T23:59:59Z"
    assert body["bbox"] == list(bbox)


class DictReader:
    def __init__(self, grid: Grid, arrays: dict[str, np.ndarray]) -> None:
        self.grid = grid
        self.arrays = arrays

    def open_grid(self, href: str) -> Grid:
        return self.grid

    def read(self, href: str, window: Window) -> np.ndarray:
        return self.arrays[href]

    def read_overview(self, href: str, factor: int) -> np.ndarray:
        raise AssertionError("unused")

    def read_text(self, href: str) -> str:
        raise AssertionError("unused")


def test_ndvi_scene_check_on_fixture(
    fixture_scene: SceneItem, fixture_grid: Grid, fixture_polygon: BaseGeometry
) -> None:
    reader = RasterioReader()
    planned = plan_window(fixture_polygon, fixture_grid)
    assert planned is not None
    stack = read_stack(fixture_scene, planned, reader)
    inside = rasterise(fixture_polygon, stack.transform, stack.shape)
    row = summarise(
        AoiPolygon("p", "s", "ramsar", fixture_polygon, fixture_polygon),
        fixture_scene,
        stack,
        planned,
        water=WaterConfig(),
        run_id="t",
    )

    def dn(band: np.ndarray) -> np.ndarray:
        return np.where(np.isfinite(band), np.round(band * 1e4), -999).astype(np.int16)

    fake = DictReader(
        fixture_grid, {"red.tif": dn(stack.red), "nir.tif": dn(stack.nir)}
    )
    nbart = NbartItem(
        item_id="dea-1",
        collection="ga_s2cm_ard_3",
        maturity="nrt",
        product_name=PRODUCT_NAME,
        epsg=32750,
        red_href="red.tif",
        nir_href="nir.tif",
    )

    def run(reader_: DictReader, item: NbartItem = nbart) -> Any:
        return ndvi_scene_check(
            fixture_scene,
            stack,
            planned,
            inside,
            measured_median=row.ndvi_median,
            nbart=item,
            reader=reader_,
            scene_grid=fixture_grid,
            expected_epsg=32750,
        )

    check = run(fake)
    assert check.passed is True
    assert check.measured < 1e-3
    assert check.detail["n_compared"] == row.n_clear
    assert check.detail["dea_maturity"] == "nrt"

    wrong_crs = Grid(
        fixture_grid.transform, fixture_grid.width, fixture_grid.height, 32650
    )
    crs = run(DictReader(wrong_crs, fake.arrays))
    assert crs.passed is False and crs.detail["reason"] == "crs differs"
    item_crs = run(fake, dataclasses.replace(nbart, epsg=32650))
    assert item_crs.passed is False and item_crs.detail["reason"] == "crs differs"

    shifted = Grid(
        fixture_grid.transform @ fixture_grid.transform.translation(5, 0),
        fixture_grid.width,
        fixture_grid.height,
        fixture_grid.epsg,
    )
    grid = run(DictReader(shifted, fake.arrays))
    assert grid.passed is False and grid.detail["reason"] == "grid differs"


@pytest.mark.live
def test_ndvi_scores_thomsons_on_newest_pass_with_dea_ard(record_property) -> None:  # type: ignore[no-untyped-def]
    cfg = load_config(Path(__file__).parents[1] / "config" / "pipeline.toml")
    client = open_client(cfg.stac.endpoint)
    end = datetime.now(UTC)
    start = end - timedelta(days=60)
    items = client.search(
        collections=[cfg.stac.collection],
        bbox=list(THOMSONS_4326),
        datetime=(f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}"),
        query={"eo:cloud_cover": {"lt": cfg.stac.cloud_cover_max}},
        sortby=[{"field": "properties.datetime", "direction": "desc"}],
        max_items=40,
    ).items_as_dicts()
    scenes = sorted(
        (
            s
            for s in (
                parse_item(
                    item,
                    collection=cfg.stac.collection,
                    required_assets=cfg.stac.required_assets,
                )
                for item in items
            )
            if s.tile == "50HLK"
        ),
        key=lambda s: s.datetime,
        reverse=True,
    )
    scene = None
    nbart = None
    for candidate in scenes:
        found = find_nbart_item(candidate, THOMSONS_4326)
        if found is not None:
            scene, nbart = candidate, found
            break
    if scene is None or nbart is None:
        pytest.fail(
            f"no 50HLK scene in the last 60 days ({len(scenes)} searched) "
            "has a matching DEA ARD item"
        )

    reader = RasterioReader()
    grid = reader.open_grid(scene.bands["green"].href)
    planned = plan_window(THOMSONS_32750, grid)
    assert planned is not None
    stack = read_stack(scene, planned, reader)
    inside = rasterise(THOMSONS_32750, stack.transform, stack.shape)
    row = summarise(
        AoiPolygon(
            "thomsons-box",
            "Forrestdale & Thomsons Lakes",
            "ramsar",
            THOMSONS_32750,
            box(*THOMSONS_4326),
        ),
        scene,
        stack,
        planned,
        water=cfg.water,
        run_id="live",
    )
    check = ndvi_scene_check(
        scene,
        stack,
        planned,
        inside,
        measured_median=row.ndvi_median,
        nbart=nbart,
        reader=dea_reader(),
        scene_grid=grid,
        expected_epsg=cfg.aoi.operation_epsg,
    )
    record_property(
        "ndvi",
        {
            "scene": scene.item_id,
            "dea_item": nbart.item_id,
            "dea_collection": nbart.collection,
            "dea_maturity": nbart.maturity,
            "ndvi_median": row.ndvi_median,
            "dea_ndvi_median": check.detail.get("dea_ndvi_median"),
            "abs_diff": check.detail.get("abs_diff"),
            "n_compared": check.detail.get("n_compared"),
        },
    )
    print(
        f"{scene.item_id} vs {nbart.collection} {nbart.item_id} ({nbart.maturity}): "
        f"pipeline ndvi_median {row.ndvi_median:.4f}, "
        f"DEA NBART {check.detail['dea_ndvi_median']:.4f}, "
        f"n {check.detail['n_compared']}, passed {check.passed}"
    )
    assert check.passed is True, check.detail
    assert check.detail["n_compared"] > 10000, check.detail
    assert math.isfinite(row.ndvi_median), check.detail
    assert math.isfinite(check.detail["dea_ndvi_median"]), check.detail
    assert check.detail["dea_maturity"] in MATURITY_PREFERENCE, check.detail
