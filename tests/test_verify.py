from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from tests.conftest import FIXTURE_DIR
from wetland_change.catalogue.item import SceneItem
from wetland_change.store import OutputStore
from wetland_change.verify.checks import Check, write_report
from wetland_change.verify.pixels import pc_item_id
from wetland_change.verify.scaling import scaling_check
from wetland_change.verify.scl import scl_shares
from wetland_change.verify.wo import WO_EXCLUDE, WO_WET, wo_agreement


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


def test_wo_agreement_with_nothing_clear_is_nan() -> None:
    agreement, n = wo_agreement(
        np.zeros((1, 1), bool), np.zeros((1, 1), bool), np.zeros((1, 1), np.uint8)
    )
    assert n == 0 and np.isnan(agreement)


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
from wetland_change.config import PipelineConfig, WaterConfig  # noqa: E402
from wetland_change.raster.read import RasterioReader, read_stack  # noqa: E402
from wetland_change.stats import rasterise  # noqa: E402
from wetland_change.verify.run import (  # noqa: E402
    latest_run_id,
    scenes_for_run,
    verify_run,
)
from wetland_change.verify.scl import scl_checks  # noqa: E402
from wetland_change.verify.wo import wo_check  # noqa: E402
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
            water=WaterConfig(),
            wo_href="wo.tif",
            reader=reader,
            scene_grid=grid,
            agreement_min=0.5,
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

    wet = run(FakeReader(grid=grid, data=np.full(shape, WO_WET, np.uint8)))
    assert wet.detail["n_mutually_clear"] > 0
    assert wet.passed is True
    dry = run(FakeReader(grid=grid, data=np.zeros(shape, np.uint8)))
    assert dry.passed is False


def _built_run(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> tuple[PipelineConfig, OutputStore, str, list[Any]]:
    polygons = _polygons(fixture_polygon)
    manifest = _run(tmp_path, FakeClient([fixture_item]), polygons, NOW)
    cfg = _config(tmp_path)
    return cfg, OutputStore(cfg.output.root), manifest.run_id, polygons


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


def test_verify_run_with_unknown_run_scores_nothing(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    cfg, store, _, polygons = _built_run(fixture_item, fixture_polygon, tmp_path)
    assert verify_run(cfg, store, "typo", polygons=polygons, docs_dir=None) == []
    report = json.loads(store.read_bytes("verification/typo.json"))
    assert report["all_passed"] is False and report["n_scored"] == 0


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
        ([Check("a", None, None, None, "r")], 4),
        ([], 4),
    ],
)
def test_cli_verify_exit_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checks: list[Check], code: int
) -> None:
    store = _cli_env(monkeypatch, tmp_path, checks)
    store.write_bytes("runs/r1.json", b'{"processed": 1}')
    result = CliRunner().invoke(cli.app, ["verify"])
    assert result.exit_code == code, result.output
