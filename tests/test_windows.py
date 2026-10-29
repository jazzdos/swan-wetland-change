from __future__ import annotations

import pytest
from affine import Affine
from shapely.geometry import box

from wetland_change.windows import Grid, PlannedWindow, plan_window

TILE = Grid(
    Affine(10, 0, 300000, 0, -10, 6500020), width=10980, height=10980, epsg=32750
)


def test_grid_bounds() -> None:
    assert TILE.bounds == (300000, 6390220, 409800, 6500020)


def test_window_snaps_to_20m_lattice() -> None:
    planned = plan_window(box(389400, 6442180, 389840, 6442620), TILE)
    assert isinstance(planned, PlannedWindow)
    w10 = planned.window10
    assert (w10.col_off, w10.row_off, w10.width, w10.height) == (8938, 5738, 48, 48)
    w20 = planned.window20
    assert (w20.col_off, w20.row_off, w20.width, w20.height) == (4469, 2869, 24, 24)
    assert planned.transform10.c == 389380
    assert planned.transform10.f == 6442640
    assert planned.scene_coverage == pytest.approx(1.0)
    assert planned.shape10 == (48, 48)


def test_odd_pixel_bounds_round_outwards_to_even() -> None:
    planned = plan_window(box(389415, 6442185, 389835, 6442615), TILE)
    assert planned is not None
    assert planned.window10.col_off % 2 == 0
    assert planned.window10.row_off % 2 == 0
    assert planned.window10.width % 2 == 0
    assert planned.window10.height % 2 == 0
    assert (
        planned.window10.col_off
        <= 8939
        < planned.window10.col_off + planned.window10.width
    )


def test_window_clips_at_scene_edge_and_reports_coverage() -> None:
    planned = plan_window(box(409700, 6442000, 410000, 6442300), TILE)
    assert planned is not None
    assert planned.window10.col_off + planned.window10.width == 10980
    assert planned.scene_coverage == pytest.approx(1 / 3, abs=1e-9)


def test_outside_scene_returns_none() -> None:
    assert plan_window(box(500000, 6442000, 500300, 6442300), TILE) is None


def test_rejects_grid_off_lattice() -> None:
    off = Grid(Affine(10, 0, 300010, 0, -10, 6500020), width=10, height=10, epsg=32750)
    with pytest.raises(ValueError, match="lattice"):
        plan_window(box(300020, 6499900, 300060, 6499960), off)


def test_rejects_non_10m_grid() -> None:
    coarse = Grid(
        Affine(20, 0, 300000, 0, -20, 6500020), width=10, height=10, epsg=32750
    )
    with pytest.raises(ValueError, match="10 m"):
        plan_window(box(300020, 6499900, 300060, 6499960), coarse)
