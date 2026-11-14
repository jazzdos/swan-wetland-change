"""Tests for the NDVI row-rule research script (st-da75, batch b2).

The script is a dated research file, so it is loaded by path. Every row here is
synthetic or read from a committed file: no raster is read and nothing touches
the network.
"""

import builtins
import csv
import dataclasses
import importlib.util
import json
import math
import re
import socket
import subprocess
import sys
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pytest
import requests
from rasterio.errors import RasterioIOError

from wetland_change.config import load_config
from wetland_change.verify.ndvi import (
    CORRELATION_MIN,
    CORRELATION_MIN_ROWS,
    MEDIAN_TOLERANCE,
    ndvi_correlation_check,
    ndvi_median_check,
)

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "docs" / "research" / "2026-11-12-ndvi-nbart-rows.py"
LEARNINGS = REPO / "LEARNINGS.md"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ndvi_nbart_rows", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ndvi_nbart_rows"] = module
    spec.loader.exec_module(module)
    return module


nr = _load()

DATES = (
    "2026-09-12",
    "2026-09-17",
    "2026-10-02",
    "2026-10-12",
    "2026-10-27",
    "2026-01-30",
)
G = Fraction(5, 1000)


def _floor_float(value: Fraction) -> float:
    """The largest float that is at most value."""
    as_float = float(value)
    if Fraction(as_float) > value:
        return math.nextafter(as_float, -math.inf)
    return as_float


def _ceil_float(value: Fraction) -> float:
    """The smallest float that is at least value."""
    as_float = float(value)
    if Fraction(as_float) < value:
        return math.nextafter(as_float, math.inf)
    return as_float


def mk(
    pass_date: str = "2026-09-12",
    tile: str = "50HLJ",
    polygon: str = "ramsar-1",
    *,
    stored: float = 0.5,
    dea: float = 0.5,
    s_dea: float = 1.0,
    d_red: float = 0.0,
    d_nir: float = 0.0,
    n: int = 500,
    status: str = "scored",
    sample: str = "confirm",
    maturity: str = "final",
    **extra: Any,
) -> Any:
    stamp = pass_date.replace("-", "")
    fields: dict[str, Any] = {
        "sample": sample,
        "pass_date": pass_date,
        "item_id": f"S2B_T{tile}_{stamp}T022111_L2A",
        "tile": tile,
        "polygon_id": polygon,
        "status": status,
        "reason": "",
        "dea_maturity": maturity,
        "n_compared": n,
        "ndvi_stored": stored,
        "ndvi_dea": dea,
        "abs_diff": abs(stored - dea),
        "ndvi_pipeline_same": stored,
        "s_dea": s_dea,
        "d_red": d_red,
        "d_nir": d_nir,
        "band_max": max(abs(d_red), abs(d_nir)),
    }
    fields.update(extra)
    return nr.Row(**fields)


def _spread(count: int, passes: int = 6) -> list[int]:
    quotient, remainder = divmod(count, passes)
    return [quotient + (1 if i < remainder else 0) for i in range(passes)]


def _first(count: int, passes: int = 6) -> list[int]:
    return [count] + [0] * (passes - 1)


def _each(count: int, passes: int = 6) -> list[int]:
    return [count] * passes


def fixture(**counts: list[int]) -> list[Any]:
    """Confirmatory rows over six passes at g = 0.005 (S* = 0.20).

    w_pass and w_fail are well-conditioned rows (s_dea 1.0). if_ and ip_ are
    ill-conditioned rows (s_dea 0.05) that fail or pass K0; within and outside
    say whether both band differences are within g. The base counts meet A0 to
    A5; each variation changes one criterion.
    """
    spec: dict[str, list[int]] = {
        "w_pass": _spread(600),
        "w_fail": [0] * 6,
        "if_within": _spread(102),
        "if_outside": [0] * 6,
        "ip_within": _spread(480),
        "ip_outside": [0] * 6,
    }
    spec.update(counts)
    out: list[Any] = []
    serial = 0
    for index, date in enumerate(DATES):
        for kind, per_pass in spec.items():
            for _ in range(per_pass[index]):
                base = -0.5 + 0.9 * (serial % 50) / 50
                serial += 1
                fails = kind in ("w_fail", "if_within", "if_outside")
                outside = kind in ("if_outside", "ip_outside")
                out.append(
                    mk(
                        date,
                        polygon=f"ramsar-{serial}",
                        stored=base + 0.1 if fails else base,
                        dea=base,
                        s_dea=1.0 if kind.startswith("w_") else 0.05,
                        d_red=0.05 if outside else 0.001,
                        d_nir=-0.001,
                    )
                )
    return out


def _row_key(row: Any) -> tuple[str, str, str]:
    return (row.pass_date, row.item_id, row.polygon_id)


def seen_gate_rows(**over: Any) -> list[Any]:
    """The eight seen failing rows with values that reproduce the reports."""
    rows = []
    for pass_date, item_id, polygon in nr.SEEN_FAILING:
        tile = nr.tile_of(item_id)
        base = mk(
            pass_date,
            tile,
            polygon,
            sample="nomination",
            stored=0.1,
            dea=0.1,
            n=1000,
            maturity="final",
            report_ndvi_median=0.1,
            report_dea_ndvi_median=0.2,
            report_n_compared=1000,
            recorded_dea_item="recorded-item",
            recorded_dea_maturity="final",
            recorded_dea_served=True,
            recorded_ndvi_dea=0.2,
            recorded_n_compared=1000,
            seen_failing=True,
        )
        rows.append(dataclasses.replace(base, item_id=item_id, **over))
    return rows


# constants -----------------------------------------------------------------


def test_constants_match_src_and_config() -> None:
    config = load_config(REPO / "config" / "pipeline.toml")
    assert nr.TOLERANCE == MEDIAN_TOLERANCE
    assert nr.CORRELATION_MIN == CORRELATION_MIN
    assert nr.CORRELATION_MIN_ROWS == CORRELATION_MIN_ROWS
    assert nr.MIN_PIXELS == config.verify.min_clear_pixels
    assert nr.COLLECTION == config.stac.collection == "sentinel-2-c1-l2a"
    assert config.aoi.operation_epsg == 32750
    assert nr.REPRO_ATOL == 1e-6
    assert (nr.MIN_FAILING, nr.MIN_ROWS, nr.MIN_PASSES) == (4, 100, 6)
    assert nr.SHARE_W == nr.SHARE_I == Fraction(95, 100)
    assert nr.COVERAGE == Fraction(1, 2)
    assert nr.EXPLAINED == Fraction(3, 4)
    assert (nr.H3_MIN_PAIRS, nr.H3_RATIO, nr.H3_FLOOR) == (10, 2, 0.005)


def test_output_paths_columns_and_statuses() -> None:
    research = REPO / "docs" / "research"
    assert nr.NOMINATION_CSV == research / "2026-11-12-ndvi-nbart-nomination.csv"
    assert nr.NOMINATION_TXT == research / "2026-11-12-ndvi-nbart-nomination.txt"
    assert nr.ROWS_CSV == research / "2026-11-12-ndvi-nbart-rows.csv"
    assert nr.ROWS_TXT == research / "2026-11-12-ndvi-nbart-rows.txt"
    assert nr.COLUMNS == tuple(f.name for f in dataclasses.fields(nr.Row))
    columns = list(nr.COLUMNS)
    assert columns.index("recorded_reason") == columns.index("recorded_n_compared") + 1
    assert nr.STATUSES[0] == "scored"
    assert "not_in_sample" in nr.STATUSES
    assert nr.UNITS == "reflectance and NDVI unitless"


def test_conditioning_grid_and_threshold() -> None:
    assert nr.G_GRID == tuple(Fraction(m, 1000) for m in range(2, 11))
    assert float(nr.G_GRID[0]) == 0.002
    assert float(nr.G_GRID[-1]) == 0.010
    assert nr.CONDITIONING_FACTOR == 40
    for g in nr.G_GRID:
        assert nr.s_star(g) == 40 * g
    assert nr.s_star(Fraction(5, 1000)) == Fraction(1, 5)


# K0 ------------------------------------------------------------------------


def test_k0_matches_ndvi_median_check() -> None:
    red_dn = np.full((20, 20), 1000, dtype=np.int16)
    nir_dn = red_dn.copy()  # DEA NDVI is exactly 0
    clear = np.ones((20, 20), dtype=bool)
    above = math.nextafter(0.05, 1.0)
    below = math.nextafter(0.05, 0.0)
    for measured, expected in (
        (0.05, True),
        (-0.05, True),
        (above, False),
        (below, True),
        (0.0, True),
        (0.2, False),
    ):
        check = ndvi_median_check(measured, red_dn, nir_dn, clear, min_pixels=100)
        row = mk(stored=measured, dea=0.0, n=400)
        assert check.passed is expected
        assert nr.k0_passes(row) is expected
    # a non-trivial DEA median agrees with the check as well
    rng = np.random.default_rng(7)
    red = rng.integers(500, 3000, size=(20, 20)).astype(np.int16)
    nir = rng.integers(2000, 6000, size=(20, 20)).astype(np.int16)
    dea_median = ndvi_median_check(0.0, red, nir, clear, min_pixels=1).detail[
        "dea_ndvi_median"
    ]
    for delta in (0.05, above, below, 0.01, 0.3):
        measured = dea_median + delta
        check = ndvi_median_check(measured, red, nir, clear, min_pixels=100)
        row = mk(stored=measured, dea=check.detail["dea_ndvi_median"], n=400)
        assert nr.k0_passes(row) is check.passed


def test_row_status_matches_ndvi_median_check_scoring() -> None:
    red_dn = np.full((20, 20), 1000, dtype=np.int16)
    nir_dn = np.full((20, 20), 3000, dtype=np.int16)
    all_clear = np.ones((20, 20), dtype=bool)
    none_clear = np.zeros((20, 20), dtype=bool)
    small = np.zeros((20, 20), dtype=bool)
    small[:9, :9] = True  # 81 pixels, below 100
    cases = (
        (float("nan"), all_clear, 400),
        (0.4, none_clear, 0),
        (0.4, small, 81),
        (0.4, all_clear, 400),
    )
    for measured, clear, n_compared in cases:
        check = ndvi_median_check(measured, red_dn, nir_dn, clear, min_pixels=100)
        status = nr.row_status(measured, n_compared)
        assert (status == "scored") is (check.passed is not None)
    assert nr.row_status(0.4, 100) == "scored"
    assert nr.row_status(0.4, 99) == "skipped"
    assert nr.row_status(float("nan"), 400) == "skipped"
    assert nr.row_status(0.4, 0) == "skipped"


def test_compare_pixels_measures_over_the_compared_set() -> None:
    shape = (20, 20)
    scl = np.full(shape, 4, dtype=np.uint8)
    scl[0, :] = 9  # a cloud row, not clear
    red = np.full(shape, 0.10, dtype=np.float32)
    nir = np.full(shape, 0.30, dtype=np.float32)
    green = np.full(shape, 0.2, dtype=np.float32)
    swir = np.full(shape, 0.2, dtype=np.float32)
    inside = np.ones(shape, dtype=bool)
    inside[:, 18:] = False
    red_dn = np.full(shape, 1100, dtype=np.int16)
    nir_dn = np.full(shape, 2900, dtype=np.int16)
    red_dn[1, 0] = -999  # DEA nodata on a clear pixel inside the polygon
    measures = nr.compare_pixels(
        scl=scl,
        green=green,
        red=red,
        nir=nir,
        swir16=swir,
        inside=inside,
        red_dn=red_dn,
        nir_dn=nir_dn,
    )
    assert measures.n_inside == 20 * 18
    assert measures.n_clear == 19 * 18
    assert measures.n_dea_nodata == 1
    assert measures.n_compared == 19 * 18 - 1
    assert measures.ndvi_pipeline_same == pytest.approx(0.5, abs=1e-6)
    assert measures.ndvi_dea == pytest.approx((0.29 - 0.11) / 0.40, abs=1e-6)
    assert measures.red_pipeline == pytest.approx(0.10, abs=1e-6)
    assert measures.red_dea == pytest.approx(0.11, abs=1e-6)
    assert measures.d_red == pytest.approx(-0.01, abs=1e-6)
    assert measures.d_nir == pytest.approx(0.01, abs=1e-6)
    assert measures.band_max == pytest.approx(0.01, abs=1e-6)
    assert measures.s_pipeline == pytest.approx(0.40, abs=1e-6)
    assert measures.s_dea == pytest.approx(0.40, abs=1e-6)
    empty = nr.compare_pixels(
        scl=np.full(shape, 9, dtype=np.uint8),
        green=green,
        red=red,
        nir=nir,
        swir16=swir,
        inside=inside,
        red_dn=red_dn,
        nir_dn=nir_dn,
    )
    assert empty.n_compared == 0
    assert math.isnan(empty.ndvi_dea) and math.isnan(empty.s_dea)


# K1 ------------------------------------------------------------------------


def test_k1_split_and_band_limit() -> None:
    g = Fraction(1, 160)  # S* is exactly 0.25 and g is exactly 0.00625
    assert nr.s_star(g) == Fraction(1, 4)
    on = mk(s_dea=0.25, stored=0.30, dea=0.30 + 0.06)
    assert nr.well_conditioned(on, g)
    assert not nr.k0_passes(on)
    assert not nr.k1_passes(on, g)  # in W: keeps 0.05 and ignores the bands
    ignoring_bands = mk(s_dea=0.25, stored=0.30, dea=0.28, d_red=1.0, d_nir=1.0)
    assert nr.k1_passes(ignoring_bands, g)
    below = mk(s_dea=math.nextafter(0.25, 0.0), stored=0.0, dea=0.5)
    assert not nr.well_conditioned(below, g)
    limit = Fraction(1, 256)  # exactly 0.00390625
    just_above = math.nextafter(1 / 256, 1.0)
    for d_red, d_nir, expected in (
        (1 / 256, 0.0, True),
        (-1 / 256, 0.0, True),
        (0.0, 1 / 256, True),
        (0.0, -1 / 256, True),
        (just_above, 0.0, False),
        (-just_above, 0.0, False),
        (0.0, just_above, False),
        (0.0, -just_above, False),
        (0.0, 0.0, True),
    ):
        row = mk(s_dea=0.01, stored=0.9, dea=0.0, d_red=d_red, d_nir=d_nir)
        assert nr.bands_within(row, limit) is expected
        assert nr.k1_passes(row, limit) is expected  # K0 would fail every row here


def test_band_limit_is_an_exact_rational_comparison() -> None:
    g = Fraction(6, 1000)
    assert Fraction(float(g)) > g  # float(0.006) lies above 6/1000
    at_limit = _floor_float(g)
    assert nr.bands_within(mk(d_red=at_limit), g)
    assert not nr.bands_within(mk(d_red=float(g)), g)
    assert not nr.bands_within(mk(d_red=math.nextafter(at_limit, 1.0)), g)
    threshold = nr.s_star(g)
    assert nr.well_conditioned(mk(s_dea=_ceil_float(threshold)), g)
    assert not nr.well_conditioned(
        mk(s_dea=_floor_float(threshold - Fraction(1, 10**12))), g
    )


# candidates over passes ----------------------------------------------------


def test_k1_scores_every_row_k0_scores() -> None:
    rows = [
        mk(polygon="ramsar-1", s_dea=1.0),
        mk(polygon="ramsar-2", s_dea=0.05, stored=0.9, dea=0.0, d_red=0.001),
        mk(polygon="ramsar-3", status="skipped"),
        mk(polygon="ramsar-4", status="read_error"),
        mk("2026-09-17", polygon="ramsar-5", status="no_dea_item"),
    ]
    seen: dict[str, set[tuple[str, str, str]]] = {"k0": set(), "k1": set()}

    def record(name: str, verdict: Callable[[Any], bool]) -> Callable[[Any], bool]:
        def recording(row: Any) -> bool:
            seen[name].add(_row_key(row))
            return verdict(row)

        return recording

    nr.pass_failures(rows, record("k0", nr.k0_passes))
    nr.pass_failures(rows, record("k1", lambda row: nr.k1_passes(row, G)))
    scored = {_row_key(row) for row in rows if row.status == "scored"}
    assert seen["k0"] == seen["k1"] == scored
    assert nr.pass_failures(rows, nr.k0_passes) == {"2026-09-12": True}
    assert nr.pass_failures(rows, lambda row: nr.k1_passes(row, G)) == {
        "2026-09-12": False
    }


@pytest.mark.parametrize("status", ["grid_differs", "crs_differs"])
def test_grid_difference_fails_every_candidate(status: str) -> None:
    rows = [
        mk(polygon=f"ramsar-{i}", stored=0.3 + i / 100, dea=0.3 + i / 100)
        for i in range(8)
    ]
    assert nr.pass_failures(rows, nr.k0_passes) == {"2026-09-12": False}
    rows.append(mk(polygon="ramsar-99", status=status))
    assert nr.pass_failures(rows, nr.k0_passes) == {"2026-09-12": True}
    for g in nr.G_GRID:
        verdict = lambda row, g=g: nr.k1_passes(row, g)  # noqa: E731  # bound per g
        assert nr.pass_failures(rows, verdict) == {"2026-09-12": True}
    assert nr.pass_failures(rows, lambda row: True) == {"2026-09-12": True}


# correlation ---------------------------------------------------------------


def _correlation_rows(stored: list[float], dea: list[float]) -> list[Any]:
    return [
        mk(polygon=f"ramsar-{i}", stored=s, dea=d)
        for i, (s, d) in enumerate(zip(stored, dea, strict=True))
    ]


def test_pass_correlation_rule() -> None:
    stored = [0.50, 0.51, 0.50, 0.51, 0.50]
    dea = [0.51, 0.50, 0.51, 0.50, 0.51]  # every row within 0.05, r = -1
    rows = _correlation_rows(stored, dea)
    check = ndvi_correlation_check(stored, dea)
    assert check.passed is False and check.measured is not None
    assert check.measured <= 0.95
    assert all(nr.k0_passes(row) for row in rows)
    assert nr.pass_failures(rows, nr.k0_passes) == {"2026-09-12": True}
    assert nr.pass_correlation(rows) == check.measured
    # fewer than 5 rows: the check is skipped and the pass does not fail
    assert nr.pass_failures(rows[:4], nr.k0_passes) == {"2026-09-12": False}
    assert nr.pass_correlation(rows[:4]) is None
    good = _correlation_rows([0.1, 0.2, 0.3, 0.4, 0.5], [0.11, 0.21, 0.29, 0.41, 0.5])
    assert nr.pass_failures(good, nr.k0_passes) == {"2026-09-12": False}
    assert nr.pass_correlation(good) == pytest.approx(
        ndvi_correlation_check(
            [0.1, 0.2, 0.3, 0.4, 0.5], [0.11, 0.21, 0.29, 0.41, 0.5]
        ).measured
    )


def test_constant_values_skip_the_correlation_check() -> None:
    rows = _correlation_rows([0.5] * 5, [0.5] * 5)
    assert ndvi_correlation_check([0.5] * 5, [0.5] * 5).passed is None
    assert nr.pass_correlation(rows) is None
    assert nr.pass_failures(rows, nr.k0_passes) == {"2026-09-12": False}
    constant_stored = _correlation_rows([0.5] * 6, [0.50, 0.51, 0.52, 0.53, 0.50, 0.49])
    assert nr.pass_failures(constant_stored, nr.k0_passes) == {"2026-09-12": False}


# nominate ------------------------------------------------------------------


def _nomination_rows() -> list[Any]:
    rows = [
        mk(polygon=f"ramsar-{i}", s_dea=1.0, stored=0.4, dea=0.41, sample="nomination")
        for i in range(10)
    ]
    rows.append(
        mk(
            polygon="ramsar-90",
            s_dea=0.2,
            stored=0.4,
            dea=0.5,
            d_red=_floor_float(Fraction(6, 1000)),
            sample="nomination",
        )
    )
    return rows


def test_nominate_smallest_admissible() -> None:
    result = nr.nominate(_nomination_rows())
    assert result.g == Fraction(6, 1000)
    by_g = {entry.g: entry for entry in result.table}
    assert tuple(by_g) == nr.G_GRID
    at_005 = by_g[Fraction(5, 1000)]
    assert at_005.s_star == Fraction(1, 5)
    assert at_005.n_w == 11 and not at_005.n1
    at_006 = by_g[Fraction(6, 1000)]
    assert at_006.n_w == 10 and at_006.n_i == 1
    assert at_006.n1 and at_006.n2 and at_006.n3
    assert at_006.w_share == 1 and at_006.i_share == 1
    assert at_006.coverage == Fraction(10, 11)
    assert all(by_g[g].n1 and by_g[g].n2 and by_g[g].n3 for g in nr.G_GRID[4:])


def test_nominate_none_when_no_g_admissible() -> None:
    rows = [
        mk(polygon=f"ramsar-{i}", s_dea=1.0, sample="nomination") for i in range(10)
    ]
    rows.append(mk(polygon="ramsar-90", s_dea=0.05, d_red=0.05, sample="nomination"))
    result = nr.nominate(rows)
    assert result.g is None
    assert len(result.table) == len(nr.G_GRID)
    assert not any(entry.n2 for entry in result.table)


def test_nominate_requires_nonempty_i() -> None:
    rows = [
        mk(polygon=f"ramsar-{i}", s_dea=1.0, sample="nomination") for i in range(10)
    ]
    result = nr.nominate(rows)
    assert result.g is None
    for entry in result.table:
        assert entry.n_i == 0 and not entry.n2
        assert entry.n1 and entry.n3  # the other two hold, N2 alone refuses
    assert nr.nominate([]).g is None


def test_nominate_ignores_unscored_rows() -> None:
    rows = _nomination_rows() + [
        mk(polygon="ramsar-91", status="skipped", s_dea=0.01, sample="nomination"),
        mk(polygon="ramsar-92", status="read_error", sample="nomination"),
    ]
    assert nr.nominate(rows).g == Fraction(6, 1000)


# decide --------------------------------------------------------------------


def test_decide_adopts_k1_only_when_all_hold() -> None:
    decision = nr.decide(fixture(), G)
    assert decision.outcome == "K1"
    assert not decision.inconclusive
    assert tuple(decision.criteria) == ("A0", "A1", "A2", "A3", "A4", "A5")
    assert all(c.met for c in decision.criteria.values())


@pytest.mark.parametrize(
    ("criterion", "counts"),
    [
        ("A1", {"w_pass": _spread(569), "w_fail": _first(31)}),
        ("A2", {"if_within": _spread(76), "if_outside": _first(26)}),
        ("A3", {"ip_within": _spread(449), "ip_outside": _first(31)}),
        ("A4", {"w_pass": _spread(594), "w_fail": _each(1)}),
        ("A5", {"ip_within": _spread(500)}),
    ],
)
def test_flipping_one_criterion_gives_k0(
    criterion: str, counts: dict[str, list[int]]
) -> None:
    decision = nr.decide(fixture(**counts), G)
    assert decision.outcome == "K0"
    assert not decision.inconclusive
    not_met = [name for name, c in decision.criteria.items() if not c.met]
    assert not_met == [criterion]


def test_a0_failure_is_inconclusive_k0() -> None:
    five_passes = [row for row in fixture() if row.pass_date != DATES[5]]
    decision = nr.decide(five_passes, G)
    assert decision.outcome == "K0" and decision.inconclusive
    assert not decision.criteria["A0"].met
    few_rows = fixture()[:99]
    small = nr.decide(few_rows, G)
    assert small.outcome == "K0" and small.inconclusive
    assert not small.criteria["A0"].met


def test_a2_is_untestable_below_four_failing_rows() -> None:
    rows = fixture(if_within=_first(3), ip_within=_spread(579))
    failing = [row for row in rows if not nr.k0_passes(row)]
    assert len(failing) == 3
    decision = nr.decide(rows, G)
    a2 = decision.criteria["A2"]
    assert not a2.met and a2.untestable
    assert decision.outcome == "K0"
    four = nr.decide(fixture(if_within=_first(4), ip_within=_spread(578)), G)
    assert four.criteria["A2"].met and not four.criteria["A2"].untestable


def test_decide_without_g_is_k0() -> None:
    decision = nr.decide(fixture(), None)
    assert decision.outcome == "K0"
    assert decision.reason == "K1 not nominated"
    assert decision.criteria == {}
    assert not decision.inconclusive


def test_decide_counts_only_scored_rows() -> None:
    rows = fixture()
    extra = [
        mk(DATES[0], polygon="ramsar-9001", status="skipped", s_dea=1.0, stored=9.0),
        mk(DATES[1], polygon="ramsar-9002", status="read_error"),
    ]
    assert nr.decide(rows + extra, G).criteria == nr.decide(rows, G).criteria


# reproduction gate ---------------------------------------------------------


def test_reproduction_gate() -> None:
    results = nr.reproduction(seen_gate_rows())
    assert len(results) == 8
    assert all(ok for _, ok, _ in results)

    def first_row_fails(**over: Any) -> bool:
        rows = seen_gate_rows()
        rows[0] = dataclasses.replace(rows[0], **over)
        outcomes = [ok for _, ok, _ in nr.reproduction(rows)]
        assert outcomes[1:] == [True] * 7
        return not outcomes[0]

    assert not first_row_fails(ndvi_stored=0.1 + 5e-7)
    assert first_row_fails(ndvi_stored=0.1 + 2e-6)
    assert first_row_fails(recorded_ndvi_dea=0.2 + 2e-6)
    assert not first_row_fails(recorded_ndvi_dea=0.2 + 5e-7)
    assert first_row_fails(recorded_n_compared=1001)
    assert first_row_fails(recorded_n_compared=999)
    assert first_row_fails(recorded_dea_served=False, recorded_dea_maturity="final")
    assert not first_row_fails(recorded_dea_served=False, recorded_dea_maturity="nrt")
    assert not first_row_fails(
        recorded_dea_served=False,
        recorded_dea_maturity="nrt",
        recorded_ndvi_dea=None,
        recorded_n_compared=None,
    )
    assert first_row_fails(
        recorded_dea_served=False, recorded_dea_maturity="nrt", ndvi_stored=0.3
    )
    for status in ("skipped", "no_dea_item", "crs_differs", "grid_differs"):
        assert not first_row_fails(status=status)
        assert first_row_fails(status=status, ndvi_stored=0.3)
    assert first_row_fails(status="no_dea_item", recorded_n_compared=3)
    assert first_row_fails(status="read_error", reason="OSError: x")
    assert first_row_fails(status="rejected_by_discover")
    message = nr.reproduction(seen_gate_rows(status="read_error", reason="boom"))[0][2]
    assert "boom" in message


def test_reproduction_gate_fails_for_a_missing_row() -> None:
    results = nr.reproduction(seen_gate_rows()[1:])
    assert len(results) == 8
    row, ok, message = results[0]
    assert row is None and not ok
    assert nr.SEEN_FAILING[0][2] in message
    assert [ok for _, ok, _ in results[1:]] == [True] * 7


def test_report_match_uses_the_gate_rule() -> None:
    row = seen_gate_rows()[0]
    assert nr.report_match(row) is True
    assert nr.report_match(dataclasses.replace(row, recorded_n_compared=3)) is False
    assert nr.report_match(dataclasses.replace(row, status="skipped")) is True
    assert nr.report_match(dataclasses.replace(row, status="read_error")) is False
    assert nr.report_match(dataclasses.replace(row, report_ndvi_median=None)) is None


# committed records ---------------------------------------------------------


def _report_rows(stamp: str) -> tuple[str, list[tuple[str, str, str]], set[str]]:
    path = REPO / "docs" / "research" / f"2026-11-12-issue-2-repro-{stamp}.json"
    data = json.loads(path.read_text())
    date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    failing = []
    items = set()
    for check in data["checks"]:
        detail = check["detail"]
        if check["name"] != "ndvi_vs_dea_nbart":
            continue
        if not detail.get("polygon_id", "").startswith("ramsar-"):
            continue
        items.add(detail["item"])
        if check["passed"] is False:
            failing.append((date, detail["item"], detail["polygon_id"]))
    return date, failing, items


def test_seen_rows_match_committed_reports() -> None:
    failing: list[tuple[str, str, str]] = []
    sample: dict[str, set[str]] = {}
    for stamp in ("20261029", "20261111"):
        date, rows, items = _report_rows(stamp)
        failing += rows
        sample[date] = items
    assert sorted(nr.SEEN_FAILING) == sorted(failing)
    assert len(nr.SEEN_FAILING) == 8
    assert {d: set(ids) for d, ids in nr.SEEN_SAMPLE.items()} == sample
    assert tuple(nr.REPORTS) == ("2026-10-29", "2026-11-11")
    assert all(path.is_file() for path in nr.REPORTS.values())
    assert sum(len(ids) for ids in nr.SEEN_SAMPLE.values()) == 8


def test_confirm_sample_matches_preregistration() -> None:
    text = LEARNINGS.read_text()
    section = text[text.index("## Pre-registered hypotheses (st-da75") :]
    start = section.index("Confirmatory sample, fixed")
    end = section.index("Decision rule, on the scored confirmatory rows")
    ids = re.findall(r"S2[ABC]_T50[A-Z]{3}_\d{8}T\d{6}_L2A", section[start:end])
    assert len(ids) == 32
    by_date: dict[str, list[str]] = {}
    for item_id in ids:
        by_date.setdefault(nr.pass_date_of(item_id), []).append(item_id)
    assert set(nr.CONFIRM_SAMPLE) == {
        "2026-09-12",
        "2026-09-17",
        "2026-10-02",
        "2026-10-12",
        "2026-10-27",
        "2026-01-30",
        "2026-04-30",
        "2026-07-29",
    }
    assert {d: sorted(v) for d, v in nr.CONFIRM_SAMPLE.items()} == {
        d: sorted(v) for d, v in by_date.items()
    }
    seen = {item for ids_ in nr.SEEN_SAMPLE.values() for item in ids_}
    assert not seen & set(ids)


# CSV -----------------------------------------------------------------------


def _same(first: Any, second: Any) -> bool:
    for field in dataclasses.fields(first):
        x, y = getattr(first, field.name), getattr(second, field.name)
        if isinstance(x, float) and math.isnan(x):
            if not (isinstance(y, float) and math.isnan(y)):
                return False
        elif x != y or type(x) is not type(y):
            return False
    return True


def test_csv_round_trip(tmp_path: Path) -> None:
    rows = fixture(w_pass=_spread(12), w_fail=_first(1), if_within=_spread(6))[:30]
    rows += [
        mk(
            polygon="ramsar-7",
            status="skipped",
            reason='fewer than 100, "quoted", with a comma\nand a newline',
            stored=float("nan"),
            dea=float("nan"),
            s_dea=0.1 + 0.2,
            d_red=-0.0,
            report_passed=False,
            recorded_dea_served=True,
            recorded_reason='recorded item EPSG 32749, "quoted", with a comma',
            seen_failing=True,
            matches_report=None,
        ),
        nr.Row(
            sample="nomination",
            pass_date="2026-11-11",
            item_id="S2B_T50HLK_20261111T022009_L2A",
            tile="50HLK",
            polygon_id="",
            status="not_returned",
            reason="not returned by discover",
        ),
    ]
    path = tmp_path / "rows.csv"
    nr.write_rows(path, rows)
    text = path.read_text()
    assert "nan" in text and "true" in text and "false" in text
    loaded = nr.load_rows(path)
    assert len(loaded) == len(rows)
    for original, reloaded in zip(rows, loaded, strict=True):
        assert _same(original, reloaded)
    with path.open(newline="") as handle:
        assert tuple(next(csv.reader(handle))) == nr.COLUMNS
    assert loaded[-1].ndvi_stored is None
    assert nr.decide(loaded, G) == nr.decide(rows, G)
    assert nr.nominate(loaded) == nr.nominate(rows)
    assert nr.build_report(loaded, loaded) == nr.build_report(rows, rows)


# reports -------------------------------------------------------------------


def _gate_nomination_rows(**over: Any) -> list[Any]:
    """Eight reproduced seen rows plus well-conditioned rows: no g admissible."""
    rows = seen_gate_rows(s_dea=1.0, **over)
    rows += [
        mk(
            "2026-10-29",
            polygon=f"ramsar-{40 + i}",
            sample="nomination",
            s_dea=1.0,
            report_ndvi_median=0.5,
            report_dea_ndvi_median=0.5,
            report_n_compared=500,
            recorded_dea_served=True,
            recorded_ndvi_dea=0.5,
            recorded_n_compared=500,
        )
        for i in range(3)
    ]
    return rows


def _g_nomination_rows() -> list[Any]:
    """The reproduced rows plus ill-conditioned rows that nominate g = 0.002."""
    rows = _gate_nomination_rows()
    rows += [
        mk(
            "2026-11-11",
            polygon=f"ramsar-{60 + i}",
            sample="nomination",
            s_dea=0.05,
            d_red=0.001,
            stored=0.2 + i / 100,
            dea=0.3 + i / 100,
        )
        for i in range(3)
    ]
    return rows


def test_reports_deterministic_and_carry_outcome_line() -> None:
    nomination = _g_nomination_rows()
    assert nr.nominate(nomination).g == Fraction(2, 1000)
    confirm = fixture()
    first = nr.build_report(confirm, nomination)
    assert first == nr.build_report(list(confirm), list(nomination))
    assert nr.build_nomination_report(nomination) == nr.build_nomination_report(
        list(nomination)
    )
    assert re.search(r"^NDVI row rule: (K0|K1)$", first, re.MULTILINE)
    for name in ("A0", "A1", "A2", "A3", "A4", "A5", "H1", "H2", "H3", "H4"):
        assert name in first
    assert "context only, not a decision input" in first
    assert re.search(r"\d{2}:\d{2}:\d{2}", first) is None  # no timestamps


def test_report_names_k1_and_its_parameters() -> None:
    nomination = _g_nomination_rows()
    assert nr.nominate(nomination).g == Fraction(2, 1000)
    text = nr.build_report(fixture(), nomination)
    assert re.search(r"^NDVI row rule: K1$", text, re.MULTILINE)
    assert "NDVI row parameters: g = 0.002, S* = 0.08" in text.splitlines()
    assert "NDVI row rule: K0" not in text


def test_report_k0_line_when_a_criterion_fails() -> None:
    nomination = _g_nomination_rows()
    text = nr.build_report(fixture(ip_within=_spread(500)), nomination)
    assert re.search(r"^NDVI row rule: K0$", text, re.MULTILINE)
    assert "NDVI row parameters" not in text


def test_report_for_a_nomination_that_names_no_g() -> None:
    nomination = _gate_nomination_rows()
    assert nr.nominate(nomination).g is None
    confirm = fixture()
    text = nr.build_report(confirm, nomination)
    assert text == nr.build_report(confirm, nomination)
    assert re.search(r"^NDVI row rule: K0$", text, re.MULTILINE)
    assert "K1 not nominated" in text
    assert "NDVI row parameters" not in text
    for name in ("A0:", "A1:", "A2:", "A3:", "A4:", "A5:"):
        assert name not in text
    for name in ("H1", "H2", "H3", "H4"):
        assert name in text
    assert "Nominated g: none" in text
    assert "K0 failing passes" in text


def test_nomination_report_contents() -> None:
    nomination = _g_nomination_rows()
    text = nr.build_nomination_report(nomination)
    assert "Reproduction: pass" in text.splitlines()
    assert "Nominated g: 0.002" in text.splitlines()
    assert "H2" in text
    for _, _, polygon in nr.SEEN_FAILING:
        assert polygon in text
    assert "Nominated g: not computed" not in text
    assert "K1(0.002) failing passes" in text
    assert "== Candidate g over the scored nomination rows ==" in text
    failed = nr.build_nomination_report(seen_gate_rows(recorded_n_compared=5))
    assert "Reproduction: fail" in failed.splitlines()
    assert "Nominated g: none" in nr.build_nomination_report(_gate_nomination_rows())
    dropped = nomination + [
        mk(
            polygon="ramsar-77",
            sample="nomination",
            status="skipped",
            reason="fewer than 100 compared pixels",
        )
    ]
    assert "fewer than 100 compared pixels" in nr.build_nomination_report(dropped)
    assert "no timestamps" not in text
    assert re.search(r"\d{2}:\d{2}:\d{2}", text) is None


# hypotheses ----------------------------------------------------------------


def _verdicts(
    nomination: list[Any],
    confirm: list[Any] | None = None,
    g: Fraction | None = G,
) -> dict[str, str]:
    confirm = confirm if confirm is not None else fixture()
    decision = nr.decide(confirm, g)
    result = nr.hypotheses(nomination, confirm, g, decision)
    return {name: hypothesis.verdict for name, hypothesis in result.items()}


def test_hypothesis_h1_follows_a1_and_a2() -> None:
    nomination = seen_gate_rows()
    assert _verdicts(nomination)["H1"] == "supported"
    explained = fixture(w_pass=_spread(569), w_fail=_first(31))
    assert _verdicts(nomination, explained)["H1"] == "not supported"  # A1 fails
    assert _verdicts(nomination, g=None)["H1"] == "not supported"
    flipped = fixture(if_within=_spread(76), if_outside=_first(26))
    assert _verdicts(nomination, flipped)["H1"] == "not supported"  # A2 fails
    untestable = fixture(if_within=_first(3), ip_within=_spread(579))
    assert _verdicts(nomination, untestable)["H1"] == "not supported"


def _h2_rows(*, same_gap: float, stored_gap: float = 0.08) -> list[Any]:
    out = []
    for row in seen_gate_rows():
        if row.pass_date == "2026-11-11" and row.polygon_id == "ramsar-13":
            row = dataclasses.replace(
                row,
                ndvi_stored=0.4 + stored_gap,
                ndvi_dea=0.4,
                ndvi_pipeline_same=0.4 + same_gap,
            )
        out.append(row)
    return out


def _ramsar_13_index(rows: list[Any]) -> int:
    return next(
        i
        for i, row in enumerate(rows)
        if row.pass_date == "2026-11-11" and row.polygon_id == "ramsar-13"
    )


def test_hypothesis_h2_paths() -> None:
    assert _verdicts(_h2_rows(same_gap=0.01))["H2"] == "supported"
    assert _verdicts(_h2_rows(same_gap=0.08))["H2"] == "not supported"
    # abs_diff must also be above 0.05
    assert _verdicts(_h2_rows(same_gap=0.01, stored_gap=0.04))["H2"] == "not supported"
    rows = _h2_rows(same_gap=0.01)
    index = _ramsar_13_index(rows)
    rows[index] = dataclasses.replace(rows[index], status="skipped")
    assert _verdicts(rows)["H2"] == "untestable"
    del rows[index]
    assert _verdicts(rows)["H2"] == "untestable"


def _h3_rows(pair_count: int, stored_gap: float, dea_gap: float) -> list[Any]:
    rows = []
    for i in range(pair_count):
        date = DATES[i % 5]
        polygon = f"ramsar-{i}"
        rows.append(mk(date, "50HLJ", polygon, stored=0.30, dea=0.35, n=300))
        rows.append(
            mk(
                date,
                "50HLK",
                polygon,
                stored=0.30 + stored_gap,
                dea=0.35 + dea_gap,
                n=300,
            )
        )
    return rows


def test_hypothesis_h3_paths() -> None:
    nomination = seen_gate_rows()
    assert _verdicts(nomination, _h3_rows(10, 0.02, 0.005))["H3"] == "supported"
    assert _verdicts(nomination, _h3_rows(9, 0.02, 0.005))["H3"] == "untestable"
    assert _verdicts(nomination, _h3_rows(10, 0.02, 0.015))["H3"] == "not supported"
    assert _verdicts(nomination, _h3_rows(10, 0.003, 0.0))["H3"] == "not supported"
    unequal = [
        dataclasses.replace(row, n_compared=301) if row.tile == "50HLK" else row
        for row in _h3_rows(10, 0.02, 0.005)
    ]
    assert _verdicts(nomination, unequal)["H3"] == "untestable"
    one_tile = [row for row in _h3_rows(10, 0.02, 0.005) if row.tile == "50HLJ"]
    assert _verdicts(nomination, one_tile)["H3"] == "untestable"


def _h4_rows(
    *,
    hlk: str | None = "final",
    hlj: str | None = "final",
    passing: bool = True,
    skip: str | None = None,
) -> list[Any]:
    """Seen rows where the run-day maturity per tile is set (None means no item)."""
    rows = []
    for row in seen_gate_rows():
        if row.pass_date != "2026-11-11":
            rows.append(row)
            continue
        maturity = hlk if row.tile == "50HLK" else hlj
        changed = dataclasses.replace(
            row,
            dea_maturity=maturity or "",
            ndvi_stored=0.4 if passing else 0.5,
            ndvi_dea=0.4,
        )
        if maturity is None:
            changed = dataclasses.replace(changed, status="no_dea_item")
        if skip == row.polygon_id and row.tile == "50HLJ":
            changed = dataclasses.replace(changed, status="skipped")
        rows.append(changed)
    return rows


def test_hypothesis_h4_paths() -> None:
    assert _verdicts(_h4_rows())["H4"] == "supported"
    assert _verdicts(_h4_rows(passing=False))["H4"] == "not supported"
    assert _verdicts(_h4_rows(hlk="interim", hlj="final"))["H4"] == "supported"
    # a mixed or all nrt maturity is untestable, whatever the rows say
    for hlk, hlj in (("nrt", "nrt"), ("final", "nrt"), ("nrt", "final")):
        assert _verdicts(_h4_rows(hlk=hlk, hlj=hlj))["H4"] == "untestable"
        assert (
            _verdicts(_h4_rows(hlk=hlk, hlj=hlj, passing=False))["H4"] == "untestable"
        )
    # a tile with no run-day DEA item
    assert _verdicts(_h4_rows(hlk=None))["H4"] == "untestable"
    assert _verdicts(_h4_rows(hlj=None))["H4"] == "untestable"
    # one of the four rows not scored, or absent
    assert _verdicts(_h4_rows(skip="ramsar-20"))["H4"] == "untestable"
    assert _verdicts(_h4_rows(skip="ramsar-21", passing=False))["H4"] == "untestable"
    absent = [
        row
        for row in _h4_rows()
        if not (row.polygon_id == "ramsar-21" and row.pass_date == "2026-11-11")
    ]
    assert _verdicts(absent)["H4"] == "untestable"


def test_h4_reports_the_k0_failing_share_by_maturity() -> None:
    confirm = [
        mk(DATES[0], polygon="ramsar-1", maturity="final", stored=0.9, dea=0.0),
        mk(DATES[0], polygon="ramsar-2", maturity="final"),
        mk(DATES[1], polygon="ramsar-3", maturity="nrt", stored=0.9, dea=0.0),
    ]
    decision = nr.decide(confirm, G)
    result = nr.hypotheses(seen_gate_rows(), confirm, G, decision)
    assert result["H4"].numbers["k0_failing_by_maturity"] == {
        "final": (1, 2),
        "nrt": (1, 1),
    }


# nomination_ready ----------------------------------------------------------


def test_nomination_ready_refuses() -> None:
    rows = _g_nomination_rows()
    text = nr.build_nomination_report(rows)
    assert nr.nomination_ready(rows, text) is None
    assert nr.nomination_ready(rows, text + "x") is not None
    assert nr.nomination_ready(rows, "") is not None
    unreproduced = seen_gate_rows(recorded_n_compared=5)
    message = nr.nomination_ready(
        unreproduced, nr.build_nomination_report(unreproduced)
    )
    assert message is not None and "Reproduction" in message
    assert nr.nomination_ready([], nr.build_nomination_report([])) is not None


# parser --------------------------------------------------------------------


@pytest.mark.parametrize("command", ["nominate", "confirm"])
def test_parser_requires_ramsar(command: str) -> None:
    parser = nr.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([command])
    args = parser.parse_args([command, "--ramsar", "/x/ramsar.geojson"])
    assert args.ramsar == Path("/x/ramsar.geojson")
    assert args.command == command
    with pytest.raises(SystemExit):
        parser.parse_args([])
    if command == "nominate":
        assert args.out == nr.NOMINATION_CSV
        assert args.report == nr.NOMINATION_TXT
    else:
        assert args.out == nr.ROWS_CSV
        assert args.report == nr.ROWS_TXT


def test_importing_the_script_does_no_network_or_file_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("I/O at import time")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(Path, "open", refuse)
    monkeypatch.setattr(Path, "read_text", refuse)
    monkeypatch.setattr(Path, "read_bytes", refuse)
    spec = importlib.util.spec_from_file_location("ndvi_rows_import_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ndvi_rows_import_check"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("ndvi_rows_import_check", None)
    assert module.COLLECTION == "sentinel-2-c1-l2a"
    assert module.NOMINATION_CSV.name == "2026-11-12-ndvi-nbart-nomination.csv"


# network errors and the committed nomination -------------------------------


def test_is_network_error() -> None:
    for exc in (
        OSError("x"),
        ConnectionError("x"),
        TimeoutError("x"),
        requests.RequestException("x"),
        requests.ConnectionError("x"),
        RasterioIOError("x"),
    ):
        assert nr.is_network_error(exc) is True
    for exc in (ValueError("x"), KeyError("x"), RuntimeError("x")):
        assert nr.is_network_error(exc) is False


def test_propagate_read_error() -> None:
    assert nr.propagate_read_error("nomination", True, OSError("net")) is True
    assert nr.propagate_read_error("nomination", True, ValueError("shape")) is False
    assert nr.propagate_read_error("nomination", False, OSError("net")) is False
    assert nr.propagate_read_error("confirm", True, OSError("net")) is False


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "test")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def test_nomination_committed(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "seed.txt").write_text("seed\n")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "seed")
    csv_path, txt_path = repo / "n.csv", repo / "n.txt"
    message = nr.nomination_committed(repo, [csv_path, txt_path])
    assert message is not None and "n.csv" in message  # absent
    csv_path.write_text("a,b\n")
    txt_path.write_text("report\n")
    message = nr.nomination_committed(repo, [csv_path, txt_path])
    assert message is not None and "n.csv" in message  # untracked
    _git(repo, "add", "n.csv", "n.txt")
    assert nr.nomination_committed(repo, [csv_path, txt_path]) is not None  # staged
    _git(repo, "commit", "-q", "-m", "nomination")
    assert nr.nomination_committed(repo, [csv_path, txt_path]) is None
    txt_path.write_text("report changed\n")
    message = nr.nomination_committed(repo, [csv_path, txt_path])
    assert message is not None and "n.txt" in message  # modified
    assert "n.csv" not in message
    txt_path.write_text("report\n")
    assert nr.nomination_committed(repo, [csv_path, txt_path]) is None
    txt_path.unlink()
    assert nr.nomination_committed(repo, [csv_path, txt_path]) is not None
    empty = _init_repo(tmp_path / "empty")
    (empty / "n.csv").write_text("x\n")
    assert nr.nomination_committed(empty, [empty / "n.csv"]) is not None


def _patch_outputs(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    monkeypatch.setattr(nr, "REPO", repo)
    for name, file in (
        ("NOMINATION_CSV", "nomination.csv"),
        ("NOMINATION_TXT", "nomination.txt"),
        ("ROWS_CSV", "rows.csv"),
        ("ROWS_TXT", "rows.txt"),
    ):
        monkeypatch.setattr(nr, name, repo / file)


def _commit_nomination(repo: Path, rows: list[Any]) -> None:
    nr.write_rows(nr.NOMINATION_CSV, rows)
    nr.NOMINATION_TXT.write_text(nr.build_nomination_report(rows))
    _git(repo, "add", "nomination.csv", "nomination.txt")
    _git(repo, "commit", "-q", "-m", "nomination")


def test_confirm_refuses_an_uncommitted_nomination_before_any_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _patch_outputs(monkeypatch, repo)
    calls: list[str] = []

    def measure(sample: str, ramsar_path: Path) -> list[Any]:
        calls.append(sample)
        return []

    monkeypatch.setattr(nr, "measure", measure)
    argv = ["confirm", "--ramsar", "x.geojson"]
    assert nr.main(argv) == 2  # absent
    rows = _gate_nomination_rows()
    nr.write_rows(nr.NOMINATION_CSV, rows)
    nr.NOMINATION_TXT.write_text(nr.build_nomination_report(rows))
    assert nr.main(argv) == 2  # present and untracked
    _git(repo, "add", "nomination.csv", "nomination.txt")
    _git(repo, "commit", "-q", "-m", "nomination")
    nr.NOMINATION_TXT.write_text("edited\n")
    assert nr.main(argv) == 2  # differs from HEAD
    assert calls == []
    assert not nr.ROWS_CSV.exists() and not nr.ROWS_TXT.exists()


def test_confirm_refuses_a_failed_gate_before_any_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _patch_outputs(monkeypatch, repo)
    _commit_nomination(repo, seen_gate_rows(recorded_n_compared=5))

    def measure(sample: str, ramsar_path: Path) -> list[Any]:
        raise AssertionError("read after a failed gate")

    monkeypatch.setattr(nr, "measure", measure)
    assert nr.main(["confirm", "--ramsar", "x.geojson"]) == 2


def test_confirm_with_no_nominated_g_reads_once_and_reports_k0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _patch_outputs(monkeypatch, repo)
    _commit_nomination(repo, _gate_nomination_rows())
    calls: list[str] = []

    def measure(sample: str, ramsar_path: Path) -> list[Any]:
        calls.append(sample)
        return fixture()

    monkeypatch.setattr(nr, "measure", measure)
    assert nr.main(["confirm", "--ramsar", "x.geojson"]) == 0
    assert calls == ["confirm"]
    text = nr.ROWS_TXT.read_text()
    assert "K1 not nominated" in text
    assert re.search(r"^NDVI row rule: K0$", text, re.MULTILINE)
    assert len(nr.load_rows(nr.ROWS_CSV)) == len(fixture())


def test_confirm_writes_nothing_when_the_read_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _patch_outputs(monkeypatch, repo)
    _commit_nomination(repo, _gate_nomination_rows())

    def measure(sample: str, ramsar_path: Path) -> list[Any]:
        raise OSError("network down")

    monkeypatch.setattr(nr, "measure", measure)
    with pytest.raises(OSError, match="network down"):
        nr.main(["confirm", "--ramsar", "x.geojson"])
    assert not nr.ROWS_CSV.exists() and not nr.ROWS_TXT.exists()


def test_nominate_writes_after_measure_and_signals_the_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out, report = tmp_path / "n.csv", tmp_path / "n.txt"
    argv = [
        "nominate",
        "--ramsar",
        "x.geojson",
        "--out",
        str(out),
        "--report",
        str(report),
    ]
    good = _g_nomination_rows()
    monkeypatch.setattr(nr, "measure", lambda sample, ramsar_path: good)
    assert nr.main(argv) == 0
    assert report.read_text() == nr.build_nomination_report(good)
    assert "Reproduction: pass" in capsys.readouterr().out
    assert len(nr.load_rows(out)) == len(good)
    bad = seen_gate_rows(recorded_n_compared=5)
    monkeypatch.setattr(nr, "measure", lambda sample, ramsar_path: bad)
    assert nr.main(argv) == 1
    assert "Reproduction: fail" in report.read_text()


def test_nominate_writes_nothing_on_a_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, report = tmp_path / "n.csv", tmp_path / "n.txt"

    def measure(sample: str, ramsar_path: Path) -> list[Any]:
        raise ConnectionError("down")

    monkeypatch.setattr(nr, "measure", measure)
    argv = ["nominate", "--ramsar", "x", "--out", str(out), "--report", str(report)]
    with pytest.raises(ConnectionError, match="down"):
        nr.main(argv)
    assert not out.exists() and not report.exists()


def test_item_id_helpers() -> None:
    assert nr.tile_of("S2A_T50HLJ_20261029T021516_L2A") == "50HLJ"
    assert nr.pass_date_of("S2A_T50HLJ_20261029T021516_L2A") == "2026-10-29"


# batch b2b: review findings ------------------------------------------------


def _h3_numbers(rows: list[Any]) -> Any:
    decision = nr.decide(rows, G)
    return nr.hypotheses(seen_gate_rows(), rows, G, decision)["H3"]


def test_h3_pairs_every_two_tiles_of_a_polygon_and_pass() -> None:
    def group(n_hlk: int, n_hmk: int) -> list[Any]:
        return [
            mk("2026-09-17", "50HLJ", "ramsar-1", n=300),
            mk("2026-09-17", "50HLK", "ramsar-1", n=n_hlk),
            mk("2026-09-17", "50HMK", "ramsar-1", n=n_hmk),
        ]

    three = _h3_numbers(group(300, 300))
    assert three.numbers["n_pairs"] == 3
    only_two = _h3_numbers(group(300, 301))
    assert only_two.numbers["n_pairs"] == 1
    none = _h3_numbers(group(301, 302))
    assert none.numbers["n_pairs"] == 0
    skipped = group(300, 300)
    skipped[2] = dataclasses.replace(skipped[2], status="skipped")
    assert _h3_numbers(skipped).numbers["n_pairs"] == 1
    for result in (three, only_two):
        assert "every two scored rows" in result.detail
        assert "item_id order" in result.detail
        assert "equal n_compared" in result.detail
    supported = _h3_numbers(_h3_rows(10, 0.02, 0.005))
    assert "every two scored rows" in supported.detail


def _other_report_keys() -> list[tuple[str, str]]:
    seen = {(item, polygon) for _, item, polygon in nr.SEEN_FAILING}
    return sorted(key for key in nr.load_report_values() if key not in seen)


def _report_row(key: tuple[str, str], *, matches: bool) -> Any:
    value = nr.load_report_values()[key]
    item_id, polygon = key
    return mk(
        nr.pass_date_of(item_id),
        nr.tile_of(item_id),
        polygon,
        sample="nomination",
        item_id=item_id,
        report_ndvi_median=value.ndvi_median,
        report_dea_ndvi_median=value.dea_ndvi_median,
        report_n_compared=value.n_compared,
        matches_report=matches,
    )


def test_other_report_rows_count_every_committed_report_row() -> None:
    keys = _other_report_keys()
    assert len(keys) == 65  # the other scored ramsar rows of the two reports
    rows = _g_nomination_rows()
    rows += [_report_row(keys[0], matches=True), _report_row(keys[1], matches=False)]
    text = nr.build_nomination_report(rows)
    lines = text.splitlines()
    assert "Other report rows that match their report: 1 of 65" in lines
    absent = [f"{item} {polygon}" for item, polygon in keys[2:]]
    header = [line for line in lines if "the read did not produce" in line]
    assert len(header) == 1 and header[0].endswith(": 63")
    for entry in absent:
        assert any(line.strip() == entry for line in lines)
    for item, polygon in keys[:2]:
        assert not any(line.strip() == f"{item} {polygon}" for line in lines)
    assert nr.build_nomination_report(rows) == text


def test_other_report_rows_with_no_rows_are_all_absent() -> None:
    text = nr.build_nomination_report(_g_nomination_rows())
    assert "Other report rows that match their report: 0 of 65" in text.splitlines()
    assert any(
        "the read did not produce" in line and line.endswith(": 65")
        for line in text.splitlines()
    )


def test_failed_gate_nomination_text_computes_no_g() -> None:
    rows = seen_gate_rows(recorded_n_compared=5)
    text = nr.build_nomination_report(rows)
    lines = text.splitlines()
    assert "Reproduction: fail" in lines
    assert "Nominated g: not computed (reproduction gate failed)" in lines
    assert "Nominated g: none" not in text
    assert "== Candidate g over the scored nomination rows ==" not in text
    assert "g, S*, |W|" not in text
    assert "K1" not in text
    assert "== Rows by status ==" in text
    for key in nr.SEEN_FAILING:
        assert " ".join(key) in text
    assert "Other report rows that match their report" in text
    assert "K0 failing passes" in text
    assert "K0 failing row share" in text
    message = nr.nomination_ready(rows, text)
    assert message is not None and "Reproduction gate failed" in message


def test_confirm_refuses_when_an_output_already_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _patch_outputs(monkeypatch, repo)
    _commit_nomination(repo, _gate_nomination_rows())
    calls: list[str] = []

    def measure(sample: str, ramsar_path: Path) -> list[Any]:
        calls.append(sample)
        return fixture()

    monkeypatch.setattr(nr, "measure", measure)
    other_csv, other_txt = tmp_path / "other.csv", tmp_path / "other.txt"
    cases = {
        "ROWS_CSV": (nr.ROWS_CSV, []),
        "ROWS_TXT": (nr.ROWS_TXT, []),
        "out": (other_csv, ["--out", str(other_csv), "--report", str(other_txt)]),
        "report": (other_txt, ["--out", str(other_csv), "--report", str(other_txt)]),
    }
    for name, (target, extra) in cases.items():
        target.write_text("earlier results\n")
        assert nr.main(["confirm", "--ramsar", "x.geojson", *extra]) == 2, name
        assert str(target) in capsys.readouterr().out
        assert calls == []
        assert target.read_text() == "earlier results\n"
        target.unlink()
    assert nr.main(["confirm", "--ramsar", "x.geojson"]) == 0
    assert calls == ["confirm"]


def test_recorded_item_fields_and_gate_message_quote_the_cause() -> None:
    row = seen_gate_rows(
        recorded_ndvi_dea=None,
        recorded_n_compared=None,
        recorded_reason="recorded grid transform differs from the scene's",
    )[0]
    ok, message = nr._reproduces(row)
    assert not ok
    assert "no recorded DEA value" in message
    assert "recorded grid transform differs from the scene's" in message
    plain = dataclasses.replace(row, recorded_reason="")
    assert "no recorded DEA value" in nr._reproduces(plain)[1]


def test_load_rows_is_strict(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    nr.write_rows(path, [mk(seen_failing=True, report_passed=False)])
    with path.open(newline="") as handle:
        table = list(csv.reader(handle))
    bool_column = table[0].index("seen_failing")
    optional_column = table[0].index("report_passed")
    assert nr.load_rows(path)[0].seen_failing is True

    def rewrite(table_: list[list[str]]) -> None:
        with path.open("w", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows(table_)

    for bad in ("True", "TRUE", "1", "yes", "t", " true"):
        table[1][optional_column] = bad
        rewrite(table)
        with pytest.raises(ValueError, match="boolean"):
            nr.load_rows(path)
    for good, expected in (("true", True), ("false", False), ("", None)):
        table[1][optional_column] = good
        rewrite(table)
        assert nr.load_rows(path)[0].report_passed is expected
    table[1][bool_column] = "maybe"
    table[1][optional_column] = "true"
    rewrite(table)
    with pytest.raises(ValueError, match="boolean"):
        nr.load_rows(path)


def test_load_rows_requires_the_exact_header(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    nr.write_rows(path, [mk()])
    with path.open(newline="") as handle:
        table = list(csv.reader(handle))

    def load(header: list[str], width: int | None = None) -> None:
        body = [header, *[row[:width] for row in table[1:]]]
        with path.open("w", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows(body)
        nr.load_rows(path)

    with pytest.raises(ValueError, match="expected columns"):
        load(table[0][:-1], len(table[0]) - 1)
    with pytest.raises(ValueError, match="expected columns"):
        load([*table[0][1:], table[0][0]])
    with pytest.raises(ValueError, match="expected columns"):
        load([*table[0], "extra"])


def test_with_retries() -> None:
    assert (nr.DEA_LOOKUP_TRIES, nr.DEA_LOOKUP_DELAY_S) == (3, 5.0)
    sleeps: list[float] = []
    calls: list[int] = []

    def flaky(failures: int, error: BaseException) -> Callable[[], str]:
        calls.clear()

        def call() -> str:
            calls.append(1)
            if len(calls) <= failures:
                raise error
            return "value"

        return call

    result = nr.with_retries(
        flaky(2, OSError("blip")), delay_s=7.0, sleep=sleeps.append
    )
    assert result == "value" and len(calls) == 3 and sleeps == [7.0, 7.0]
    sleeps.clear()
    with pytest.raises(requests.ConnectionError, match="still down"):
        nr.with_retries(
            flaky(3, requests.ConnectionError("still down")), sleep=sleeps.append
        )
    assert len(calls) == 3 and sleeps == [nr.DEA_LOOKUP_DELAY_S] * 2
    sleeps.clear()
    with pytest.raises(ValueError, match="bad"):
        nr.with_retries(flaky(1, ValueError("bad")), sleep=sleeps.append)
    assert len(calls) == 1 and sleeps == []
    sleeps.clear()
    assert nr.with_retries(lambda: 5, sleep=sleeps.append) == 5 and sleeps == []
    with pytest.raises(OSError, match="again"):
        nr.with_retries(flaky(2, OSError("again")), tries=2, sleep=sleeps.append)
    assert len(calls) == 2 and len(sleeps) == 1


def test_read_dea_window_checks_both_shapes() -> None:
    class Reader:
        def read(self, href: str, window: object) -> np.ndarray:
            return np.zeros((3, 3) if href == "bad" else (2, 2))

    red, nir = nr.read_dea_window(Reader(), "red", "nir", None, (2, 2))
    assert red.shape == nir.shape == (2, 2)
    for hrefs in (("bad", "nir"), ("red", "bad")):
        with pytest.raises(ValueError, match="differ from"):
            nr.read_dea_window(Reader(), *hrefs, None, (2, 2))


# measure wiring, with fakes ------------------------------------------------

SEEN_ITEM = "S2A_T50HLJ_20261029T021516_L2A"
CONFIRM_ITEM = "S2B_T50HLJ_20260912T022111_L2A"
RECORDED_RED = "https://dea.invalid/dea-recorded/red.tif"


class FakeReader:
    """Stands in for RasterioReader: records the hrefs it is asked for."""

    def __init__(self, epsg: int = 32750) -> None:
        self.epsg = epsg
        self.opened: list[str] = []
        self.transforms: dict[str, str] = {}
        self.shapes: dict[str, tuple[int, int]] = {}

    def open_grid(self, href: str) -> Any:
        self.opened.append(href)
        return SimpleNamespace(epsg=self.epsg, transform=self.transforms.get(href, "T"))

    def read_text(self, href: str) -> str:
        return "<xml/>"

    def read(self, href: str, window10: object) -> np.ndarray:
        return np.zeros(self.shapes.get(href, (2, 2)))


def _scene(item_id: str, epsg: int = 32750) -> Any:
    return SimpleNamespace(
        item_id=item_id,
        tile=nr.tile_of(item_id),
        epsg=epsg,
        bands={
            "green": SimpleNamespace(href=f"https://es.invalid/{item_id}/green.tif")
        },
        product_metadata_href=f"https://es.invalid/{item_id}/MTD.xml",
    )


def _measures() -> Any:
    return nr.Measures(
        n_inside=600,
        n_clear=550,
        n_compared=500,
        n_dea_nodata=0,
        ndvi_pipeline_same=0.5,
        ndvi_dea=0.5,
        red_pipeline=0.1,
        nir_pipeline=0.4,
        red_dea=0.1,
        nir_dea=0.4,
        d_red=0.0,
        d_nir=0.0,
        band_max=0.0,
        s_pipeline=0.5,
        s_dea=0.5,
    )


class Wiring:
    """Fake collaborators for measure on their source modules: no network, no raster.

    A polygon is its id. A window is the polygon id in window10, so a fake read
    knows which polygon it serves.
    """

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        polygons: list[str],
        scenes: list[Any],
        rejected: list[tuple[str, str]] | None = None,
    ) -> None:
        self.polygons = [
            SimpleNamespace(polygon_id=pid, geometry=pid, geometry_4326=pid)
            for pid in polygons
        ]
        self.scenes = scenes
        self.rejected = rejected or []
        self.fail_read: dict[str, BaseException] = {}
        self.lookup_error: BaseException | None = None
        self.looked_up: list[str] = []
        self.read: list[str] = []
        self.reader = FakeReader()
        self.dea = FakeReader()
        self.nbart = SimpleNamespace(
            collection="ga_s2am_ard_3",
            item_id="dea-run-day",
            maturity="final",
            epsg=32750,
            red_href="https://dea.invalid/dea-run-day/red.tif",
            nir_href="https://dea.invalid/dea-run-day/nir.tif",
        )
        patches: dict[str, Any] = {
            "wetland_change.aoi.load_ramsar": lambda *a, **k: self.polygons,
            "wetland_change.aoi.union_bbox_4326": lambda polygons: (0.0, 0.0, 1.0, 1.0),
            "wetland_change.catalogue.search.open_client": lambda endpoint: object(),
            "wetland_change.catalogue.search.discover": self.discover,
            "wetland_change.raster.read.RasterioReader": lambda: self.reader,
            "wetland_change.raster.read.read_stack": self.read_stack,
            "wetland_change.raster.scaling.parse_product_metadata": lambda text: None,
            "wetland_change.raster.scaling.check_band_scaling": lambda band, esa: None,
            "wetland_change.stats.rasterise": lambda geometry, transform, shape: (
                np.ones(shape, dtype=bool)
            ),
            "wetland_change.stats.summarise": lambda *a, **k: SimpleNamespace(
                ndvi_median=0.5
            ),
            "wetland_change.verify.ndvi.find_nbart_item": self.find,
            "wetland_change.verify.ndvi.dea_ndvi_median": lambda red, nir, clear: (
                0.2,
                1000,
                0,
            ),
            "wetland_change.verify.wo.dea_reader": lambda: self.dea,
            "wetland_change.windows.plan_window": lambda geometry, grid: (
                SimpleNamespace(window10=geometry)
            ),
            "wetland_change.mask.clear_mask": lambda *a: np.ones((2, 2), dtype=bool),
        }
        for target, fake in patches.items():
            monkeypatch.setattr(target, fake)
        monkeypatch.setattr(nr, "compare_pixels", lambda **kwargs: _measures())
        monkeypatch.setattr(nr, "load_report_values", lambda: {})
        monkeypatch.setattr(nr, "DEA_LOOKUP_DELAY_S", 0.0)

    def discover(self, client: Any, stac: Any, **kwargs: Any) -> Any:
        date = kwargs["datetime_range"][0].date().isoformat()
        return SimpleNamespace(
            scenes=[s for s in self.scenes if nr.pass_date_of(s.item_id) == date],
            rejected=[r for r in self.rejected if nr.pass_date_of(r[0]) == date],
        )

    def read_stack(self, scene: Any, window: Any, reader: Any) -> Any:
        self.read.append(window.window10)
        error = self.fail_read.get(window.window10)
        if error is not None:
            raise error
        return SimpleNamespace(
            transform=None,
            shape=(2, 2),
            scl=None,
            green=None,
            red=None,
            nir=None,
            swir16=None,
        )

    def find(self, scene: Any, bbox: Any) -> Any:
        self.looked_up.append(scene.item_id)
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.nbart


def _by_polygon(rows: list[Any]) -> dict[str, Any]:
    return {row.polygon_id: row for row in rows if row.polygon_id}


def test_measure_refuses_another_collection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(nr, "COLLECTION", "sentinel-2-l2a")
    with pytest.raises(ValueError, match="sentinel-2-l2a"):
        nr.measure("confirm", tmp_path / "ramsar.geojson")


def test_measure_reads_the_scene_and_scores_every_polygon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wiring = Wiring(
        monkeypatch, polygons=["ramsar-1", "ramsar-2"], scenes=[_scene(CONFIRM_ITEM)]
    )
    rows = nr.measure("confirm", tmp_path / "ramsar.geojson")
    by_polygon = _by_polygon(rows)
    assert {row.status for row in by_polygon.values()} == {"scored"}
    assert wiring.looked_up == [CONFIRM_ITEM]
    assert by_polygon["ramsar-1"].dea_item == "dea-run-day"


@pytest.mark.parametrize(
    ("sample", "item", "error"),
    [
        ("confirm", CONFIRM_ITEM, ValueError("bad window")),
        ("confirm", CONFIRM_ITEM, OSError("blip")),
        ("nomination", SEEN_ITEM, OSError("blip")),
    ],
    ids=["confirm-value", "confirm-network", "nomination-unseen-network"],
)
def test_measure_gives_a_read_error_row_and_reads_the_rest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sample: str,
    item: str,
    error: BaseException,
) -> None:
    wiring = Wiring(
        monkeypatch,
        polygons=["ramsar-1", "ramsar-2", "ramsar-3"],
        scenes=[_scene(item)],
    )
    wiring.fail_read["ramsar-2"] = error
    rows = nr.measure(sample, tmp_path / "ramsar.geojson")
    by_polygon = _by_polygon(rows)
    assert by_polygon["ramsar-2"].status == "read_error"
    assert by_polygon["ramsar-2"].reason == f"{type(error).__name__}: {error}"
    assert by_polygon["ramsar-1"].status == "scored"
    assert by_polygon["ramsar-3"].status == "scored"
    assert wiring.read == ["ramsar-1", "ramsar-2", "ramsar-3"]


def test_nomination_network_error_on_a_seen_row_propagates_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wiring = Wiring(
        monkeypatch, polygons=["ramsar-1", "ramsar-15"], scenes=[_scene(SEEN_ITEM)]
    )
    wiring.fail_read["ramsar-15"] = ConnectionError("down")
    with pytest.raises(ConnectionError, match="down"):
        nr.measure("nomination", tmp_path / "ramsar.geojson")
    out, report = tmp_path / "n.csv", tmp_path / "n.txt"
    argv = ["nominate", "--ramsar", "x", "--out", str(out), "--report", str(report)]
    with pytest.raises(ConnectionError, match="down"):
        nr.main(argv)
    assert not out.exists() and not report.exists()


def test_nomination_value_error_on_a_seen_row_fails_the_gate_with_its_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wiring = Wiring(
        monkeypatch, polygons=["ramsar-1", "ramsar-15"], scenes=[_scene(SEEN_ITEM)]
    )
    wiring.fail_read["ramsar-15"] = ValueError("bad window")
    rows = nr.measure("nomination", tmp_path / "ramsar.geojson")
    seen = _by_polygon(rows)["ramsar-15"]
    assert seen.status == "read_error" and seen.seen_failing
    first_key = ("2026-10-29", SEEN_ITEM, "ramsar-15")
    assert nr.SEEN_FAILING[0] == first_key
    _, ok, message = nr.reproduction(rows)[0]
    assert not ok and "ValueError: bad window" in message
    assert _by_polygon(rows)["ramsar-1"].status == "scored"


def test_confirm_scene_lookup_failure_gives_read_error_rows_for_every_polygon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wiring = Wiring(
        monkeypatch,
        polygons=["ramsar-1", "ramsar-15"],
        scenes=[_scene(CONFIRM_ITEM)],
    )
    wiring.lookup_error = OSError("DEA down")
    rows = nr.measure("confirm", tmp_path / "ramsar.geojson")
    by_polygon = _by_polygon(rows)
    assert set(by_polygon) == {"ramsar-1", "ramsar-15"}
    for row in by_polygon.values():
        assert row.status == "read_error" and row.reason == "OSError: DEA down"
    assert wiring.read == []
    assert wiring.looked_up == [CONFIRM_ITEM] * nr.DEA_LOOKUP_TRIES


def test_nomination_scene_lookup_network_error_propagates_for_a_seen_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wiring = Wiring(
        monkeypatch, polygons=["ramsar-1", "ramsar-15"], scenes=[_scene(SEEN_ITEM)]
    )
    wiring.lookup_error = OSError("DEA down")
    with pytest.raises(OSError, match="DEA down"):
        nr.measure("nomination", tmp_path / "ramsar.geojson")
    assert wiring.looked_up == [SEEN_ITEM] * nr.DEA_LOOKUP_TRIES


def test_nomination_scene_lookup_failure_without_a_seen_row_or_network_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wiring = Wiring(monkeypatch, polygons=["ramsar-1"], scenes=[_scene(SEEN_ITEM)])
    wiring.lookup_error = OSError("DEA down")
    rows = nr.measure("nomination", tmp_path / "ramsar.geojson")
    assert _by_polygon(rows)["ramsar-1"].status == "read_error"
    wiring.polygons += [
        SimpleNamespace(polygon_id="ramsar-15", geometry="ramsar-15", geometry_4326="")
    ]
    wiring.lookup_error = ValueError("odd item")
    wiring.looked_up.clear()
    rows = nr.measure("nomination", tmp_path / "ramsar.geojson")
    by_polygon = _by_polygon(rows)
    assert by_polygon["ramsar-15"].status == "read_error"
    assert by_polygon["ramsar-15"].reason == "ValueError: odd item"
    assert wiring.looked_up == [SEEN_ITEM]  # a ValueError is not retried


def test_measure_lists_discovery_outcomes_and_never_reads_an_unlisted_scene(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extra = "S2B_T50HMJ_20260912T022111_L2A"
    rejected = "S2B_T50JLL_20260912T022111_L2A"
    missing = "S2B_T50HLK_20260912T022111_L2A"
    wiring = Wiring(
        monkeypatch,
        polygons=["ramsar-1"],
        scenes=[_scene(CONFIRM_ITEM), _scene(extra)],
        rejected=[(rejected, "cloud cover 45")],
    )
    rows = nr.measure("confirm", tmp_path / "ramsar.geojson")
    by_item = {row.item_id: row for row in rows if row.pass_date == "2026-09-12"}
    assert by_item[CONFIRM_ITEM].status == "scored"
    assert by_item[extra].status == "not_in_sample"
    assert by_item[rejected].status == "rejected_by_discover"
    assert by_item[rejected].reason == "cloud cover 45"
    assert by_item[missing].status == "not_returned"
    assert wiring.looked_up == [CONFIRM_ITEM]
    assert not any(extra in href for href in wiring.reader.opened)
    assert wiring.read == ["ramsar-1"]


@pytest.mark.parametrize(
    ("grid_epsg", "item_epsg"), [(32749, 32750), (32750, 32749)], ids=["grid", "item"]
)
def test_measure_raises_on_a_scene_guard_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, grid_epsg: int, item_epsg: int
) -> None:
    from wetland_change.pipeline import SceneGridError

    wiring = Wiring(
        monkeypatch, polygons=["ramsar-1"], scenes=[_scene(CONFIRM_ITEM, item_epsg)]
    )
    wiring.reader.epsg = grid_epsg
    with pytest.raises(SceneGridError):
        nr.measure("confirm", tmp_path / "ramsar.geojson")
    assert wiring.read == []


class RecordedWiring(Wiring):
    """The nomination of one seen row whose report names a different DEA item."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(
            monkeypatch, polygons=["ramsar-15"], scenes=[_scene(SEEN_ITEM)]
        )
        value = nr.ReportValue(
            ndvi_median=0.5,
            dea_ndvi_median=0.2,
            n_compared=1000,
            passed=False,
            dea_collection="ga_s2am_ard_3",
            dea_item="dea-recorded",
            dea_maturity="final",
        )
        monkeypatch.setattr(
            nr, "load_report_values", lambda: {(SEEN_ITEM, "ramsar-15"): value}
        )
        self.recorded = SimpleNamespace(
            epsg=32750,
            red_href=RECORDED_RED,
            nir_href=RECORDED_RED.replace("red", "nir"),
        )
        self.fetched: list[str] = []
        self.fetch_failures = 0
        monkeypatch.setattr(nr, "fetch_recorded_item", self.fetch)

    def fetch(self, collection: str, item_id: str) -> Any:
        self.fetched.append(item_id)
        if len(self.fetched) <= self.fetch_failures:
            raise requests.ConnectionError("blip")
        return self.recorded


def test_recorded_item_fetch_is_retried_and_a_served_item_is_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wiring = RecordedWiring(monkeypatch)
    wiring.fetch_failures = 2
    row = _by_polygon(nr.measure("nomination", tmp_path / "r"))["ramsar-15"]
    assert wiring.fetched == ["dea-recorded"] * 3
    assert row.recorded_dea_served is True
    assert row.recorded_ndvi_dea == 0.2 and row.recorded_n_compared == 1000
    assert row.recorded_reason == ""
    assert row.matches_report is True


def test_recorded_item_fetch_gives_up_after_the_last_try(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wiring = RecordedWiring(monkeypatch)
    wiring.fetch_failures = 99
    with pytest.raises(requests.ConnectionError):
        nr.measure("nomination", tmp_path / "r")
    assert wiring.fetched == ["dea-recorded"] * nr.DEA_LOOKUP_TRIES


def test_recorded_item_not_served_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wiring = RecordedWiring(monkeypatch)
    monkeypatch.setattr(
        nr, "fetch_recorded_item", lambda *key: wiring.fetched.append("x")
    )
    row = _by_polygon(nr.measure("nomination", tmp_path / "r"))["ramsar-15"]
    assert wiring.fetched == ["x"]
    assert row.recorded_dea_served is False


@pytest.mark.parametrize(
    ("epsg", "transform", "expected"),
    [(32749, "T", "EPSG 32749"), (32750, "OTHER", "transform")],
    ids=["epsg", "transform"],
)
def test_recorded_item_on_another_grid_records_the_cause(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    epsg: int,
    transform: str,
    expected: str,
) -> None:
    wiring = RecordedWiring(monkeypatch)
    wiring.recorded.epsg = epsg
    wiring.dea.transforms[RECORDED_RED] = transform
    rows = nr.measure("nomination", tmp_path / "r")
    row = _by_polygon(rows)["ramsar-15"]
    assert row.recorded_dea_served is True and row.recorded_ndvi_dea is None
    assert expected in row.recorded_reason
    ok, message = nr._reproduces(row)
    assert not ok and "no recorded DEA value" in message and expected in message


def test_recorded_item_read_applies_the_window_shape_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wiring = RecordedWiring(monkeypatch)
    wiring.dea.shapes[RECORDED_RED] = (3, 3)
    row = _by_polygon(nr.measure("nomination", tmp_path / "r"))["ramsar-15"]
    assert row.status == "read_error"
    assert row.reason.startswith("ValueError: DEA window shapes")
