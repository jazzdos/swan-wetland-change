"""The daily run fills `dea_wo_agreement` from DEA Water Observations."""

from __future__ import annotations

import dataclasses
import hashlib
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from affine import Affine
from shapely.geometry.base import BaseGeometry

from tests.test_pipeline import NOW, FakeClient, _config, _polygons
from tests.test_verify import FakeReader, _stack_and_window
from wetland_change.catalogue.item import SceneItem
from wetland_change.config import VerifyConfig, WaterConfig, WaterSetting
from wetland_change.mask import clear_mask
from wetland_change.outputs.geoparquet import read_observations
from wetland_change.pipeline import process_scene, run_once
from wetland_change.raster.read import Grid, RasterioReader
from wetland_change.stats import rasterise, water_pixels
from wetland_change.store import OutputStore
from wetland_change.verify.wo import (
    SceneWo,
    observation_agreement,
    resolve_scene_wo,
    wo_agreement,
    wo_check,
)

BBOX = (115.0, -32.5, 116.0, -32.0)
POLYGON_ID = "ramsar-52"


def _wo_array(shape: tuple[int, int]) -> np.ndarray:
    """Fixed pseudo-random WO flags: wet (128) or dry (0), so agreement is partial."""
    rng = np.random.default_rng(7)
    return np.where(rng.random(shape) < 0.5, 128, 0).astype(np.uint8)


class RaisingReader(FakeReader):
    """FakeReader whose chosen method raises and which counts every call."""

    def __init__(self, *, raise_on: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.raise_on = raise_on
        self.calls = 0

    def open_grid(self, href: str) -> Grid:
        self.calls += 1
        if self.raise_on == "open_grid":
            raise OSError("DEA unreachable")
        return super().open_grid(href)

    def read(self, href: str, window: Any) -> np.ndarray:
        self.calls += 1
        if self.raise_on == "read":
            raise OSError("DEA read failed")
        return super().read(href, window)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == logging.WARNING]


@pytest.mark.parametrize("override", [False, True])
def test_observation_agreement_equals_wo_check_measured(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry, override: bool
) -> None:
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    water = WaterConfig(
        overrides={POLYGON_ID: WaterSetting(method="scl6", agreement_min=0.5)}
        if override
        else {}
    )
    reader = FakeReader(grid=grid, data=_wo_array(stack.shape))
    expected = wo_check(
        fixture_scene,
        stack,
        planned,
        inside,
        water=water,
        wo_href="wo.tif",
        reader=reader,
        scene_grid=grid,
        polygon_id=POLYGON_ID,
    ).measured
    assert expected is not None
    assert 0.0 < expected < 1.0
    got = observation_agreement(
        fixture_scene,
        stack,
        planned,
        inside,
        water=water,
        polygon_id=POLYGON_ID,
        wo=SceneWo("wo.tif", reader),
        scene_grid=grid,
    )
    assert got == expected


def test_override_changes_the_number(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    """The override is honoured: scl6 and ndwi give different agreement."""
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    reader = FakeReader(grid=grid, data=_wo_array(stack.shape))
    wo = SceneWo("wo.tif", reader)

    def run(water: WaterConfig) -> float | None:
        return observation_agreement(
            fixture_scene,
            stack,
            planned,
            inside,
            water=water,
            polygon_id=POLYGON_ID,
            wo=wo,
            scene_grid=grid,
        )

    plain = run(WaterConfig())
    scl6 = run(
        WaterConfig(
            overrides={POLYGON_ID: WaterSetting(method="scl6", agreement_min=0.5)}
        )
    )
    assert plain is not None and scl6 is not None
    assert plain != scl6


def test_none_when_wo_grid_differs(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    shifted = dataclasses.replace(
        grid, transform=grid.transform @ Affine.translation(1, 0)
    )
    reader = FakeReader(grid=shifted, data=_wo_array(stack.shape))
    assert (
        observation_agreement(
            fixture_scene,
            stack,
            planned,
            inside,
            water=WaterConfig(),
            polygon_id=POLYGON_ID,
            wo=SceneWo("wo.tif", reader),
            scene_grid=grid,
        )
        is None
    )


def test_none_without_a_mutually_clear_pixel(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    reader = FakeReader(grid=grid, data=np.ones(stack.shape, dtype=np.uint8))
    assert (
        observation_agreement(
            fixture_scene,
            stack,
            planned,
            inside,
            water=WaterConfig(),
            polygon_id=POLYGON_ID,
            wo=SceneWo("wo.tif", reader),
            scene_grid=grid,
        )
        is None
    )


def test_resolve_scene_wo_none_when_lookup_finds_nothing(
    fixture_scene: SceneItem,
) -> None:
    built: list[int] = []

    def factory() -> FakeReader:
        built.append(1)
        return FakeReader()

    assert (
        resolve_scene_wo(
            fixture_scene, BBOX, lookup=lambda s, b: None, reader_factory=factory
        )
        is None
    )
    assert built == []


def test_resolve_scene_wo_returns_href_and_reader(fixture_scene: SceneItem) -> None:
    reader = FakeReader()
    wo = resolve_scene_wo(
        fixture_scene,
        BBOX,
        lookup=lambda s, b: "wo.tif",
        reader_factory=lambda: reader,
    )
    assert wo is not None
    assert (wo.href, wo.reader, wo.failed) == ("wo.tif", reader, False)


def test_lookup_error_gives_none_and_warns(
    fixture_scene: SceneItem, caplog: pytest.LogCaptureFixture
) -> None:
    def lookup(scene: SceneItem, bbox: Any) -> str | None:
        raise OSError("DEA STAC down")

    with caplog.at_level(logging.WARNING):
        wo = resolve_scene_wo(
            fixture_scene, BBOX, lookup=lookup, reader_factory=FakeReader
        )
    assert wo is None
    records = _warnings(caplog)
    assert len(records) == 1
    assert fixture_scene.item_id in records[0].getMessage()
    assert records[0].exc_info is not None


def test_reader_factory_error_gives_none_and_warns(
    fixture_scene: SceneItem, caplog: pytest.LogCaptureFixture
) -> None:
    def factory() -> FakeReader:
        raise RuntimeError("no credentials")

    with caplog.at_level(logging.WARNING):
        wo = resolve_scene_wo(
            fixture_scene, BBOX, lookup=lambda s, b: "wo.tif", reader_factory=factory
        )
    assert wo is None
    assert len(_warnings(caplog)) == 1


@pytest.mark.parametrize("raise_on", ["open_grid", "read"])
def test_reader_error_gives_none_and_warns(
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    caplog: pytest.LogCaptureFixture,
    raise_on: str,
) -> None:
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    reader = RaisingReader(raise_on=raise_on, grid=grid, data=_wo_array(stack.shape))
    wo = SceneWo("wo.tif", reader)
    with caplog.at_level(logging.WARNING):
        got = observation_agreement(
            fixture_scene,
            stack,
            planned,
            inside,
            water=WaterConfig(),
            polygon_id=POLYGON_ID,
            wo=wo,
            scene_grid=grid,
        )
    assert got is None
    records = _warnings(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert fixture_scene.item_id in message
    assert POLYGON_ID in message
    assert wo.failed


def test_failed_scene_wo_is_not_retried_for_the_next_polygon(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    reader = RaisingReader(raise_on="read", grid=grid, data=_wo_array(stack.shape))
    wo = SceneWo("wo.tif", reader)

    def call() -> float | None:
        return observation_agreement(
            fixture_scene,
            stack,
            planned,
            inside,
            water=WaterConfig(),
            polygon_id=POLYGON_ID,
            wo=wo,
            scene_grid=grid,
        )

    assert call() is None
    calls_after_first = reader.calls
    assert calls_after_first >= 1
    assert call() is None
    assert reader.calls == calls_after_first


def _scene_rows(scene: SceneItem, polygons: list[Any], **kwargs: Any) -> list[Any]:
    return process_scene(
        scene,
        polygons,
        reader=RasterioReader(),
        water=WaterConfig(),
        operation_epsg=32750,
        run_id="run-1",
        **kwargs,
    )


def test_process_scene_fills_the_column(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    polygons = _polygons(fixture_polygon)
    grid = RasterioReader().open_grid(fixture_scene.bands["green"].href)
    plain = _scene_rows(fixture_scene, polygons)
    assert len(plain) == 1
    assert plain[0].dea_wo_agreement is None

    stack, _planned, inside, _grid = _stack_and_window(fixture_scene, fixture_polygon)
    data = _wo_array(stack.shape)
    clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & rasterise(
        fixture_polygon, stack.transform, stack.shape
    )
    expected, n = wo_agreement(
        water_pixels(WaterConfig().for_polygon(POLYGON_ID), stack, clear), clear, data
    )
    assert n > 0
    assert 0.0 < expected < 1.0

    lookups: list[str] = []

    def lookup(scene: SceneItem, bbox: Any) -> str | None:
        lookups.append(scene.item_id)
        return "wo.tif"

    filled = _scene_rows(
        fixture_scene,
        polygons,
        wo_lookup=lookup,
        wo_reader_factory=lambda: FakeReader(grid=grid, data=data),
    )
    assert lookups == [fixture_scene.item_id]
    assert len(filled) == 1
    assert filled[0].dea_wo_agreement == expected
    assert dataclasses.replace(filled[0], dea_wo_agreement=None) == plain[0]


def test_none_below_the_min_clear_pixels_floor(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    """The row and the report share one floor: fewer clear pixels than it gives None."""
    stack, planned, inside, grid = _stack_and_window(fixture_scene, fixture_polygon)
    data = _wo_array(stack.shape)
    clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
    _expected, n = wo_agreement(
        water_pixels(WaterConfig().for_polygon(POLYGON_ID), stack, clear), clear, data
    )
    assert n > 1

    def run(floor: int) -> float | None:
        return observation_agreement(
            fixture_scene,
            stack,
            planned,
            inside,
            water=WaterConfig(),
            polygon_id=POLYGON_ID,
            wo=SceneWo("wo.tif", FakeReader(grid=grid, data=data)),
            scene_grid=grid,
            min_clear_pixels=floor,
        )

    assert run(n) is not None
    assert run(n + 1) is None


def test_process_scene_applies_the_min_clear_pixels_floor(
    fixture_scene: SceneItem, fixture_polygon: BaseGeometry
) -> None:
    polygons = _polygons(fixture_polygon)
    grid = RasterioReader().open_grid(fixture_scene.bands["green"].href)
    stack = _stack_and_window(fixture_scene, fixture_polygon)[0]
    data = _wo_array(stack.shape)

    def rows(floor: int) -> list[Any]:
        return _scene_rows(
            fixture_scene,
            polygons,
            wo_lookup=lambda s, b: "wo.tif",
            wo_reader_factory=lambda: FakeReader(grid=grid, data=data),
            wo_min_clear_pixels=floor,
        )

    assert rows(1)[0].dea_wo_agreement is not None
    assert rows(10_000_000)[0].dea_wo_agreement is None


def test_process_scene_survives_dea_errors(
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    polygons = _polygons(fixture_polygon)
    plain = _scene_rows(fixture_scene, polygons)

    def lookup(scene: SceneItem, bbox: Any) -> str | None:
        raise OSError("DEA STAC down")

    with caplog.at_level(logging.WARNING):
        rows = _scene_rows(fixture_scene, polygons, wo_lookup=lookup)
    assert rows == plain
    assert _warnings(caplog)


def _run_with_wo(
    tmp_path: Path,
    fixture_item: dict[str, Any],
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    lookup: Any,
    *,
    now: Any = NOW,
    min_clear_pixels: int | None = None,
) -> Any:
    stack = _stack_and_window(fixture_scene, fixture_polygon)[0]
    grid = RasterioReader().open_grid(fixture_scene.bands["green"].href)
    cfg = _config(tmp_path)
    if min_clear_pixels is not None:
        cfg = cfg.model_copy(
            update={"verify": VerifyConfig(min_clear_pixels=min_clear_pixels)}
        )
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")
    return run_once(
        cfg,
        client=FakeClient([fixture_item]),
        reader=RasterioReader(),
        store=OutputStore(cfg.output.root),
        polygons=_polygons(fixture_polygon),
        now=now,
        config_path=config_path,
        wo_lookup=lookup,
        wo_reader_factory=lambda: FakeReader(grid=grid, data=_wo_array(stack.shape)),
    )


def test_run_once_with_failing_lookup_still_processes_the_scene(
    fixture_item: dict[str, Any],
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    def lookup(scene: SceneItem, bbox: Any) -> str | None:
        raise OSError("DEA STAC down")

    manifest = _run_with_wo(
        tmp_path, fixture_item, fixture_scene, fixture_polygon, lookup
    )
    assert (manifest.processed, manifest.failed) == (1, 0)
    observations = read_observations(OutputStore(str(tmp_path / "out")))
    assert len(observations) == 1
    assert observations["dea_wo_agreement"].isna().all()


def test_run_once_stores_agreement_and_is_byte_identical(
    fixture_item: dict[str, Any],
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    def digest(root: Path) -> dict[str, str]:
        return {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }

    def lookup(scene: SceneItem, bbox: Any) -> str | None:
        return "wo.tif"

    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        root.mkdir()
        manifest = _run_with_wo(
            root, fixture_item, fixture_scene, fixture_polygon, lookup
        )
        assert (manifest.processed, manifest.failed) == (1, 0)
    observations = read_observations(OutputStore(str(first / "out")))
    column = observations["dea_wo_agreement"]
    assert str(column.dtype) == "float64"
    assert column.notna().all()
    assert ((column > 0) & (column < 1)).all()
    assert digest(first / "out") == digest(second / "out")


def test_run_once_applies_the_verify_min_clear_pixels_floor(
    fixture_item: dict[str, Any],
    fixture_scene: SceneItem,
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    """The row uses `verify.min_clear_pixels`, the floor the report uses."""
    manifest = _run_with_wo(
        tmp_path,
        fixture_item,
        fixture_scene,
        fixture_polygon,
        lambda scene, bbox: "wo.tif",
        min_clear_pixels=10_000_000,
    )
    assert (manifest.processed, manifest.failed) == (1, 0)
    observations = read_observations(OutputStore(str(tmp_path / "out")))
    assert len(observations) == 1
    assert observations["dea_wo_agreement"].isna().all()
