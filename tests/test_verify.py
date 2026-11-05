from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from tests.conftest import FIXTURE_DIR
from wetland_change.catalogue.item import SceneItem
from wetland_change.manifest import manifest_path
from wetland_change.store import OutputStore
from wetland_change.verify.checks import Check, write_report
from wetland_change.verify.pixels import pc_item_id
from wetland_change.verify.scaling import scaling_check
from wetland_change.verify.scl import scl_shares
from wetland_change.verify.wo import (
    WO_EXCLUDE,
    WO_WET,
    pooled_agreement,
    wo_agreement,
    wo_candidates,
    wo_wet_area,
)


def test_scaling_check_passes_on_fixture(fixture_scene: SceneItem) -> None:
    check = scaling_check(
        fixture_scene, (FIXTURE_DIR / "product_metadata.xml").read_text()
    )
    assert check.passed is True
    assert check.name == "reflectance_scaling"
    assert "ESA" in check.reference


def test_scaling_check_fails_on_tampered_xml(fixture_scene: SceneItem) -> None:
    xml = (
        (FIXTURE_DIR / "product_metadata.xml")
        .read_text()
        .replace("BOA_ADD_OFFSET", "BOA_ADD_OFFSET_X")
    )
    check = scaling_check(fixture_scene, xml)
    assert check.passed is False
    assert "BOA_ADD_OFFSET" in check.detail["error"]


def test_scl_shares_ignore_nodata() -> None:
    scl = np.array([[0, 0, 6, 6], [4, 5, 8, 9]], dtype=np.uint8)
    shares = scl_shares(scl)
    assert shares["water"] == 100 * 2 / 6
    assert shares["vegetation"] == 100 * 1 / 6
    assert shares["cloud"] == 100 * 2 / 6


def test_pc_item_id_drops_baseline_token() -> None:
    uri = "S2C_MSIL2A_20261027T021211_N0513_R060_T50HLK_20261027T071801.SAFE"
    assert pc_item_id(uri) == "S2C_MSIL2A_20261027T021211_R060_T50HLK_20261027T071801"


def test_wo_agreement_on_mutually_clear_pixels() -> None:
    water = np.array([[True, True], [False, False]])
    clear = np.array([[True, True], [True, False]])
    wo = np.array([[WO_WET, 0], [0, WO_WET]], dtype=np.uint8)
    agreement, n = wo_agreement(water, clear, wo)
    assert n == 3
    assert agreement == 2 / 3
    wo[0, 1] |= WO_EXCLUDE & 64
    agreement, n = wo_agreement(water, clear, wo)
    assert (agreement, n) == (1.0, 2)


def test_wo_agreement_counts_only_wo_0_and_128_as_clear() -> None:
    clear = np.ones((1, 6), bool)
    wo = np.array([[0, 128, 4, 8, 16, 132]], dtype=np.uint8)
    water = np.array([[False, True, True, True, True, True]])
    agreement, n = wo_agreement(water, clear, wo)
    assert n == 2
    assert agreement == 1.0
    for value in (4, 8, 16, 132, 1, 2, 32, 64):
        agreement, n = wo_agreement(
            np.ones((1, 1), bool),
            np.ones((1, 1), bool),
            np.array([[value]], dtype=np.uint8),
        )
        assert n == 0 and np.isnan(agreement), value
    for value in (0, 128):
        _, n = wo_agreement(
            np.ones((1, 1), bool),
            np.ones((1, 1), bool),
            np.array([[value]], dtype=np.uint8),
        )
        assert n == 1, value


def test_wo_agreement_with_nothing_clear_is_nan() -> None:
    agreement, n = wo_agreement(
        np.zeros((1, 1), bool), np.zeros((1, 1), bool), np.zeros((1, 1), np.uint8)
    )
    assert n == 0 and np.isnan(agreement)


def test_wo_wet_area_on_mutually_clear_pixels() -> None:
    water = np.array([[True, True, False, False], [True, False, False, True]])
    clear = np.array([[True, True, True, True], [True, True, True, False]])
    wo = np.array(
        [[WO_WET, WO_WET, WO_WET, 64], [WO_WET, 1, WO_WET | 4, WO_WET]],
        dtype=np.uint8,
    )
    # Flagged WO pixels (64, 1, 128|4) and the pipeline-unclear pixel drop out
    # of both shares, leaving four mutually clear pixels.
    pipeline_wet, wo_wet, n = wo_wet_area(water, clear, wo)
    assert (pipeline_wet, wo_wet, n) == (3, 4, 4)

    assert wo_wet_area(
        np.zeros((1, 1), bool), np.zeros((1, 1), bool), np.zeros((1, 1), np.uint8)
    ) == (0, 0, 0)


def test_wo_wet_area_gap_is_bounded_by_disagreement() -> None:
    rng = np.random.default_rng(20261105)
    for _ in range(5):
        water = rng.random((40, 40)) < rng.uniform(0.1, 0.9)
        clear = rng.random((40, 40)) < 0.9
        wo = np.where(rng.random((40, 40)) < rng.uniform(0.1, 0.9), WO_WET, 0).astype(
            np.uint8
        )
        wo[rng.random((40, 40)) < 0.1] |= 4
        agreement, n_agree = wo_agreement(water, clear, wo)
        pipeline_wet, wo_wet, n = wo_wet_area(water, clear, wo)
        assert n == n_agree > 0
        assert abs(pipeline_wet - wo_wet) / n <= 1 - agreement + 1e-12


def test_write_report(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "out"))
    checks = [
        Check("a", passed=True, measured=0.99, threshold=0.95, reference="x"),
        Check(
            "b",
            passed=None,
            measured=None,
            threshold=None,
            reference="y",
            detail={"reason": "skipped"},
        ),
    ]
    json_path, md_path = write_report(
        checks,
        store=store,
        run_id="r1",
        docs_dir=tmp_path / "docs",
        generated_at=datetime(2026, 10, 29, tzinfo=UTC),
    )
    payload = json.loads(store.read_bytes(json_path))
    assert payload["run_id"] == "r1"
    assert payload["all_passed"] is True
    assert payload["checks"][1]["passed"] is None
    assert md_path is not None and md_path.exists()
    assert "| a |" in md_path.read_text()


def test_report_marks_an_errored_skip_as_not_all_passed(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "out"))
    ok = Check("a", True, 1.0, 1.0, "r")
    errored = Check("e", None, None, None, "r", {"error": "RuntimeError: down"})
    reason = Check("s", None, None, None, "r", {"reason": "late reference"})
    assert errored.errored and not reason.errored and not ok.errored
    write_report([ok, errored], store=store, run_id="e", docs_dir=None)
    bad = json.loads(store.read_bytes("verification/e.json"))
    assert (bad["all_passed"], bad["n_errored"], bad["n_skipped"]) == (False, 1, 1)
    write_report([ok, reason], store=store, run_id="s", docs_dir=None)
    good = json.loads(store.read_bytes("verification/s.json"))
    assert (good["all_passed"], good["n_errored"], good["n_skipped"]) == (True, 0, 1)


# ---------------------------------------------------------------------------
# Offline coverage of the check branches, verify_run and the verify CLI
# ---------------------------------------------------------------------------

import copy  # noqa: E402
import dataclasses  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
import rasterio  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from rasterio.windows import Window  # noqa: E402
from shapely.geometry.base import BaseGeometry  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from tests.test_pipeline import NOW, FakeClient, _config, _polygons, _run  # noqa: E402
from wetland_change import cli  # noqa: E402
from wetland_change.config import (  # noqa: E402
    PipelineConfig,
    VerifyConfig,
    WaterConfig,
    WaterSetting,
)
from wetland_change.mask import clear_mask  # noqa: E402
from wetland_change.outputs.geoparquet import (  # noqa: E402
    observation_path,
    read_observations,
)
from wetland_change.raster.read import RasterioReader, read_stack  # noqa: E402
from wetland_change.stats import rasterise, water_pixels  # noqa: E402
from wetland_change.verify.ndvi import NbartItem  # noqa: E402
from wetland_change.verify.run import (  # noqa: E402
    ManifestReadError,
    latest_run_id,
    scenes_for_run,
    stored_ndvi,
    verify_run,
)
from wetland_change.verify.scl import scl_checks  # noqa: E402
from wetland_change.verify.wo import WET_AREA_MAX_PP, wo_check  # noqa: E402
from wetland_change.windows import Grid, plan_window  # noqa: E402


class FakeReader:
    """Serves canned arrays; `grid` answers open_grid for every href."""

    def __init__(
        self,
        *,
        overview: np.ndarray | None = None,
        data: np.ndarray | None = None,
        grid: Grid | None = None,
        text: str = "",
    ) -> None:
        self.overview = overview
        self.data = data
        self.grid = grid
        self.text = text

    def open_grid(self, href: str) -> Grid:
        assert self.grid is not None
        return self.grid

    def read(self, href: str, window: Window) -> np.ndarray:
        assert self.data is not None
        return self.data

    def read_overview(self, href: str, factor: int) -> np.ndarray:
        assert self.overview is not None
        return self.overview

    def read_text(self, href: str) -> str:
        return self.text


def _with_properties(scene: SceneItem, **props: Any) -> SceneItem:
    raw = copy.deepcopy(scene.raw)
    for key, value in props.items():
        if value is None:
            raw["properties"].pop(key, None)
        else:
            raw["properties"][key] = value
    return dataclasses.replace(scene, raw=raw)


def test_report_is_strict_json_and_empty_run_does_not_pass(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "out"))
    nan = float("nan")
    checks = [Check("a", True, nan, 0.95, "x", {"scl_agreement": nan, "n": [nan]})]
    json_path, md_path = write_report(
        checks, store=store, run_id="r", docs_dir=tmp_path
    )
    raw = store.read_bytes(json_path).decode()
    assert "NaN" not in raw
    payload = json.loads(raw)
    assert payload["checks"][0]["measured"] is None
    assert payload["checks"][0]["detail"] == {"scl_agreement": None, "n": [None]}
    assert md_path is not None and "nan" not in md_path.read_text()
    write_report([], store=store, run_id="e", docs_dir=None)
    empty = json.loads(store.read_bytes("verification/e.json"))
    assert empty["all_passed"] is False
    assert (empty["n_scored"], empty["n_skipped"]) == (0, 0)
    write_report(
        [Check("s", None, None, None, "y")], store=store, run_id="s", docs_dir=None
    )
    skipped = json.loads(store.read_bytes("verification/s.json"))
    assert (skipped["all_passed"], skipped["n_skipped"]) == (False, 1)


def test_scl_checks_pass_fail_and_missing_property(
    fixture_scene: SceneItem, fixture_grid: Grid
) -> None:
    water = _with_properties(
        fixture_scene,
        **{
            "s2:water_percentage": 100.0,
            "s2:vegetation_percentage": None,
            "s2:not_vegetated_percentage": 50.0,
            "eo:cloud_cover": 0.0,
        },
    )
    reader = FakeReader(data=np.full((4, 4), 6, np.uint8), grid=fixture_grid)
    checks = {c.name: c for c in scl_checks(water, reader)}
    assert checks["scl_share_water"].passed is True
    assert checks["scl_share_vegetation"].passed is None
    assert checks["scl_share_not_vegetated"].passed is False
    assert checks["scl_share_cloud"].passed is True


def test_scl_checks_skip_when_scl_has_no_valid_pixels(
    fixture_scene: SceneItem, fixture_grid: Grid
) -> None:
    reader = FakeReader(data=np.zeros((4, 4), np.uint8), grid=fixture_grid)
    checks = scl_checks(fixture_scene, reader)
    assert checks and all(c.passed is None for c in checks)


def test_scl_checks_use_full_resolution_not_mode_overviews(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    """Mode-built overviews bias class shares; the check must not read them."""
    scl = np.full((64, 64), 4, dtype=np.uint8)
    scl[1::2, 1::2] = 5  # every 2x2 block is three vegetation, one not_vegetated
    path = tmp_path / "SCL.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=1,
        dtype="uint8",
        nodata=0,
        crs="EPSG:32750",
        transform=from_origin(389300.0, 6442720.0, 20.0, 20.0),
    ) as dst:
        dst.write(scl, 1)
    with rasterio.open(path, "r+") as dst:
        dst.build_overviews([2, 4, 8, 16], Resampling.mode)
        dst.update_tags(ns="rio_overview", resampling="mode")
    with rasterio.open(path) as src:
        # Guard: the 1/16 overview of this file is pure class 4, so an overview
        # read would measure vegetation 100 instead of 75.
        assert np.all(src.read(1, out_shape=(4, 4)) == 4)
    scene = dataclasses.replace(
        _with_properties(
            fixture_scene,
            **{
                "s2:vegetation_percentage": 75.0,
                "s2:not_vegetated_percentage": 25.0,
                "s2:water_percentage": 0.0,
                "eo:cloud_cover": 0.0,
            },
        ),
        scl_href=str(path),
    )
    checks = {c.name: c for c in scl_checks(scene, RasterioReader())}
    assert checks["scl_share_vegetation"].measured == pytest.approx(75.0)
    assert checks["scl_share_not_vegetated"].measured == pytest.approx(25.0)
    assert all(c.passed is True for c in checks.values()), checks


def _stack_and_window(
    scene: SceneItem, polygon: BaseGeometry
) -> tuple[Any, Any, np.ndarray, Grid]:
    reader = RasterioReader()
    grid = reader.open_grid(scene.bands["green"].href)
    planned = plan_window(polygon, grid)
    assert planned is not None
    stack = read_stack(scene, planned, reader)
    inside = rasterise(polygon, stack.transform, stack.shape)
    return stack, planned, inside, grid


def test_wo_check_branches(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    shape = stack.shape

    def run(reader: FakeReader) -> Check:
        return wo_check(
            fixture_scene,
            stack,
            planned,
            inside,
            water=WaterConfig(agreement_min=0.5),
            wo_href="wo.tif",
            reader=reader,
            scene_grid=grid,
        )

    shifted = Grid(
        transform=grid.transform * grid.transform.translation(5, 0),
        width=grid.width,
        height=grid.height,
        epsg=grid.epsg,
    )
    differs = run(FakeReader(grid=shifted, data=np.zeros(shape, np.uint8)))
    assert differs.passed is False and differs.detail["reason"] == "grid differs"

    nothing_clear = run(FakeReader(grid=grid, data=np.full(shape, 1, np.uint8)))
    assert nothing_clear.passed is None
    assert nothing_clear.measured is None
    assert nothing_clear.detail["n_mutually_clear"] == 0

    # WO equal to the pipeline's own water, so agreement and wet area both hold.
    clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
    own = water_pixels(WaterConfig(agreement_min=0.5).for_polygon(None), stack, clear)
    wet = run(FakeReader(grid=grid, data=np.where(own, WO_WET, 0).astype(np.uint8)))
    assert wet.detail["n_mutually_clear"] > 0
    assert wet.passed is True
    assert wet.detail["wet_area_diff_pp"] == 0
    dry = run(FakeReader(grid=grid, data=np.zeros(shape, np.uint8)))
    assert dry.passed is False


def _wo_with_clear_count(
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    n_clear: int,
    **kwargs: Any,
) -> Check:
    """wo_check where WO is clear and dry on exactly `n_clear` pixels.

    The pipeline pixel is clear and wet there (agreement_min 0.5), so every
    mutually clear pixel disagrees.
    """
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
    water = WaterConfig(agreement_min=0.5)
    wet = water_pixels(water.for_polygon(None), stack, clear) & clear
    rows, cols = np.nonzero(wet)
    assert rows.size >= n_clear
    data = np.full(stack.shape, 1, np.uint8)
    data[rows[:n_clear], cols[:n_clear]] = 0
    return wo_check(
        fixture_scene,
        stack,
        planned,
        inside,
        water=water,
        wo_href="wo.tif",
        reader=FakeReader(grid=grid, data=data),
        scene_grid=grid,
        **kwargs,
    )


def test_wo_check_one_disagreeing_pixel_fails_under_the_default_floor(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    result = _wo_with_clear_count(fixture_scene, fixture_polygon, 1)
    assert result.detail["n_mutually_clear"] == 1
    assert result.passed is False
    assert result.measured == 0.0


def test_wo_check_below_min_clear_pixels_is_a_reason_skip(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    result = _wo_with_clear_count(fixture_scene, fixture_polygon, 1, min_clear_pixels=2)
    assert result.passed is None
    assert result.measured is None
    assert result.threshold == 0.5
    assert result.reference == "wo.tif"
    assert result.detail["n_mutually_clear"] == 1
    assert result.detail["min_clear_pixels"] == 2
    assert result.detail["reason"] == "fewer than 2 mutually clear pixels"
    assert result.detail["item"] == fixture_scene.item_id
    assert result.errored is False


def test_wo_check_count_equal_to_the_floor_is_scored(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    result = _wo_with_clear_count(fixture_scene, fixture_polygon, 2, min_clear_pixels=2)
    assert result.detail["n_mutually_clear"] == 2
    assert result.passed is False
    assert result.measured == 0.0
    assert "reason" not in result.detail


def test_wo_check_zero_clear_pixels_unchanged_with_a_floor(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    result = _wo_with_clear_count(
        fixture_scene, fixture_polygon, 0, min_clear_pixels=100
    )
    assert result.passed is None and result.measured is None
    assert result.detail["n_mutually_clear"] == 0
    assert "reason" not in result.detail


def test_pooled_agreement_ignores_floor_skipped_checks(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    skipped = _wo_with_clear_count(
        fixture_scene, fixture_polygon, 1, min_clear_pixels=2
    )
    assert pooled_agreement([skipped]) is None


def _wo_with(
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    water: WaterConfig,
    *,
    polygon_id: str | None = None,
    shift: bool = False,
) -> Check:
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    reader_grid = grid
    if shift:
        reader_grid = Grid(
            transform=grid.transform * grid.transform.translation(5, 0),
            width=grid.width,
            height=grid.height,
            epsg=grid.epsg,
        )
    reader = FakeReader(grid=reader_grid, data=np.full(stack.shape, WO_WET, np.uint8))
    return wo_check(
        fixture_scene,
        stack,
        planned,
        inside,
        water=water,
        wo_href="wo.tif",
        reader=reader,
        scene_grid=grid,
        polygon_id=polygon_id,
    )


def test_wo_check_scores_each_polygon_with_its_own_setting(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    water = WaterConfig(
        method="mndwi",
        threshold=-0.1,
        agreement_min=0.5,
        overrides={
            "ramsar-52": WaterSetting(method="ndwi", threshold=0.0, agreement_min=0.9)
        },
    )
    over = _wo_with(fixture_scene, fixture_polygon, water, polygon_id="ramsar-52")
    assert over.measured == pytest.approx(1125 / 1936)
    assert over.threshold == 0.9
    assert over.passed is False
    assert over.reference == "wo.tif"
    assert over.detail["method"] == "ndwi"
    assert over.detail["threshold"] == 0.0
    assert over.detail["agreement_min"] == 0.9
    assert over.detail["override"] is True
    assert over.detail["polygon_id"] == "ramsar-52"

    other = _wo_with(fixture_scene, fixture_polygon, water, polygon_id="ramsar-53")
    assert other.measured == 1.0
    assert other.threshold == 0.5
    assert other.passed is True
    assert other.detail["wet_area_diff_pp"] == 0
    assert other.reference == "wo.tif"
    assert other.detail["method"] == "mndwi"
    assert other.detail["override"] is False

    glob = _wo_with(fixture_scene, fixture_polygon, water)
    assert glob.threshold == other.threshold
    assert glob.measured == other.measured
    assert glob.reference == "wo.tif"
    assert "polygon_id" not in glob.detail


def _wo_flipped(
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    water: WaterConfig,
    *,
    polygon_id: str,
    dry_to_wet: int = 0,
    wet_to_dry: int = 0,
) -> Check:
    """wo_check against a WO array equal to the pipeline's own water, with
    clear pixels flipped so the agreement and the wet-area gap are known."""
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
    pipeline = water_pixels(water.for_polygon(polygon_id), stack, clear)
    wo = np.where(pipeline, WO_WET, 0).astype(np.uint8)
    dry = np.flatnonzero(clear & ~pipeline)
    wet = np.flatnonzero(clear & pipeline)
    assert len(dry) >= dry_to_wet and len(wet) >= wet_to_dry
    wo.flat[dry[:dry_to_wet]] = WO_WET
    wo.flat[wet[:wet_to_dry]] = 0
    return wo_check(
        fixture_scene,
        stack,
        planned,
        inside,
        water=water,
        wo_href="wo.tif",
        reader=FakeReader(grid=grid, data=wo),
        scene_grid=grid,
        polygon_id=polygon_id,
    )


def _ndwi_water(agreement_min: float = 0.9) -> WaterConfig:
    return WaterConfig(
        overrides={
            "ramsar-52": WaterSetting(
                method="ndwi", threshold=0.0, agreement_min=agreement_min
            )
        }
    )


def test_wo_check_fails_on_wet_area_even_when_agreement_passes(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    result = _wo_flipped(
        fixture_scene,
        fixture_polygon,
        _ndwi_water(0.9),
        polygon_id="ramsar-52",
        dry_to_wet=136,
    )
    n = result.detail["n_mutually_clear"]
    assert result.measured == pytest.approx(1 - 136 / n)
    assert result.measured is not None and result.measured > 0.9
    assert result.threshold == 0.9
    assert result.passed is False
    assert result.detail["wet_area_passed"] is False
    assert result.detail["wet_area_diff_pp"] == pytest.approx(-100 * 136 / n)
    assert result.detail["wet_area_diff_pp"] < -5
    assert result.detail["wet_area_max_pp"] == 5.0 == WET_AREA_MAX_PP
    gap = result.detail["wet_area_wo"] - result.detail["wet_area_pipeline"]
    assert gap == pytest.approx(136 / n)


def test_wo_check_fails_on_wet_area_when_wo_is_drier(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    result = _wo_flipped(
        fixture_scene,
        fixture_polygon,
        _ndwi_water(0.9),
        polygon_id="ramsar-52",
        wet_to_dry=136,
    )
    n = result.detail["n_mutually_clear"]
    assert result.measured is not None and result.measured > 0.9
    assert result.passed is False
    assert result.detail["wet_area_passed"] is False
    assert result.detail["wet_area_diff_pp"] == pytest.approx(100 * 136 / n)


def test_wo_check_passes_when_wet_area_within_5pp(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    result = _wo_flipped(
        fixture_scene,
        fixture_polygon,
        _ndwi_water(0.9),
        polygon_id="ramsar-52",
        dry_to_wet=40,
    )
    n = result.detail["n_mutually_clear"]
    assert result.measured is not None and result.measured > 0.9
    assert result.passed is True
    assert result.detail["wet_area_passed"] is True
    assert result.detail["wet_area_diff_pp"] == pytest.approx(-100 * 40 / n)
    assert result.detail["wet_area_max_pp"] == 5.0


@pytest.mark.parametrize(("pipeline_wet", "expected"), [(11, True), (12, False)])
def test_wo_check_wet_area_limit_is_exact_at_5pp(
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    pipeline_wet: int,
    expected: bool,
) -> None:
    # 20 mutually clear pixels and 10 WO-wet. 11 pipeline-wet is exactly 5 pp
    # (agreement 0.95) and passes; 12 is 10 pp and fails. Float shares gave
    # 5.000000000000004 at the limit.
    water = _ndwi_water(0.5 if not expected else 0.95)
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
    pipeline = water_pixels(water.for_polygon("ramsar-52"), stack, clear)
    wet = np.flatnonzero(clear & pipeline)[:pipeline_wet]
    dry = np.flatnonzero(clear & ~pipeline)[: 20 - pipeline_wet]
    assert len(wet) == pipeline_wet and len(dry) == 20 - pipeline_wet
    small = np.zeros(inside.shape, bool)
    small.flat[np.concatenate([wet, dry])] = True
    wo = np.zeros(inside.shape, np.uint8)
    wo.flat[wet[:10]] = WO_WET
    result = wo_check(
        fixture_scene,
        stack,
        planned,
        small,
        water=water,
        wo_href="wo.tif",
        reader=FakeReader(grid=grid, data=wo),
        scene_grid=grid,
        polygon_id="ramsar-52",
    )
    assert result.detail["n_mutually_clear"] == 20
    assert result.detail["wet_area_diff_pp"] == (5.0 if expected else 10.0)
    assert result.detail["wet_area_passed"] is expected
    assert result.passed is expected


@pytest.mark.parametrize(("agreement_min", "expected"), [(0.55, True), (0.60, False)])
def test_wo_check_agreement_min_alone_decides_pass(
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    agreement_min: float,
    expected: bool,
) -> None:
    # Equal flips each way keep the wet-area gap at zero, so only the
    # agreement floor can decide.
    result = _wo_flipped(
        fixture_scene,
        fixture_polygon,
        _ndwi_water(agreement_min),
        polygon_id="ramsar-52",
        dry_to_wet=406,
        wet_to_dry=406,
    )
    n = result.detail["n_mutually_clear"]
    assert result.passed is expected
    assert result.threshold == agreement_min
    assert result.measured == pytest.approx(1 - 812 / n)
    assert result.detail["wet_area_diff_pp"] == pytest.approx(0.0)
    assert result.detail["wet_area_passed"] is True


def test_wo_check_scl6_override_scores_scl_class_6(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    water = WaterConfig(
        method="ndwi",
        threshold=0.0,
        overrides={"ramsar-15": WaterSetting(method="scl6", agreement_min=0.94)},
    )
    scl = _wo_with(fixture_scene, fixture_polygon, water, polygon_id="ramsar-15")
    assert scl.measured == scl.detail["scl_agreement"] == 1.0
    assert scl.detail["threshold"] is None
    assert scl.threshold == 0.94
    assert scl.passed is True
    assert scl.detail["wet_area_diff_pp"] == 0

    index = _wo_with(fixture_scene, fixture_polygon, water, polygon_id="ramsar-52")
    assert index.measured == pytest.approx(1125 / 1936)


def test_wo_check_grid_differs_reports_the_polygon_agreement_min(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    water = WaterConfig(
        overrides={"ramsar-52": WaterSetting(method="scl6", agreement_min=0.97)}
    )
    result = _wo_with(
        fixture_scene, fixture_polygon, water, polygon_id="ramsar-52", shift=True
    )
    assert result.passed is False
    assert result.threshold == 0.97
    assert result.detail["reason"] == "grid differs"
    assert result.detail["polygon_id"] == "ramsar-52"


def _built_run(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> tuple[PipelineConfig, OutputStore, str, list[Any]]:
    polygons = _polygons(fixture_polygon)
    manifest = _run(tmp_path, FakeClient([fixture_item]), polygons, NOW)
    cfg = _config(tmp_path)
    return cfg, OutputStore(cfg.output.root), manifest.run_id, polygons


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(endpoint: str) -> Any:
        raise RuntimeError("network disabled in offline tests")

    def refuse_lookup(scene: SceneItem, bbox: Any) -> Any:
        raise RuntimeError("network disabled in offline tests")

    monkeypatch.setattr("wetland_change.verify.run.open_client", refuse)
    monkeypatch.setattr("wetland_change.verify.run.find_nbart_item", refuse_lookup)


def test_scenes_for_run_and_latest_run_id(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, _ = _built_run(fixture_item, fixture_polygon, tmp_path)
    scenes = scenes_for_run(cfg, store, run_id)
    assert [s.item_id for s in scenes] == [fixture_item["id"]]
    assert scenes_for_run(cfg, store, "nope") == []
    assert latest_run_id(store) == run_id
    store.write_bytes("runs/99991231T000000Z.json", b'{"processed": 0}')
    assert latest_run_id(store) == run_id
    assert latest_run_id(OutputStore(str(tmp_path / "empty"))) is None


def test_latest_run_id_raises_on_manifest_oserror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path / "store"))
    store.write_bytes("runs/20261029T100000Z.json", b'{"processed": 1}')
    store.write_bytes("runs/20261030T100000Z.json", b'{"processed": 1}')
    original = OutputStore.read_bytes

    def flaky(self: OutputStore, relpath: str) -> bytes:
        if relpath == "runs/20261030T100000Z.json":
            raise PermissionError("denied")
        return original(self, relpath)

    monkeypatch.setattr(OutputStore, "read_bytes", flaky)
    with pytest.raises(ManifestReadError) as excinfo:
        latest_run_id(store)
    assert "runs/20261030T100000Z.json" in str(excinfo.value)


def test_latest_run_id_skips_a_malformed_manifest(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "store"))
    store.write_bytes("runs/20261029T100000Z.json", b'{"processed": 1}')
    store.write_bytes("runs/20261030T100000Z.json", b"not json")
    assert latest_run_id(store) == "20261029T100000Z"


def test_latest_run_id_skips_a_newer_backfill_manifest(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "store"))
    store.write_bytes("runs/20261029T100000Z.json", b'{"processed": 1, "kind": "run"}')
    store.write_bytes(
        "runs/20261030T100000Z.json", b'{"processed": 40, "kind": "backfill"}'
    )
    assert latest_run_id(store) == "20261029T100000Z"


def test_latest_run_id_treats_a_manifest_without_kind_as_a_run(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path / "store"))
    store.write_bytes("runs/20261029T100000Z.json", b'{"processed": 1}')
    store.write_bytes(
        "runs/20261030T100000Z.json", b'{"processed": 5, "kind": "backfill"}'
    )
    assert latest_run_id(store) == "20261029T100000Z"


def test_latest_run_id_returns_none_when_only_backfills_processed(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path / "store"))
    store.write_bytes(
        "runs/20261030T100000Z.json", b'{"processed": 3, "kind": "backfill"}'
    )
    assert latest_run_id(store) is None


def test_verify_run_with_injected_dependencies(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    lookups: list[str] = []
    grid = RasterioReader().open_grid(fixture_item["assets"]["green"]["href"])

    def lookup(scene: SceneItem, bbox: Any) -> str | None:
        lookups.append(scene.item_id)
        return "wo.tif"

    def pixel(scene: SceneItem, reader: Any, window: Window) -> Check:
        return Check("pixels_vs_planetary_computer", True, 1.0, 1.0, "fake")

    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        wo_lookup=lookup,
        wo_reader_factory=lambda: FakeReader(
            grid=grid, data=np.full((48, 48), WO_WET, np.uint8)
        ),
        pixel_checker=pixel,
        docs_dir=None,
    )
    names = [c.name for c in checks]
    assert names.count("reflectance_scaling") == 1
    assert names.count("water_vs_dea_s2_wo") == 1  # the off-scene polygon is skipped
    assert "pixels_vs_planetary_computer" in names
    assert lookups == [fixture_item["id"]]
    report = json.loads(store.read_bytes(f"verification/{run_id}.json"))
    assert report["n_scored"] > 0
    wo = next(c for c in checks if c.name == "water_vs_dea_s2_wo")
    assert wo.passed is not None and wo.detail["polygon_id"] == "ramsar-52"


def test_verify_run_scores_wo_with_the_polygon_override(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    cfg = cfg.model_copy(
        update={
            "water": WaterConfig(
                overrides={"ramsar-52": WaterSetting(method="scl6", agreement_min=0.97)}
            )
        }
    )
    grid = RasterioReader().open_grid(fixture_item["assets"]["green"]["href"])
    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        wo_lookup=lambda s, b: "wo.tif",
        wo_reader_factory=lambda: FakeReader(
            grid=grid, data=np.full((48, 48), WO_WET, np.uint8)
        ),
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        docs_dir=None,
    )
    (wo,) = [c for c in checks if c.name == "water_vs_dea_s2_wo"]
    assert wo.threshold == 0.97
    assert wo.detail["method"] == "scl6"
    assert wo.detail["polygon_id"] == "ramsar-52"
    assert wo.detail["override"] is True
    assert wo.measured == 1.0
    assert wo.passed is True


def test_verify_run_turns_exceptions_into_skipped_checks(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)

    def boom(scene: SceneItem, bbox: Any) -> str | None:
        raise RuntimeError("DEA is down")

    def pixel_boom(scene: SceneItem, reader: Any, window: Window) -> Check:
        raise RuntimeError("PC is down")

    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        wo_lookup=boom,
        pixel_checker=pixel_boom,
        docs_dir=None,
    )
    errors = {c.name: c.detail["error"] for c in checks if "error" in c.detail}
    assert errors["water_vs_dea_s2_wo"] == "RuntimeError: DEA is down"
    assert errors["pixels_vs_planetary_computer"] == "RuntimeError: PC is down"
    assert store.exists(f"verification/{run_id}.json")
    report = json.loads(store.read_bytes(f"verification/{run_id}.json"))
    assert report["all_passed"] is False
    assert report["n_errored"] >= 2


def test_verify_run_does_not_look_up_wo_without_overlap(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)

    def never(scene: SceneItem, bbox: Any) -> str | None:
        raise AssertionError("no polygon overlaps, so no lookup")

    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons[1:],
        wo_lookup=never,
        docs_dir=None,
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
    )
    assert "water_vs_dea_s2_wo" not in [c.name for c in checks]


class DictReader:
    """Serves arrays by href; `grid` answers open_grid for every href."""

    def __init__(self, *, grid: Grid, arrays: dict[str, np.ndarray]) -> None:
        self.grid = grid
        self.arrays = arrays

    def open_grid(self, href: str) -> Grid:
        return self.grid

    def read(self, href: str, window: Window) -> np.ndarray:
        return self.arrays[href]

    def read_overview(self, href: str, factor: int) -> np.ndarray:
        raise NotImplementedError

    def read_text(self, href: str) -> str:
        raise NotImplementedError


def _nbart_item() -> NbartItem:
    return NbartItem(
        "dea-1", "ga_s2cm_ard_3", "nrt", "S2C_MSIL1C_x", 32750, "red.tif", "nir.tif"
    )


def _dea_dn(stack: Any, band: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(band), np.round(band * 1e4), -999).astype(np.int16)


def _ndvi_run(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    **overrides: Any,
) -> tuple[list[Check], OutputStore, str]:
    min_clear_pixels = overrides.pop("min_clear_pixels", None)
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    if min_clear_pixels is not None:
        cfg = cfg.model_copy(
            update={"verify": VerifyConfig(min_clear_pixels=min_clear_pixels)}
        )
    scene = scenes_for_run(cfg, store, run_id)[0]
    stack, _, _, grid = _stack_and_window(scene, fixture_polygon)
    arrays = {
        "red.tif": _dea_dn(stack, stack.red),
        "nir.tif": _dea_dn(stack, stack.nir),
    }
    kwargs: dict[str, Any] = {
        "nbart_lookup": lambda s, b: _nbart_item(),
        "nbart_reader_factory": lambda: DictReader(grid=grid, arrays=arrays),
        "wo_lookup": lambda s, b: None,
        "pixel_checker": lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        "docs_dir": None,
    }
    kwargs.update(overrides)
    checks = verify_run(cfg, store, run_id, polygons=polygons, **kwargs)
    return checks, store, run_id


def test_verify_run_scores_ndvi_against_injected_nbart_item(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    checks, store, run_id = _ndvi_run(fixture_item, fixture_polygon, tmp_path)
    ndvi = [c for c in checks if c.name == "ndvi_vs_dea_nbart"]
    assert len(ndvi) == 1  # the off-scene polygon is skipped
    assert ndvi[0].passed is True
    assert ndvi[0].detail["polygon_id"] == "ramsar-52"
    observed = read_observations(store)
    stored = float(
        observed.loc[observed["polygon_id"] == "ramsar-52", "ndvi_median"].iloc[0]
    )
    assert ndvi[0].detail["ndvi_median"] == pytest.approx(stored)
    assert abs(ndvi[0].detail["dea_ndvi_median"] - ndvi[0].detail["ndvi_median"]) < 1e-3
    corr = [c for c in checks if c.name == "ndvi_correlation_vs_dea_nbart"]
    assert len(corr) == 1 and corr[0].passed is None
    report = json.loads(store.read_bytes(f"verification/{run_id}.json"))
    names = {c["name"] for c in report["checks"]}
    assert {"ndvi_vs_dea_nbart", "ndvi_correlation_vs_dea_nbart"} <= names


def test_verify_run_excludes_a_floor_skipped_ndvi_row_from_the_correlation(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    checks, _, _ = _ndvi_run(
        fixture_item, fixture_polygon, tmp_path, min_clear_pixels=10_000_000
    )
    ndvi = [c for c in checks if c.name == "ndvi_vs_dea_nbart"]
    assert len(ndvi) == 1
    assert ndvi[0].passed is None and ndvi[0].errored is False
    assert ndvi[0].detail["reason"].startswith("fewer than 10000000 compared")
    corr = [c for c in checks if c.name == "ndvi_correlation_vs_dea_nbart"]
    assert len(corr) == 1
    assert corr[0].detail["rows"] == []
    assert corr[0].detail["n_rows"] == 0


def test_verify_run_correlation_is_skipped_not_errored_on_a_mismatched_grid(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    probe = tmp_path / "probe"
    probe.mkdir()
    cfg, store, run_id, _ = _built_run(fixture_item, fixture_polygon, probe)
    scene = scenes_for_run(cfg, store, run_id)[0]
    _, _, _, grid = _stack_and_window(scene, fixture_polygon)
    wrong = dataclasses.replace(grid, epsg=grid.epsg + 1)
    checks, _, _ = _ndvi_run(
        fixture_item,
        fixture_polygon,
        tmp_path,
        nbart_reader_factory=lambda: DictReader(grid=wrong, arrays={}),
    )
    ndvi = [c for c in checks if c.name == "ndvi_vs_dea_nbart"]
    assert len(ndvi) == 1
    assert ndvi[0].passed is False
    assert ndvi[0].detail["reason"] == "crs differs"
    corr = [c for c in checks if c.name == "ndvi_correlation_vs_dea_nbart"]
    assert len(corr) == 1
    assert corr[0].passed is None
    assert "error" not in corr[0].detail, corr[0].detail


def test_verify_run_ndvi_skips_when_dea_has_no_item(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    checks, _, _ = _ndvi_run(
        fixture_item, fixture_polygon, tmp_path, nbart_lookup=lambda s, b: None
    )
    ndvi = [c for c in checks if c.name == "ndvi_vs_dea_nbart"]
    assert len(ndvi) == 1
    assert ndvi[0].passed is None
    assert ndvi[0].detail["reason"] == "no DEA ARD item for this acquisition"


def test_verify_run_default_nbart_lookup_is_offline(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        wo_lookup=lambda s, b: None,
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        docs_dir=None,
    )
    ndvi = [c for c in checks if c.name == "ndvi_vs_dea_nbart"]
    assert len(ndvi) == 1
    assert ndvi[0].detail["error"] == "RuntimeError: network disabled in offline tests"


def test_verify_run_ndvi_skips_when_observation_file_is_missing(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    for path in store.list_files("observations"):
        store.delete(path)
    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        nbart_lookup=lambda s, b: _nbart_item(),
        nbart_reader_factory=lambda: DictReader(
            grid=RasterioReader().open_grid(fixture_item["assets"]["green"]["href"]),
            arrays={},
        ),
        wo_lookup=lambda s, b: None,
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        docs_dir=None,
    )
    ndvi = [c for c in checks if c.name == "ndvi_vs_dea_nbart"]
    assert len(ndvi) == 1
    assert ndvi[0].passed is None
    assert ndvi[0].detail["reason"] == "no observation row for this polygon"


def test_verify_run_reads_the_stack_once_for_wo_and_ndvi(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    red_href = fixture_item["assets"]["red"]["href"]
    reads: list[str] = []

    class CountingReader(RasterioReader):
        def read(self, href: str, window: Window) -> np.ndarray:
            reads.append(href)
            return super().read(href, window)

    grid = RasterioReader().open_grid(fixture_item["assets"]["green"]["href"])
    checks, _, _ = _ndvi_run(
        fixture_item,
        fixture_polygon,
        tmp_path,
        reader=CountingReader(),
        wo_lookup=lambda s, b: "wo.tif",
        wo_reader_factory=lambda: FakeReader(
            grid=grid, data=np.full((48, 48), WO_WET, np.uint8)
        ),
    )
    assert any(c.name == "water_vs_dea_s2_wo" and c.passed is not None for c in checks)
    assert any(c.name == "ndvi_vs_dea_nbart" and c.passed is not None for c in checks)
    assert reads.count(red_href) == 1


def test_stored_ndvi_reads_the_scene_observation_file(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, _ = _built_run(fixture_item, fixture_polygon, tmp_path)
    scene = scenes_for_run(cfg, store, run_id)[0]
    values = stored_ndvi(store, scene)
    assert set(values) == {"ramsar-52"}
    assert np.isfinite(values["ramsar-52"])
    store.delete(observation_path(scene.year, scene.tile, scene.item_id))
    assert stored_ndvi(store, scene) == {}


def test_verify_run_with_unknown_run_scores_nothing(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, _, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    assert verify_run(cfg, store, "typo", polygons=polygons, docs_dir=None) == []
    report = json.loads(store.read_bytes("verification/typo.json"))
    assert report["all_passed"] is False and report["n_scored"] == 0


ES_HLK = "S2C_MSIL2A_20261027T021211_N0513_R060_T50HLK_20261027T071801"
CDSE_HLK = "S2C_MSIL2A_20261027T021211_N0512_R060_T50HLK_20261027T091500"
CDSE_HLJ = "S2C_MSIL2A_20261027T021211_N0512_R060_T50HLJ_20261027T091500"


def _discovery_clients(
    fixture_item: dict[str, Any],
) -> tuple[FakeClient, list[dict[str, Any]]]:
    other = copy.deepcopy(fixture_item)
    other["id"] = fixture_item["id"].replace("50HLK", "50HLJ")
    other["properties"]["s2:product_uri"] = fixture_item["properties"][
        "s2:product_uri"
    ].replace("T50HLK", "T50HLJ")
    other["properties"]["grid:code"] = "MGRS-50HLJ"
    cdse = [
        {
            "id": name,
            "geometry": fixture_item["geometry"],
            "properties": {
                "datetime": fixture_item["properties"]["datetime"],
                "eo:cloud_cover": 5.0,
                "grid:code": f"MGRS-{name.split('_')[5][1:]}",
            },
        }
        for name in (CDSE_HLK, CDSE_HLJ)
    ]
    return FakeClient([fixture_item, other]), cdse


def _discovery(checks: list[Check]) -> dict[str, Check]:
    return {c.detail["tile"]: c for c in checks if c.name == "discovery_vs_copernicus"}


def test_verify_run_emits_discovery_check_per_tile(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    es, cdse = _discovery_clients(fixture_item)
    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        es_client=es,
        cdse_client=FakeClient(cdse),
        wo_lookup=lambda scene, bbox: None,
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        docs_dir=None,
    )
    found = [c for c in checks if c.name == "discovery_vs_copernicus"]
    assert len(found) == 2
    assert set(_discovery(checks)) == {"50HLK", "50HLJ"}
    assert all(c.passed is True for c in found)
    report = json.loads(store.read_bytes(f"verification/{run_id}.json"))
    in_report = [c for c in report["checks"] if c["name"] == "discovery_vs_copernicus"]
    assert len(in_report) == 2


def test_verify_run_discovery_fails_for_product_missing_from_earth_search(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    es, cdse = _discovery_clients(fixture_item)
    es.items = es.items[:1]  # Earth Search lacks the 50HLJ product
    for item in cdse:  # sensed more than 24 h before the run start
        item["properties"]["datetime"] = "2026-10-27T02:26:39Z"
    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        es_client=es,
        cdse_client=FakeClient(cdse),
        wo_lookup=lambda scene, bbox: None,
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        docs_dir=None,
    )
    by_tile = _discovery(checks)
    assert by_tile["50HLK"].passed is True
    assert by_tile["50HLJ"].passed is False
    assert by_tile["50HLJ"].detail["missing_from_earth_search"] == [CDSE_HLJ]


def test_verify_run_discovery_latency_uses_listing_time_not_run_start(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    es, cdse = _discovery_clients(fixture_item)
    es.items = es.items[:1]  # Earth Search lacks the 50HLJ product
    for item in cdse:  # sensed within 24 h of the run start
        item["properties"]["datetime"] = "2026-10-27T02:26:39Z"
    manifest_key = manifest_path(run_id)
    manifest = json.loads(store.read_bytes(manifest_key))
    manifest["started_at"] = "2026-10-27T10:00:00Z"
    store.write_bytes(manifest_key, json.dumps(manifest).encode())
    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        es_client=es,
        cdse_client=FakeClient(cdse),
        wo_lookup=lambda scene, bbox: None,
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        docs_dir=None,
        clock=lambda: datetime(2026, 10, 30, 10, 0, tzinfo=UTC),  # listed 3 days on
    )
    by_tile = _discovery(checks)
    assert by_tile["50HLJ"].passed is False
    assert by_tile["50HLJ"].detail["missing_from_earth_search"] == [CDSE_HLJ]
    assert by_tile["50HLJ"].detail["pending_latency"] == []


def test_verify_run_discovery_error_is_one_skipped_check(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)

    class Broken:
        def search(self, **kwargs: Any) -> Any:
            raise RuntimeError("CDSE is down")

    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        es_client=FakeClient([fixture_item]),
        cdse_client=Broken(),
        wo_lookup=lambda scene, bbox: None,
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        docs_dir=None,
    )
    found = [c for c in checks if c.name == "discovery_vs_copernicus"]
    assert len(found) == 1
    assert found[0].passed is None
    assert "CDSE is down" in found[0].detail["error"]
    assert found[0].detail["run_id"] == run_id
    assert any(c.name == "reflectance_scaling" and c.passed for c in checks)


def test_pixel_check_skips_on_different_processing_baseline(
    fixture_scene: SceneItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pystac_client

    from wetland_change.verify.pixels import pixel_check

    class Item:
        properties = {"s2:processing_baseline": "04.00"}
        assets: dict[str, Any] = {}

    class Catalog:
        def search(self, **kwargs: Any) -> Any:
            return type("S", (), {"items": lambda self: iter([Item()])})()

    monkeypatch.setattr(pystac_client.Client, "open", lambda *a, **k: Catalog())
    check = pixel_check(fixture_scene, FakeReader(), Window(0, 0, 4, 4))
    assert check.passed is None
    assert check.detail["reason"] == "different processing baseline"
    assert check.detail["earth_search_baseline"] == fixture_scene.processing_baseline
    assert check.detail["planetary_computer_baseline"] == "04.00"


_ERRORED = Check("e", None, None, None, "r", {"error": "RuntimeError: down"})
_REASON_ONLY = Check("s", None, None, None, "r", {"reason": "late reference"})


def _cli_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checks: list[Check]
) -> OutputStore:
    cfg = _config(tmp_path)
    monkeypatch.setattr(cli, "_load", lambda config: (cfg, []))
    monkeypatch.setattr("wetland_change.verify.run.verify_run", lambda *a, **k: checks)
    return OutputStore(cfg.output.root)


def test_cli_verify_errors_without_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _cli_env(monkeypatch, tmp_path, [])
    result = CliRunner().invoke(cli.app, ["verify"])
    assert result.exit_code == 2
    result = CliRunner().invoke(cli.app, ["verify", "--run-id", "typo"])
    assert result.exit_code == 2


@pytest.mark.parametrize(
    ("checks", "code"),
    [
        ([Check("a", True, 1.0, 1.0, "r")], 0),
        ([Check("a", False, 0.5, 1.0, "r")], 3),
        ([Check("a", None, None, None, "r", {"reason": "late"})], 4),
        ([], 4),
        ([Check("a", True, 1.0, 1.0, "r"), _ERRORED], 6),
        ([_ERRORED], 6),
        ([Check("a", False, 0.5, 1.0, "r"), _ERRORED], 3),
        ([Check("a", True, 1.0, 1.0, "r"), _REASON_ONLY], 0),
    ],
)
def test_cli_verify_exit_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checks: list[Check], code: int
) -> None:
    store = _cli_env(monkeypatch, tmp_path, checks)
    store.write_bytes("runs/r1.json", b'{"processed": 1}')
    result = CliRunner().invoke(cli.app, ["verify"])
    assert result.exit_code == code, result.output


def test_cli_verify_names_the_errored_count_on_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _cli_env(monkeypatch, tmp_path, [_ERRORED, _ERRORED])
    store.write_bytes("runs/r1.json", b'{"processed": 1}')
    result = CliRunner().invoke(cli.app, ["verify"])
    assert result.exit_code == 6
    assert "2 reference checks could not run for run r1" in result.output


WB_UID = "qd635epws_v3"


def _waterbody_polygon() -> Any:
    from shapely.geometry import box

    from wetland_change.aoi import AoiPolygon

    geom = box(0, 0, 1932, 1000)  # 193.2 ha
    return AoiPolygon(f"dea-{WB_UID}", WB_UID, "dea_waterbody", geom, geom)


def _add_waterbody_row(
    store: OutputStore, scene: SceneItem, *, wet_fraction: float
) -> None:
    import io

    import pandas as pd

    from wetland_change.outputs.geoparquet import observation_path

    path = observation_path(scene.year, scene.tile, scene.item_id)
    frame = pd.read_parquet(io.BytesIO(store.read_bytes(path)))
    row = frame.iloc[[0]].copy()
    row["polygon_id"] = f"dea-{WB_UID}"
    row["aoi_layer"] = "dea_waterbody"
    row["datetime"] = pd.Timestamp(scene.datetime)
    row["valid_fraction"] = 1.0
    row["water_ha_index"] = wet_fraction * 193.2
    buf = io.BytesIO()
    pd.concat([frame, row], ignore_index=True).to_parquet(buf)
    store.write_bytes(path, buf.getvalue())


def test_verify_run_scores_the_waterbody_history(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    import pandas as pd

    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    scene = scenes_for_run(cfg, store, run_id)[0]
    _add_waterbody_row(store, scene, wet_fraction=0.5)
    loaded: list[str] = []

    def loader(uid: str) -> Any:
        loaded.append(uid)
        return pd.DataFrame(
            {
                "date": [pd.Timestamp(scene.datetime).tz_convert("UTC")],
                "wet_fraction": [0.5025],
            }
        )

    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        waterbody_polygons=[_waterbody_polygon()],
        waterbodies_loader=loader,
        wo_lookup=lambda s, b: None,
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        docs_dir=None,
    )
    assert loaded == [WB_UID]
    wb = [c for c in checks if c.name == "water_vs_dea_waterbodies"]
    assert len(wb) == 1
    assert wb[0].passed is True
    assert wb[0].measured == pytest.approx(0.25)
    spearman = [c for c in checks if c.name == "water_spearman_vs_dea_waterbodies"]
    assert len(spearman) == 1 and spearman[0].passed is None  # fewer than 10 pairs


def _store_earlier_pass(
    store: OutputStore,
    template: SceneItem,
    item_id: str,
    when: datetime,
    *,
    wet_fraction: float,
    run_kind: str = "run",
) -> None:
    """Store one waterbody observation file and its succeeded ledger entry."""
    import io

    import pandas as pd

    from wetland_change.ledger import entry_for, write_ledger
    from wetland_change.outputs.geoparquet import observation_path

    scene = replace(template, item_id=item_id, datetime=when)
    path = observation_path(scene.year, scene.tile, scene.item_id)
    frame = pd.read_parquet(
        io.BytesIO(
            store.read_bytes(
                observation_path(template.year, template.tile, template.item_id)
            )
        )
    )
    row = frame.iloc[[0]].copy()
    row["polygon_id"] = f"dea-{WB_UID}"
    row["aoi_layer"] = "dea_waterbody"
    row["item_id"] = item_id
    row["datetime"] = pd.Timestamp(when)
    row["scene_coverage"] = 1.0
    row["valid_fraction"] = 1.0
    row["water_ha_index"] = wet_fraction * 193.2
    buf = io.BytesIO()
    row.to_parquet(buf)
    store.write_bytes(path, buf.getvalue())
    write_ledger(
        [
            entry_for(
                scene,
                status="succeeded",
                attempts=1,
                run_id=f"earlier-{item_id}",
                processed_at=datetime(2026, 11, 1, tzinfo=UTC),
                n_rows=1,
                observation_path=path,
                run_kind=run_kind,
            )
        ],
        store,
        run_id=f"earlier-{item_id}",
    )


class _CountingStore(OutputStore):
    def __init__(self, root: str) -> None:
        super().__init__(root)
        self.listed: list[str] = []
        self.checked: list[str] = []

    def list_files(self, prefix: str) -> list[str]:
        self.listed.append(prefix)
        return super().list_files(prefix)

    def exists(self, relpath: str) -> bool:
        self.checked.append(relpath)
        return super().exists(relpath)


def _verify_with_history(
    cfg: PipelineConfig,
    store: OutputStore,
    run_id: str,
    polygons: list[Any],
    scene: SceneItem,
    series_dates: list[datetime],
    series_wet: list[float],
) -> list[Check]:
    import pandas as pd

    series = pd.DataFrame(
        {
            "date": [pd.Timestamp(d).tz_convert("UTC") for d in series_dates],
            "wet_fraction": series_wet,
        }
    )
    return verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        waterbody_polygons=[_waterbody_polygon()],
        waterbodies_loader=lambda uid: series,
        wo_lookup=lambda s, b: None,
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        docs_dir=None,
    )


def test_verify_run_scores_spearman_over_stored_history(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    from datetime import timedelta

    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    scene = scenes_for_run(cfg, store, run_id)[0]
    _add_waterbody_row(store, scene, wet_fraction=0.5)
    days = [
        (f"h{k}", k * 10, 0.5 - 0.02 * k, "backfill" if k % 2 else "run")
        for k in range(1, 13)
    ]
    # Exactly history_days back is in the window; one day further is out, and so
    # is a pass newer than the run's newest scene.
    days += [("edge-in", 365, 0.1, "run"), ("edge-out", 366, 0.1, "run")]
    for item_id, back, wet, kind in days:
        _store_earlier_pass(
            store,
            scene,
            item_id,
            scene.datetime - timedelta(days=back),
            wet_fraction=wet,
            run_kind=kind,
        )
    _store_earlier_pass(
        store, scene, "later", scene.datetime + timedelta(days=3), wet_fraction=0.9
    )
    dates = [scene.datetime] + [
        scene.datetime - timedelta(days=b) for _, b, _, _ in days
    ]
    dates.append(scene.datetime + timedelta(days=3))
    wets = [0.5025] + [w + 0.0025 for _, _, w, _ in days] + [0.9025]
    checks = _verify_with_history(cfg, store, run_id, polygons, scene, dates, wets)
    per_pass = [c for c in checks if c.name == "water_vs_dea_waterbodies"]
    assert len(per_pass) == 1  # the verified run only
    (spearman,) = [c for c in checks if c.name == "water_spearman_vs_dea_waterbodies"]
    assert spearman.passed is not None
    # run pass + 12 history passes + the pass exactly history_days back
    assert spearman.detail["n_pairs"] == 14
    assert spearman.detail["n_run_pairs"] == 1
    assert spearman.detail["history_days"] == 365


def _lake_dates_and_wets(
    scene: SceneItem, days: list[tuple[str, int, float]]
) -> tuple[list[datetime], list[float]]:
    from datetime import timedelta

    dates = [scene.datetime] + [scene.datetime - timedelta(days=b) for _, b, _ in days]
    wets = [0.5025] + [w + 0.0025 for _, _, w in days]
    return dates, wets


def test_verify_run_scores_spearman_when_the_run_has_no_lake_rows(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    from datetime import timedelta

    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    scene = scenes_for_run(cfg, store, run_id)[0]
    # No _add_waterbody_row: the run's own rows are all non-lake polygons.
    days = [(f"h{k}", k * 10, 0.5 - 0.02 * k) for k in range(1, 13)]
    for item_id, back, wet in days:
        _store_earlier_pass(
            store,
            scene,
            item_id,
            scene.datetime - timedelta(days=back),
            wet_fraction=wet,
        )
    dates, wets = _lake_dates_and_wets(scene, days)
    checks = _verify_with_history(cfg, store, run_id, polygons, scene, dates, wets)
    assert not [c for c in checks if c.name == "water_vs_dea_waterbodies"]
    (spearman,) = [c for c in checks if c.name == "water_spearman_vs_dea_waterbodies"]
    assert spearman.passed is not None
    assert spearman.detail["n_pairs"] == 12
    assert spearman.detail["n_run_pairs"] == 0
    assert not [c for c in checks if c.name.startswith("water") and c.errored]


def test_verify_run_history_uses_only_the_latest_succeeded_stored_entries(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    from datetime import timedelta

    from wetland_change.ledger import entry_for, write_ledger
    from wetland_change.outputs.geoparquet import observation_path

    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    scene = scenes_for_run(cfg, store, run_id)[0]
    _add_waterbody_row(store, scene, wet_fraction=0.5)
    days = [(f"h{k}", k * 10, 0.5 - 0.02 * k) for k in range(1, 13)]
    for item_id, back, wet in days:
        _store_earlier_pass(
            store,
            scene,
            item_id,
            scene.datetime - timedelta(days=back),
            wet_fraction=wet,
        )
    extra = [("failed-later", 130, 0.2), ("file-gone", 140, 0.3)]
    for item_id, back, wet in extra:
        _store_earlier_pass(
            store,
            scene,
            item_id,
            scene.datetime - timedelta(days=back),
            wet_fraction=wet,
        )
    # Its latest ledger row is a failure, though an earlier success left a file.
    failed_scene = replace(
        scene,
        item_id="failed-later",
        datetime=scene.datetime - timedelta(days=130),
    )
    write_ledger(
        [
            entry_for(
                failed_scene,
                status="failed",
                attempts=1,
                run_id="later-failure",
                processed_at=datetime(2026, 11, 2, tzinfo=UTC),
                error="boom",
            )
        ],
        store,
        run_id="later-failure",
    )
    # The ledger lists the file as succeeded, but it is no longer in the store.
    gone = observation_path(scene.year, scene.tile, "file-gone")
    assert store.delete(gone)
    dates, wets = _lake_dates_and_wets(scene, days + extra)
    checks = _verify_with_history(cfg, store, run_id, polygons, scene, dates, wets)
    (spearman,) = [c for c in checks if c.name == "water_spearman_vs_dea_waterbodies"]
    assert spearman.passed is not None
    # run pass + 12 healthy history passes; neither extra item counts
    assert spearman.detail["n_pairs"] == 13
    assert not [c for c in checks if c.name.startswith("water") and c.errored]


def test_verify_run_reads_history_with_one_ledger_listing_and_no_exists(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    from datetime import timedelta

    cfg, _, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    store = _CountingStore(cfg.output.root)
    scene = scenes_for_run(cfg, store, run_id)[0]
    _add_waterbody_row(store, scene, wet_fraction=0.5)
    for k in range(1, 4):
        _store_earlier_pass(
            store,
            scene,
            f"h{k}",
            scene.datetime - timedelta(days=10 * k),
            wet_fraction=0.4,
        )
    store.listed.clear()
    store.checked.clear()
    _verify_with_history(
        cfg,
        store,
        run_id,
        polygons,
        scene,
        [scene.datetime],
        [0.5],
    )
    assert store.listed.count("ledger") == 1
    assert store.listed.count("observations") == 1
    assert not [p for p in store.checked if p.startswith("observations")]


def test_verify_run_without_waterbodies_makes_no_history_check(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    def loader(uid: str) -> Any:
        raise AssertionError("the loader must not be called")

    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        waterbodies_loader=loader,
        wo_lookup=lambda s, b: None,
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        docs_dir=None,
    )
    names = {c.name for c in checks}
    assert "water_vs_dea_waterbodies" not in names
    assert "water_spearman_vs_dea_waterbodies" not in names

    # Waterbody polygons but no stored waterbody rows: still no fetch.
    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        waterbody_polygons=[_waterbody_polygon()],
        waterbodies_loader=loader,
        wo_lookup=lambda s, b: None,
        pixel_checker=lambda *a: Check("p", True, 1.0, 1.0, "fake"),
        docs_dir=None,
    )
    names = {c.name for c in checks}
    assert "water_vs_dea_waterbodies" not in names
    assert "water_spearman_vs_dea_waterbodies" not in names


BBOX = (115.8168, -32.1615, 115.8421, -32.1378)


def _scene_on(
    base: SceneItem, item_id: str, year: int, month: int, day: int
) -> SceneItem:
    return replace(
        base, item_id=item_id, datetime=datetime(year, month, day, 2, 23, tzinfo=UTC)
    )


class _FakeFind:
    def __init__(self, hrefs: dict[str, str | None]) -> None:
        self.hrefs = hrefs
        self.calls: list[tuple[str, tuple[float, float, float, float]]] = []

    def __call__(
        self, scene: SceneItem, bbox: tuple[float, float, float, float]
    ) -> str | None:
        self.calls.append((scene.item_id, bbox))
        return self.hrefs.get(scene.item_id)


def test_wo_candidates_newest_first_skips_scenes_without_wo(
    fixture_scene: SceneItem,
) -> None:
    old = _scene_on(fixture_scene, "old", 2026, 12, 1)
    mid = _scene_on(fixture_scene, "mid", 2026, 12, 11)
    new = _scene_on(fixture_scene, "new", 2026, 12, 21)
    find = _FakeFind({"old": "https://wo/old", "mid": None, "new": "https://wo/new"})
    got = list(wo_candidates([old, mid, new], BBOX, find=find))
    assert [(s.item_id, h) for s, h in got] == [
        ("new", "https://wo/new"),
        ("old", "https://wo/old"),
    ]
    assert all(bbox == BBOX for _, bbox in find.calls)
    assert [i for i, _ in find.calls] == ["new", "mid", "old"]


def test_wo_candidates_pinned_fixture_date_gone(fixture_scene: SceneItem) -> None:
    pinned = _scene_on(fixture_scene, "pinned", 2026, 10, 27)
    newer = _scene_on(fixture_scene, "newer", 2027, 2, 3)
    find = _FakeFind({"pinned": None, "newer": "https://wo/newer"})
    got = list(wo_candidates([pinned, newer], BBOX, find=find))
    assert [(s.item_id, h) for s, h in got] == [("newer", "https://wo/newer")]


def test_wo_candidates_empty_when_no_wo_anywhere(fixture_scene: SceneItem) -> None:
    scenes = [
        _scene_on(fixture_scene, "a", 2026, 12, 1),
        _scene_on(fixture_scene, "b", 2026, 12, 6),
    ]
    assert list(wo_candidates(scenes, BBOX, find=_FakeFind({}))) == []


def test_wo_candidates_limit(fixture_scene: SceneItem) -> None:
    scenes = [
        _scene_on(fixture_scene, f"s{day}", 2026, 12, day) for day in (1, 6, 11, 16)
    ]
    find = _FakeFind({s.item_id: f"https://wo/{s.item_id}" for s in scenes})
    got = list(wo_candidates(scenes, BBOX, find=find, limit=2))
    assert [s.item_id for s, _ in got] == ["s16", "s11"]
    assert len(find.calls) == 2


def _wo_check(item: str, agreement: float | None, n: int) -> Check:
    return Check(
        "water_vs_dea_s2_wo",
        None if agreement is None else True,
        agreement,
        0.9,
        "https://wo",
        {"item": item, "n_mutually_clear": n},
    )


def test_pooled_agreement_is_pixel_weighted() -> None:
    checks = [_wo_check("a", 0.99, 90000), _wo_check("b", 0.89, 10000)]
    got = pooled_agreement(checks)
    assert got is not None
    agreement, n = got
    assert n == 100000
    assert agreement == pytest.approx(0.98)


def test_pooled_agreement_skips_unmeasured_and_empty() -> None:
    checks = [_wo_check("a", None, 0), _wo_check("b", 0.5, 0), _wo_check("c", 0.9, 10)]
    assert pooled_agreement(checks) == pytest.approx((0.9, 10))


def test_pooled_agreement_none_when_nothing_usable() -> None:
    assert pooled_agreement([]) is None
    assert pooled_agreement([_wo_check("a", None, 0)]) is None


def _assert_every_name_maps_to_a_row(checks: list[Check]) -> None:
    from wetland_change.verify.matrix import matrix_status

    rows = matrix_status(checks)
    mapped = {
        name for r in rows if r["row"] != "End to end" for name in r["check_names"]
    }
    assert {c.name for c in checks} <= mapped


def test_every_check_name_verify_run_emits_maps_to_a_matrix_row(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    grid = RasterioReader().open_grid(fixture_item["assets"]["green"]["href"])
    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=polygons,
        wo_lookup=lambda scene, bbox: "wo.tif",
        wo_reader_factory=lambda: FakeReader(
            grid=grid, data=np.full((48, 48), WO_WET, np.uint8)
        ),
        pixel_checker=lambda scene, reader, window: Check(
            "pixels_vs_planetary_computer", True, 1.0, 1.0, "fake"
        ),
        docs_dir=None,
    )
    names = {c.name for c in checks}
    assert {"reflectance_scaling", "water_vs_dea_s2_wo"} <= names
    assert any(n.startswith("scl_share_") for n in names)
    _assert_every_name_maps_to_a_row(checks)
    report = json.loads(store.read_bytes(f"verification/{run_id}.json"))
    assert len(report["matrix"]) == 14


def test_error_check_names_map_to_a_matrix_row(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, run_id, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    checks = verify_run(
        cfg, store, run_id, polygons=polygons, reader=FakeReader(), docs_dir=None
    )
    names = {c.name for c in checks if c.errored}
    assert {"scl_shares", "scene_grid"} <= names
    _assert_every_name_maps_to_a_row(checks)
    report = json.loads(store.read_bytes(f"verification/{run_id}.json"))
    assert report["all_passed"] is False
