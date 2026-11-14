"""NDVI row rule against DEA NBART: nomination and confirmation (st-da75).

Implements the st-da75 pre-registration in LEARNINGS.md, section
"Pre-registered hypotheses (st-da75, 2026-11-14)". The candidates K0 and
K1(g), the grid of g, the nomination rule N1 to N3, the decision rule A0 to A5,
the reproduction gate and the hypotheses H1 to H4 are fixed there and in the
constants below. The section is the authority where this text differs.

  uv run python docs/research/2026-11-12-ndvi-nbart-rows.py nominate --ramsar <path>
  uv run python docs/research/2026-11-12-ndvi-nbart-rows.py confirm --ramsar <path>

nominate re-reads the 8 seen scene-tiles of the two committed issue-2 reports
and writes the nomination CSV and text. confirm reads the 32 confirmatory
scene-tiles once, takes g only from the committed nomination files and writes
the rows CSV and the report. Neither command writes before its whole sample is
read, and confirm refuses before any network call when the nomination is not
committed at HEAD, differs from the committed version or records a
reproduction gate failure. confirm also refuses, before any network call, when
its rows CSV, its report or an --out or --report target already exists, because
the sample is read once; a run stopped by a network error writes no file, so
the one allowed rerun is not blocked.

Error routing. A network error (an OSError) on one of the eight seen rows of
the nomination propagates, and no file is written. A scene-level DEA lookup, DEA
grid open or recorded-item fetch failure gives read_error rows for every planned
polygon of the scene, unless the same rule makes it propagate. Every other
per-polygon error gives a read_error row. The scene guards and the Earth Search
discovery raise. The DEA item lookup and the recorded-item fetch are each tried
up to DEA_LOOKUP_TRIES times, DEA_LOOKUP_DELAY_S seconds apart, when the error is
a network error; any other error is not retried and a 404 for the recorded item
means it is not served.

--ramsar is the DBCA-010 Ramsar layer (config aoi.ramsar_path is relative and
absent in a worktree). Anonymous public reads of Earth Search and DEA only.

Only the Earth Search collection sentinel-2-c1-l2a is read. Pipeline
reflectance is DN times scale plus offset from the item's raster:bands, checked
against the ESA product XML by check_band_scaling. DEA reflectance comes from
nbart_reflectance on items that parse_nbart_item accepts. The source CRS and
the operation CRS are EPSG:32750. Reflectance and NDVI are unitless. DEA NBART
is another processing of the same acquisition and is not ground truth, so a
result here measures consistency between two processings.

Everything above `measure` is pure, except that the nomination report reads the
two committed reports. The module top level imports only the
standard library and numpy; everything else is imported inside functions, so
importing the module does no network or file I/O.
"""

import argparse
import csv
import dataclasses
import functools
import itertools
import json
import logging
import math
import re
import statistics
import subprocess
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

import numpy as np

logger = logging.getLogger(__name__)

COLLECTION: Final = "sentinel-2-c1-l2a"
REPO: Final = Path(__file__).resolve().parents[2]
RESEARCH: Final = REPO / "docs" / "research"
NOMINATION_CSV: Final = RESEARCH / "2026-11-12-ndvi-nbart-nomination.csv"
NOMINATION_TXT: Final = RESEARCH / "2026-11-12-ndvi-nbart-nomination.txt"
ROWS_CSV: Final = RESEARCH / "2026-11-12-ndvi-nbart-rows.csv"
ROWS_TXT: Final = RESEARCH / "2026-11-12-ndvi-nbart-rows.txt"
REPORTS: Final = {
    "2026-10-29": RESEARCH / "2026-11-12-issue-2-repro-20261029.json",
    "2026-11-11": RESEARCH / "2026-11-12-issue-2-repro-20261111.json",
}
RUN_ID: Final = "st-da75"
UNITS: Final = "reflectance and NDVI unitless"

SEEN_SAMPLE: Final[dict[str, tuple[str, ...]]] = {
    "2026-10-29": (
        "S2A_T50HLJ_20261029T021516_L2A",
        "S2A_T50HLK_20261029T021516_L2A",
        "S2A_T50JLL_20261029T021516_L2A",
    ),
    "2026-11-11": (
        "S2B_T50HLJ_20261111T022009_L2A",
        "S2B_T50HLK_20261111T022009_L2A",
        "S2B_T50HMK_20261111T022009_L2A",
        "S2B_T50JLL_20261111T022009_L2A",
        "S2B_T50JML_20261111T022009_L2A",
    ),
}
CONFIRM_SAMPLE: Final[dict[str, tuple[str, ...]]] = {
    "2026-09-12": (
        "S2B_T50HLJ_20260912T022111_L2A",
        "S2B_T50HLK_20260912T022111_L2A",
    ),
    "2026-09-17": (
        "S2C_T50HLJ_20260917T022244_L2A",
        "S2C_T50HLK_20260917T022244_L2A",
        "S2C_T50HMK_20260917T022244_L2A",
        "S2C_T50JLL_20260917T022244_L2A",
        "S2C_T50JML_20260917T022244_L2A",
    ),
    "2026-10-02": (
        "S2B_T50HLJ_20261002T021907_L2A",
        "S2B_T50HLK_20261002T021907_L2A",
        "S2B_T50HMK_20261002T021907_L2A",
        "S2B_T50JLL_20261002T021907_L2A",
        "S2B_T50JML_20261002T021907_L2A",
    ),
    "2026-10-12": (
        "S2B_T50HLJ_20261012T021555_L2A",
        "S2B_T50HLK_20261012T021555_L2A",
        "S2B_T50HMK_20261012T021555_L2A",
        "S2B_T50JLL_20261012T021555_L2A",
        "S2B_T50JML_20261012T021555_L2A",
    ),
    "2026-10-27": (
        "S2C_T50HLJ_20261027T022351_L2A",
        "S2C_T50HLK_20261027T022351_L2A",
        "S2C_T50HMK_20261027T022351_L2A",
        "S2C_T50JLL_20261027T022351_L2A",
        "S2C_T50JML_20261027T022351_L2A",
    ),
    "2026-01-30": (
        "S2C_T50HLJ_20260130T022322_L2A",
        "S2C_T50HLK_20260130T022322_L2A",
        "S2C_T50HMK_20260130T022322_L2A",
        "S2C_T50JLL_20260130T022322_L2A",
        "S2C_T50JML_20260130T022322_L2A",
    ),
    "2026-04-30": ("S2C_T50HMK_20260430T021807_L2A",),
    "2026-07-29": (
        "S2C_T50HLK_20260729T022253_L2A",
        "S2C_T50HMK_20260729T022253_L2A",
        "S2C_T50JLL_20260729T022253_L2A",
        "S2C_T50JML_20260729T022253_L2A",
    ),
}
# (pass_date, item_id, polygon_id) of the eight rows that failed in the reports.
SEEN_FAILING: Final[tuple[tuple[str, str, str], ...]] = (
    ("2026-10-29", "S2A_T50HLJ_20261029T021516_L2A", "ramsar-15"),
    ("2026-10-29", "S2A_T50HLJ_20261029T021516_L2A", "ramsar-20"),
    ("2026-10-29", "S2A_T50HLJ_20261029T021516_L2A", "ramsar-21"),
    ("2026-10-29", "S2A_T50HLK_20261029T021516_L2A", "ramsar-27"),
    ("2026-11-11", "S2B_T50HLK_20261111T022009_L2A", "ramsar-13"),
    ("2026-11-11", "S2B_T50HLJ_20261111T022009_L2A", "ramsar-13"),
    ("2026-11-11", "S2B_T50HLJ_20261111T022009_L2A", "ramsar-20"),
    ("2026-11-11", "S2B_T50HLJ_20261111T022009_L2A", "ramsar-21"),
)

G_GRID: Final = tuple(Fraction(m, 1000) for m in range(2, 11))
CONDITIONING_FACTOR: Final = Fraction(40)

TOLERANCE: Final = 0.05
CORRELATION_MIN: Final = 0.95
CORRELATION_MIN_ROWS: Final = 5
MIN_PIXELS: Final = 100
REPRO_ATOL: Final = 1e-6
DEA_LOOKUP_TRIES: Final = 3
DEA_LOOKUP_DELAY_S: Final = 5.0

SHARE_W: Final = Fraction(95, 100)
SHARE_I: Final = Fraction(95, 100)
COVERAGE: Final = Fraction(1, 2)
EXPLAINED: Final = Fraction(3, 4)
MIN_FAILING: Final = 4
MIN_ROWS: Final = 100
MIN_PASSES: Final = 6

H3_MIN_PAIRS: Final = 10
H3_RATIO: Final = 2
H3_FLOOR: Final = 0.005
H3_PAIR_RULE: Final = (
    "pairs are every two scored rows of one polygon and pass, taken in item_id "
    "order, on different tiles with equal n_compared"
)

STATUSES: Final = (
    "scored",
    "skipped",
    "grid_differs",
    "crs_differs",
    "read_error",
    "no_dea_item",
    "rejected_by_discover",
    "not_returned",
    "not_in_sample",
)
DIFFERENCE_STATUSES: Final = ("grid_differs", "crs_differs")
# Statuses of rows whose ndvi_stored and recorded-item values were computed, so
# the reproduction gate can test them whatever the run-day DEA item gave.
VALUED_STATUSES: Final = ("scored", "skipped", "no_dea_item", *DIFFERENCE_STATUSES)
SCENE_LEVEL_STATUSES: Final = ("rejected_by_discover", "not_returned", "not_in_sample")
H4_PASS_DATE: Final = "2026-11-11"
H2_POLYGON: Final = "ramsar-13"


@dataclass(frozen=True, slots=True)
class Row:
    """One polygon on one scene-tile, or one scene-tile when polygon_id is empty."""

    sample: str
    pass_date: str
    item_id: str
    tile: str
    polygon_id: str
    status: str
    reason: str = ""
    dea_collection: str = ""
    dea_item: str = ""
    dea_maturity: str = ""
    n_inside: int | None = None
    n_clear: int | None = None
    n_compared: int | None = None
    n_dea_nodata: int | None = None
    ndvi_stored: float | None = None
    ndvi_pipeline_same: float | None = None
    ndvi_dea: float | None = None
    abs_diff: float | None = None
    red_pipeline: float | None = None
    nir_pipeline: float | None = None
    red_dea: float | None = None
    nir_dea: float | None = None
    d_red: float | None = None
    d_nir: float | None = None
    band_max: float | None = None
    s_pipeline: float | None = None
    s_dea: float | None = None
    source_epsg: int | None = None
    dea_epsg: int | None = None
    operation_epsg: int | None = None
    units: str = UNITS
    report_ndvi_median: float | None = None
    report_dea_ndvi_median: float | None = None
    report_n_compared: int | None = None
    report_passed: bool | None = None
    recorded_dea_item: str = ""
    recorded_dea_maturity: str = ""
    recorded_dea_served: bool | None = None
    recorded_ndvi_dea: float | None = None
    recorded_n_compared: int | None = None
    recorded_reason: str = ""
    seen_failing: bool = False
    matches_report: bool | None = None


COLUMNS: Final = tuple(field.name for field in dataclasses.fields(Row))


def _kind(annotation: object) -> str:
    if annotation is str:
        return "str"
    if annotation is bool or annotation == (bool | None):
        return "bool"
    if annotation == (int | None):
        return "int"
    if annotation == (float | None):
        return "float"
    raise TypeError(f"unsupported Row field type {annotation!r}")


_KINDS: Final = {field.name: _kind(field.type) for field in dataclasses.fields(Row)}


def _encode(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _decode(kind: str, text: str) -> object:
    if kind == "str":
        return text
    if text == "":
        return None
    if kind == "bool":
        if text not in ("true", "false"):
            raise ValueError(f"not a boolean: {text!r}")
        return text == "true"
    if kind == "int":
        return int(text)
    return float(text)


def write_rows(path: Path, rows: Iterable[Row]) -> None:
    """Write rows with floats as repr, None as empty and booleans as true or false."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow([_encode(getattr(row, name)) for name in COLUMNS])


def load_rows(path: Path) -> list[Row]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path} does not have the expected columns")
        decoded: list[dict[str, Any]] = [
            {name: _decode(_KINDS[name], record[name]) for name in COLUMNS}
            for record in reader
        ]
    return [Row(**fields) for fields in decoded]


# Item ids, rows and scoring -------------------------------------------------


def tile_of(item_id: str) -> str:
    match = re.search(r"_T(\d{2}[A-Z]{3})_", item_id)
    if match is None:
        raise ValueError(f"no MGRS tile in item id {item_id!r}")
    return match.group(1)


def pass_date_of(item_id: str) -> str:
    match = re.search(r"_(\d{4})(\d{2})(\d{2})T\d{6}_", item_id)
    if match is None:
        raise ValueError(f"no acquisition date in item id {item_id!r}")
    return "-".join(match.groups())


def _natural(text: str) -> tuple[Any, ...]:
    return tuple(
        int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)
    )


def _row_order(row: Row) -> tuple[Any, ...]:
    return (row.pass_date, row.tile, row.item_id, _natural(row.polygon_id))


def _scored(rows: Iterable[Row]) -> list[Row]:
    return [row for row in rows if row.status == "scored"]


def _num(value: float | None) -> float:
    if value is None:
        raise ValueError("a scored row is missing a value")
    return value


def row_status(ndvi_stored: float, n_compared: int) -> str:
    """The scored-row rule of ndvi_median_check with min_pixels = MIN_PIXELS."""
    if not math.isfinite(ndvi_stored) or n_compared == 0 or n_compared < MIN_PIXELS:
        return "skipped"
    return "scored"


def is_network_error(exc: BaseException) -> bool:
    """True for an OSError, which covers requests.RequestException and
    rasterio.errors.RasterioIOError (both are OSError subclasses in the
    installed versions, checked when this script was written)."""
    return isinstance(exc, OSError)


def propagate_read_error(sample: str, seen_failing: bool, exc: BaseException) -> bool:
    """A network error on one of the eight seen nomination rows stops the run."""
    return sample == "nomination" and seen_failing and is_network_error(exc)


def with_retries[T](
    call: Callable[[], T],
    *,
    tries: int = DEA_LOOKUP_TRIES,
    delay_s: float = DEA_LOOKUP_DELAY_S,
    sleep: Callable[[float], object] = time.sleep,
) -> T:
    """call(), tried again after a network error, at most tries calls in all.

    A network error (is_network_error) sleeps delay_s and tries again; the last
    one is raised when every try failed. Any other error is raised at once.
    """
    for attempt in range(1, tries + 1):
        try:
            return call()
        except Exception as err:
            if not is_network_error(err) or attempt == tries:
                raise
            sleep(delay_s)
    raise ValueError(f"tries must be at least 1, got {tries}")


# Candidates -----------------------------------------------------------------


def s_star(g: Fraction) -> Fraction:
    return CONDITIONING_FACTOR * g


def well_conditioned(row: Row, g: Fraction) -> bool:
    return Fraction(_num(row.s_dea)) >= s_star(g)


def k0_passes(row: Row) -> bool:
    """The float comparison that ndvi_median_check makes."""
    return bool(abs(_num(row.ndvi_stored) - _num(row.ndvi_dea)) <= TOLERANCE)


def _k1_at(g: Fraction, row: Row) -> bool:
    return k1_passes(row, g)


def bands_within(row: Row, g: Fraction) -> bool:
    return Fraction(abs(_num(row.d_red))) <= g and Fraction(abs(_num(row.d_nir))) <= g


def k1_passes(row: Row, g: Fraction) -> bool:
    return k0_passes(row) if well_conditioned(row, g) else bands_within(row, g)


def pass_correlation(scored_rows: Sequence[Row]) -> float | None:
    """Pearson r of ndvi_stored and ndvi_dea, None when the check is skipped."""
    from wetland_change.verify.ndvi import ndvi_correlation_check

    check = ndvi_correlation_check(
        [_num(row.ndvi_stored) for row in scored_rows],
        [_num(row.ndvi_dea) for row in scored_rows],
        min_corr=CORRELATION_MIN,
        min_rows=CORRELATION_MIN_ROWS,
    )
    return None if check.passed is None else check.measured


def pass_failures(
    rows: Iterable[Row], verdict: Callable[[Row], bool]
) -> dict[str, bool]:
    """Per pass date, whether the NDVI checks alone would fail the pass.

    verdict says whether a scored row passes the candidate. A pass fails when a
    scored row fails, when a row has a DEA CRS or grid difference, or when the
    correlation check has at least 5 rows and r is 0.95 or less. A skipped
    correlation check does not fail the pass. Only passes with a scored row or
    a CRS or grid difference are listed.
    """
    by_pass: dict[str, list[Row]] = {}
    for row in rows:
        if row.status == "scored" or row.status in DIFFERENCE_STATUSES:
            by_pass.setdefault(row.pass_date, []).append(row)
    failures: dict[str, bool] = {}
    for date in sorted(by_pass):
        group = by_pass[date]
        scored_rows = _scored(group)
        verdicts = [verdict(row) for row in scored_rows]
        correlation = pass_correlation(scored_rows)
        failures[date] = (
            any(row.status in DIFFERENCE_STATUSES for row in group)
            or not all(verdicts)
            or (correlation is not None and not correlation > CORRELATION_MIN)
        )
    return failures


def _failing_passes(failures: dict[str, bool]) -> tuple[int, int]:
    return sum(failures.values()), len(failures)


# Nomination -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GridEntry:
    g: Fraction
    s_star: Fraction
    n_scored: int
    n_w: int
    n_w_pass: int
    w_share: Fraction | None
    n_i: int
    n_i_within: int
    i_share: Fraction | None
    coverage: Fraction | None
    n1: bool
    n2: bool
    n3: bool

    @property
    def admissible(self) -> bool:
        return self.n1 and self.n2 and self.n3


@dataclass(frozen=True, slots=True)
class Nomination:
    g: Fraction | None
    table: tuple[GridEntry, ...]


def _ratio(numerator: int, denominator: int) -> Fraction | None:
    return Fraction(numerator, denominator) if denominator else None


def nominate(rows: Iterable[Row]) -> Nomination:
    """The smallest g in G_GRID that meets N1, N2 and N3 on the scored rows."""
    scored = _scored(rows)
    table = []
    for g in G_GRID:
        well = [row for row in scored if well_conditioned(row, g)]
        ill = [row for row in scored if not well_conditioned(row, g)]
        n_w_pass = sum(k0_passes(row) for row in well)
        n_i_within = sum(bands_within(row, g) for row in ill)
        table.append(
            GridEntry(
                g=g,
                s_star=s_star(g),
                n_scored=len(scored),
                n_w=len(well),
                n_w_pass=n_w_pass,
                w_share=_ratio(n_w_pass, len(well)),
                n_i=len(ill),
                n_i_within=n_i_within,
                i_share=_ratio(n_i_within, len(ill)),
                coverage=_ratio(len(well), len(scored)),
                n1=n_w_pass >= SHARE_W * len(well),
                n2=len(ill) > 0 and n_i_within >= SHARE_I * len(ill),
                n3=len(well) >= COVERAGE * len(scored),
            )
        )
    chosen = next((entry.g for entry in table if entry.admissible), None)
    return Nomination(chosen, tuple(table))


# Reproduction gate ----------------------------------------------------------


def _reproduces(row: Row) -> tuple[bool, str]:
    """The gate rule for one row against its report values.

    The gate tests ndvi_stored, the recorded-item values and n_compared, not
    the run-day DEA item, so a row whose run-day status is skipped, no_dea_item,
    crs_differs or grid_differs is still tested on those values. A row that
    could not be read (read_error) or has no values fails.
    """
    if row.status not in VALUED_STATUSES:
        return False, f"not read ({row.status}): {row.reason}"
    problems = []
    if row.report_ndvi_median is None or row.ndvi_stored is None:
        problems.append("no report value for ndvi_stored")
    elif not abs(row.ndvi_stored - row.report_ndvi_median) <= REPRO_ATOL:
        problems.append(
            f"ndvi_stored {row.ndvi_stored!r} differs from report "
            f"{row.report_ndvi_median!r}"
        )
    if row.recorded_dea_served is True:
        if row.recorded_ndvi_dea is None or row.report_dea_ndvi_median is None:
            problems.append(
                "no recorded DEA value"
                + (f": {row.recorded_reason}" if row.recorded_reason else "")
            )
        elif not abs(row.recorded_ndvi_dea - row.report_dea_ndvi_median) <= REPRO_ATOL:
            problems.append(
                f"recorded DEA median {row.recorded_ndvi_dea!r} differs from report "
                f"{row.report_dea_ndvi_median!r}"
            )
        if row.recorded_n_compared != row.report_n_compared:
            problems.append(
                f"recorded n_compared {row.recorded_n_compared} differs from report "
                f"{row.report_n_compared}"
            )
    elif row.recorded_dea_served is False:
        if row.recorded_dea_maturity == "final":
            problems.append("recorded final DEA item is no longer served")
    else:
        problems.append("recorded DEA item not read")
    return (not problems), "; ".join(problems) if problems else "ok"


def report_match(row: Row) -> bool | None:
    """Whether the row reproduces its report row; None when it has none."""
    if row.report_ndvi_median is None:
        return None
    return _reproduces(row)[0]


def reproduction(rows: Iterable[Row]) -> list[tuple[Row | None, bool, str]]:
    """(row, ok, message) for each of the eight seen failing rows."""
    by_key = {(row.pass_date, row.item_id, row.polygon_id): row for row in rows}
    results: list[tuple[Row | None, bool, str]] = []
    for key in SEEN_FAILING:
        row = by_key.get(key)
        if row is None:
            results.append((None, False, f"{' '.join(key)}: row is missing"))
            continue
        ok, message = _reproduces(row)
        results.append((row, ok, message))
    return results


# Decision -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Criterion:
    name: str
    value: Fraction | int | None
    detail: str
    threshold: str
    met: bool
    untestable: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    outcome: str
    inconclusive: bool
    criteria: dict[str, Criterion]
    g: Fraction | None
    reason: str


def decide(confirm_rows: Iterable[Row], g: Fraction | None) -> Decision:
    """A0 to A5 on the scored confirmatory rows; K1 only when all are met."""
    rows = list(confirm_rows)
    if g is None:
        return Decision("K0", False, {}, None, "K1 not nominated")
    scored = _scored(rows)
    well = [row for row in scored if well_conditioned(row, g)]
    ill = [row for row in scored if not well_conditioned(row, g)]
    k0_failing = [row for row in scored if not k0_passes(row)]
    passes = {row.pass_date for row in scored}
    k0_failed_passes, n_passes = _failing_passes(pass_failures(rows, k0_passes))
    k1_failed_passes, _ = _failing_passes(
        pass_failures(rows, lambda row: k1_passes(row, g))
    )
    well_pass = sum(k0_passes(row) for row in well)
    ill_within = sum(bands_within(row, g) for row in ill)
    explained = sum(
        1 for row in k0_failing if not well_conditioned(row, g) and bands_within(row, g)
    )
    untestable = len(k0_failing) < MIN_FAILING
    criteria = [
        Criterion(
            "A0",
            len(scored),
            f"{len(scored)} scored rows on {len(passes)} passes",
            f"at least {MIN_ROWS} rows on at least {MIN_PASSES} passes",
            len(scored) >= MIN_ROWS and len(passes) >= MIN_PASSES,
        ),
        Criterion(
            "A1",
            _ratio(well_pass, len(well)),
            f"{well_pass} of {len(well)} W rows have abs_diff at most {TOLERANCE}",
            f"share at least {float(SHARE_W):.2f}",
            len(well) > 0 and well_pass >= SHARE_W * len(well),
        ),
        Criterion(
            "A2",
            _ratio(explained, len(k0_failing)),
            f"{explained} of {len(k0_failing)} K0-failing rows are in I with "
            "band_max at most g" + (" (untestable)" if untestable else ""),
            f"at least {MIN_FAILING} failing rows and share at least "
            f"{float(EXPLAINED):.2f}",
            not untestable and explained >= EXPLAINED * len(k0_failing),
            untestable,
        ),
        Criterion(
            "A3",
            _ratio(ill_within, len(ill)),
            f"{ill_within} of {len(ill)} I rows have band_max at most g",
            f"share at least {float(SHARE_I):.2f}",
            len(ill) > 0 and ill_within >= SHARE_I * len(ill),
        ),
        Criterion(
            "A4",
            k0_failed_passes - k1_failed_passes,
            f"K1 fails {k1_failed_passes} of {n_passes} passes, "
            f"K0 fails {k0_failed_passes}",
            "K1 fails strictly fewer passes than K0",
            k1_failed_passes < k0_failed_passes,
        ),
        Criterion(
            "A5",
            _ratio(len(well), len(scored)),
            f"{len(well)} of {len(scored)} scored rows are in W",
            f"share at least {float(COVERAGE):.2f}",
            len(scored) > 0 and len(well) >= COVERAGE * len(scored),
        ),
    ]
    by_name = {criterion.name: criterion for criterion in criteria}
    unmet = [name for name, criterion in by_name.items() if not criterion.met]
    outcome = "K0" if unmet else "K1"
    inconclusive = not by_name["A0"].met
    if not unmet:
        reason = "A0 to A5 are all met"
    elif inconclusive:
        reason = "A0 not met: inconclusive"
    else:
        reason = "not met: " + ", ".join(unmet)
    return Decision(outcome, inconclusive, by_name, g, reason)


# Hypotheses -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hypothesis:
    verdict: str
    detail: str
    numbers: dict[str, Any]


SUPPORTED: Final = "supported"
NOT_SUPPORTED: Final = "not supported"
UNTESTABLE: Final = "untestable"


def _seen_rows(
    rows: Iterable[Row], keys: Iterable[tuple[str, str, str]]
) -> list[Row | None]:
    by_key = {(row.pass_date, row.item_id, row.polygon_id): row for row in rows}
    return [by_key.get(key) for key in keys]


def _h2(nomination_rows: Sequence[Row]) -> Hypothesis:
    keys = [
        key for key in SEEN_FAILING if key[0] == H4_PASS_DATE and key[2] == H2_POLYGON
    ]
    found = _seen_rows(nomination_rows, keys)
    rows = [row for row in found if row is not None and row.status == "scored"]
    if len(rows) != len(keys):
        return Hypothesis(UNTESTABLE, "a ramsar-13 row of 2026-11-11 is not scored", {})
    numbers: dict[str, Any] = {}
    holds = []
    for row in rows:
        same_gap = abs(_num(row.ndvi_pipeline_same) - _num(row.ndvi_dea))
        abs_diff = abs(_num(row.ndvi_stored) - _num(row.ndvi_dea))
        numbers[row.tile] = {"same_pixel_gap": same_gap, "abs_diff": abs_diff}
        holds.append(same_gap <= TOLERANCE and not k0_passes(row))
    verdict = SUPPORTED if all(holds) else NOT_SUPPORTED
    return Hypothesis(
        verdict,
        "same-pixel gap at most 0.05 and abs_diff above 0.05 on both rows",
        numbers,
    )


def _h3(confirm_rows: Sequence[Row]) -> Hypothesis:
    groups: dict[tuple[str, str], list[Row]] = {}
    for row in _scored(confirm_rows):
        groups.setdefault((row.pass_date, row.polygon_id), []).append(row)
    pairs = [
        (first, second)
        for group in groups.values()
        for first, second in itertools.combinations(
            sorted(group, key=lambda row: row.item_id), 2
        )
        if first.tile != second.tile and first.n_compared == second.n_compared
    ]
    numbers: dict[str, Any] = {"n_pairs": len(pairs)}
    if len(pairs) < H3_MIN_PAIRS:
        return Hypothesis(
            UNTESTABLE,
            f"{len(pairs)} pairs, at least 10 needed; {H3_PAIR_RULE}",
            numbers,
        )
    stored = statistics.median(
        abs(_num(a.ndvi_stored) - _num(b.ndvi_stored)) for a, b in pairs
    )
    dea = statistics.median(abs(_num(a.ndvi_dea) - _num(b.ndvi_dea)) for a, b in pairs)
    numbers.update(median_stored_difference=stored, median_dea_difference=dea)
    holds = stored >= H3_RATIO * dea and stored >= H3_FLOOR
    return Hypothesis(
        SUPPORTED if holds else NOT_SUPPORTED,
        "median between-tile difference of ndvi_stored at least twice that of "
        f"ndvi_dea and at least 0.005; {H3_PAIR_RULE}",
        numbers,
    )


def _failing_by_maturity(rows: Iterable[Row]) -> dict[str, tuple[int, int]]:
    counts: dict[str, list[int]] = {}
    for row in _scored(rows):
        entry = counts.setdefault(row.dea_maturity, [0, 0])
        entry[1] += 1
        entry[0] += 0 if k0_passes(row) else 1
    return {name: (entry[0], entry[1]) for name, entry in sorted(counts.items())}


def _h4(nomination_rows: Sequence[Row], confirm_rows: Sequence[Row]) -> Hypothesis:
    keys = [key for key in SEEN_FAILING if key[0] == H4_PASS_DATE]
    found = _seen_rows(nomination_rows, keys)
    numbers: dict[str, Any] = {
        "k0_failing_by_maturity": _failing_by_maturity(confirm_rows)
    }
    rows = [row for row in found if row is not None and row.status == "scored"]
    if len(rows) != len(keys):
        return Hypothesis(
            UNTESTABLE,
            "a tile has no run-day DEA item or a 2026-11-11 failing row is not scored",
            numbers,
        )
    maturities = {row.tile: row.dea_maturity for row in rows}
    numbers["run_day_maturity"] = maturities
    if "nrt" in maturities.values():
        return Hypothesis(UNTESTABLE, "a run-day DEA item is still nrt", numbers)
    passing = [k0_passes(row) for row in rows]
    numbers["rows_passing_k0"] = sum(passing)
    return Hypothesis(
        SUPPORTED if all(passing) else NOT_SUPPORTED,
        "all four seen failing rows pass K0 against non-nrt run-day items",
        numbers,
    )


def hypotheses(
    nomination_rows: Iterable[Row],
    confirm_rows: Iterable[Row],
    g: Fraction | None,
    decision: Decision,
) -> dict[str, Hypothesis]:
    """H1 to H4. They are reported and are not decision inputs."""
    nomination = list(nomination_rows)
    confirm = list(confirm_rows)
    if g is None or "A1" not in decision.criteria:
        h1 = Hypothesis(NOT_SUPPORTED, "K1 not nominated", {})
    else:
        a1, a2 = decision.criteria["A1"], decision.criteria["A2"]
        h1 = Hypothesis(
            SUPPORTED if a1.met and a2.met else NOT_SUPPORTED,
            f"A1 met: {a1.met}; A2 met: {a2.met}",
            {"a1": a1.met, "a2": a2.met},
        )
    return {
        "H1": h1,
        "H2": _h2(nomination),
        "H3": _h3(confirm),
        "H4": _h4(nomination, confirm),
    }


# Reports --------------------------------------------------------------------


def _f(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _share(value: Fraction | int | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def _g_label(g: Fraction) -> str:
    return f"{float(g):.3f}"


def _s_label(g: Fraction) -> str:
    return f"{float(s_star(g)):.2f}"


def _key_label(row: Row) -> str:
    return f"{row.pass_date} {row.item_id} {row.polygon_id or '-'}"


def _status_lines(rows: Sequence[Row]) -> list[str]:
    counts = {status: 0 for status in STATUSES}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return [f"{status}: {count}" for status, count in counts.items()]


def _unscored_lines(rows: Sequence[Row]) -> list[str]:
    lines = [
        f"{_key_label(row)} {row.status}: {row.reason}"
        for row in sorted(rows, key=_row_order)
        if row.status != "scored"
    ]
    return lines or ["none"]


def _candidate_lines(
    name: str, rows: Sequence[Row], verdict: Callable[[Row], bool]
) -> list[str]:
    failed, total = _failing_passes(pass_failures(rows, verdict))
    scored = _scored(rows)
    failing_rows = sum(not verdict(row) for row in scored)
    return [
        f"{name} failing passes: {failed} of {total} "
        f"(share {_share(_ratio(failed, total))})",
        f"{name} failing row share: {failing_rows} of {len(scored)} "
        f"(share {_share(_ratio(failing_rows, len(scored)))})",
    ]


def _hypothesis_lines(result: dict[str, Hypothesis]) -> list[str]:
    return [
        f"{name}: {h.verdict}. {h.detail}. {h.numbers}" for name, h in result.items()
    ]


def _other_report_rows(rows: Sequence[Row]) -> tuple[int, int, list[tuple[str, str]]]:
    """Match count, total and unproduced keys of the other committed report rows.

    The other rows are every scored ramsar ndvi_vs_dea_nbart row of the reports
    in REPORTS outside SEEN_FAILING. A report row with no row in rows counts as
    not matching and is listed as (item id, polygon id).
    """
    seen = {(item_id, polygon_id) for _, item_id, polygon_id in SEEN_FAILING}
    produced = {(row.item_id, row.polygon_id): row for row in rows if row.polygon_id}
    keys = sorted(
        (key for key in load_report_values() if key not in seen),
        key=lambda key: (key[0], _natural(key[1])),
    )
    matched = sum(
        1 for key in keys if key in produced and produced[key].matches_report is True
    )
    return matched, len(keys), [key for key in keys if key not in produced]


def build_nomination_report(rows: Iterable[Row]) -> str:
    """The nomination text, rebuilt from the rows and the committed reports.

    The text carries no timestamps, so the same rows give the same text.
    """
    rows = sorted(rows, key=_row_order)
    results = reproduction(rows)
    gate_ok = all(ok for _, ok, _ in results)
    matched, other_total, not_produced = _other_report_rows(rows)
    out = [
        "NDVI row rule against DEA NBART: nomination (st-da75)",
        f"Collection: {COLLECTION}",
        "Source CRS and operation CRS: EPSG:32750. "
        f"Units: {UNITS}. DEA NBART is not ground truth.",
        "",
        "== Rows by status ==",
        *_status_lines(rows),
        "",
        "== Rows not scored ==",
        *_unscored_lines(rows),
        "",
        "== Reproduction of the eight seen failing rows ==",
        f"Reproduction: {'pass' if gate_ok else 'fail'}",
    ]
    for key, (row, ok, message) in zip(SEEN_FAILING, results, strict=True):
        if row is None:
            out.append(f"{' '.join(key)}: FAIL {message}")
            continue
        deviation = (
            abs(row.ndvi_stored - row.report_ndvi_median)
            if row.ndvi_stored is not None and row.report_ndvi_median is not None
            else None
        )
        recorded_deviation = (
            abs(row.recorded_ndvi_dea - row.report_dea_ndvi_median)
            if row.recorded_ndvi_dea is not None
            and row.report_dea_ndvi_median is not None
            else None
        )
        out.append(
            f"{_key_label(row)}: {'ok' if ok else 'FAIL'} "
            f"ndvi_stored={row.ndvi_stored!r} report={row.report_ndvi_median!r} "
            f"deviation={deviation!r} "
            f"recorded_dea_served={row.recorded_dea_served} "
            f"recorded_ndvi_dea={row.recorded_ndvi_dea!r} "
            f"report_dea={row.report_dea_ndvi_median!r} "
            f"deviation={recorded_deviation!r} "
            f"n_compared={row.recorded_n_compared} "
            f"report_n_compared={row.report_n_compared} "
            f"run_day_item={row.dea_item or '-'} ({row.dea_maturity or '-'}) "
            f"message={message}"
        )
    out.append(f"Other report rows that match their report: {matched} of {other_total}")
    out.append(
        "Other report rows the read did not produce, counted as not matching: "
        f"{len(not_produced)}"
    )
    out.extend(f"  {item_id} {polygon_id}" for item_id, polygon_id in not_produced)
    chosen: Fraction | None = None
    if not gate_ok:
        out.extend(["", "Nominated g: not computed (reproduction gate failed)"])
    else:
        nomination = nominate(rows)
        out.extend(
            [
                "",
                "== Candidate g over the scored nomination rows ==",
                "g, S*, |W|, W pass share, |I|, I within-g share, coverage, N1, N2, N3",
            ]
        )
        for entry in nomination.table:
            out.append(
                f"{_g_label(entry.g)}, {_s_label(entry.g)}, {entry.n_w}, "
                f"{_share(entry.w_share)}, {entry.n_i}, {_share(entry.i_share)}, "
                f"{_share(entry.coverage)}, {entry.n1}, {entry.n2}, {entry.n3}"
            )
        chosen = nomination.g
        out.append(
            f"Nominated g: {_g_label(chosen)}"
            if chosen is not None
            else "Nominated g: none"
        )
    out.extend(["", "== Failing passes and rows on the nomination passes =="])
    out.extend(_candidate_lines("K0", rows, k0_passes))
    if chosen is not None:
        out.extend(
            _candidate_lines(
                f"K1({_g_label(chosen)})", rows, lambda row: k1_passes(row, chosen)
            )
        )
    h2 = _h2(rows)
    out.extend(["", "== H2 (not a decision input) =="])
    out.extend(_hypothesis_lines({"H2": h2}))
    return "\n".join(out) + "\n"


def nomination_ready(nomination_rows: Sequence[Row], committed_text: str) -> str | None:
    """An error message when the nomination cannot be used, else None."""
    failed = [message for row, ok, message in reproduction(nomination_rows) if not ok]
    if failed:
        return "Reproduction gate failed: " + " | ".join(failed)
    if committed_text != build_nomination_report(nomination_rows):
        return "The committed nomination text does not match its rows"
    return None


def nomination_committed(repo: Path, paths: Sequence[Path]) -> str | None:
    """An error message when a path is absent, not tracked at HEAD or changed."""
    problems = []
    for path in paths:
        if not path.is_file():
            problems.append(f"{path} is absent")
            continue
        try:
            relative = path.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            problems.append(f"{path} is outside the repository {repo}")
            continue
        shown = subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:{relative}"],
            capture_output=True,
            check=False,
        )
        if shown.returncode != 0:
            problems.append(f"{path} is not tracked at HEAD")
        elif shown.stdout != path.read_bytes():
            problems.append(f"{path} differs from its HEAD version")
    return "; ".join(problems) if problems else None


def _maturity_counts(rows: Iterable[Row]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.dea_maturity] = counts.get(row.dea_maturity, 0) + 1
    return ", ".join(f"{name or 'none'}: {n}" for name, n in sorted(counts.items()))


def _pass_table(rows: Sequence[Row], g: Fraction | None) -> list[str]:
    k0 = pass_failures(rows, k0_passes)
    k1 = pass_failures(rows, lambda row: k1_passes(row, g)) if g is not None else {}
    out = ["pass_date, scored rows, K0 fail, K1 fail, r"]
    for date in k0:
        group = [row for row in _scored(rows) if row.pass_date == date]
        correlation = pass_correlation(group)
        out.append(
            f"{date}, {len(group)}, {k0[date]}, "
            f"{k1[date] if g is not None else 'n/a'}, {_f(correlation)}"
        )
    return out


def build_report(confirm_rows: Iterable[Row], nomination_rows: Iterable[Row]) -> str:
    """The confirmatory report, built from the rows alone (no timestamps)."""
    rows = sorted(confirm_rows, key=_row_order)
    nomination = sorted(nomination_rows, key=_row_order)
    g = nominate(nomination).g
    decision = decide(rows, g)
    result = hypotheses(nomination, rows, g, decision)
    scored = _scored(rows)
    read_ids = {row.item_id for row in rows if row.status not in SCENE_LEVEL_STATUSES}
    sample_size = sum(len(ids) for ids in CONFIRM_SAMPLE.values())
    out = [
        "NDVI row rule against DEA NBART: confirmatory sample (st-da75)",
        f"Collection: {COLLECTION}",
        "Source CRS and operation CRS: EPSG:32750. "
        f"Units: {UNITS}. DEA NBART is not ground truth.",
        "",
        "== Sample ==",
        f"Scene-tiles in the sample: {sample_size} on {len(CONFIRM_SAMPLE)} passes",
        f"Scene-tiles read: {len(read_ids)}",
        "Rows by status:",
        *_status_lines(rows),
        "DEA maturity of the scene-tiles read: "
        + _maturity_counts(
            {row.item_id: row for row in rows if row.item_id in read_ids}.values()
        ),
        f"DEA maturity of the scored rows: {_maturity_counts(scored)}",
        "",
        "== Dropped rows ==",
        *_unscored_lines(rows),
        "",
        "== Nominated g ==",
        f"Nominated g: {_g_label(g)}" if g is not None else "Nominated g: none",
        "",
        "== Candidates ==",
    ]
    candidates: list[tuple[str, Callable[[Row], bool]]] = [("K0", k0_passes)]
    if g is not None:
        candidates.append((f"K1({_g_label(g)})", lambda row: k1_passes(row, g)))
    for name, verdict in candidates:
        out.append(f"{name} confirmatory passes:")
        out.extend(_candidate_lines(name, rows, verdict))
        out.append(f"{name} nomination passes:")
        out.extend(_candidate_lines(name, nomination, verdict))
    out.extend(["", "== Per-pass table (confirmatory) =="])
    out.extend(_pass_table(rows, g))
    if decision.criteria:
        out.extend(["", "== Criteria =="])
        for name, criterion in decision.criteria.items():
            out.append(
                f"{name}: {criterion.detail}; value {_share(criterion.value)}; "
                f"threshold {criterion.threshold}; met: {criterion.met}"
            )
        if decision.inconclusive:
            out.append("Inconclusive: A0 is not met, so K0 stays")
    out.extend(["", "== Hypotheses (not decision inputs) =="])
    out.extend(_hypothesis_lines(result))
    out.extend(["", "== K0-failing rows =="])
    failing = [row for row in scored if not k0_passes(row)]
    out.append("pass_date item polygon, s_dea, band_max, d_red, d_nir, maturity")
    for row in failing:
        out.append(
            f"{_key_label(row)}, {_f(row.s_dea)}, {_f(row.band_max)}, "
            f"{_f(row.d_red)}, {_f(row.d_nir)}, {row.dea_maturity}"
        )
    if not failing:
        out.append("none")
    out.extend(
        ["", "== K1 pass failures at every g (context only, not a decision input) =="]
    )
    for grid_g in G_GRID:
        failed, total = _failing_passes(
            pass_failures(rows, functools.partial(_k1_at, grid_g))
        )
        out.append(
            f"g = {_g_label(grid_g)}, S* = {_s_label(grid_g)}: "
            f"{failed} of {total} passes fail"
        )
    out.extend(["", "== Outcome =="])
    out.append(f"NDVI row rule: {decision.outcome}")
    if decision.outcome == "K1" and g is not None:
        out.append(f"NDVI row parameters: g = {_g_label(g)}, S* = {_s_label(g)}")
    else:
        out.append(f"Reason: {decision.reason}")
    return "\n".join(out) + "\n"


# Pixel comparison and the network reads -------------------------------------


@dataclass(frozen=True, slots=True)
class Measures:
    n_inside: int
    n_clear: int
    n_compared: int
    n_dea_nodata: int
    ndvi_pipeline_same: float
    ndvi_dea: float
    red_pipeline: float
    nir_pipeline: float
    red_dea: float
    nir_dea: float
    d_red: float
    d_nir: float
    band_max: float
    s_pipeline: float
    s_dea: float


def compare_pixels(
    *,
    scl: np.ndarray,
    green: np.ndarray,
    red: np.ndarray,
    nir: np.ndarray,
    swir16: np.ndarray,
    inside: np.ndarray,
    red_dn: np.ndarray,
    nir_dn: np.ndarray,
) -> Measures:
    """Medians over the clear pixels that DEA also holds, as ndvi_scene_check reads."""
    from wetland_change.indices import ndvi
    from wetland_change.mask import clear_mask
    from wetland_change.verify.ndvi import (
        NBART_NODATA,
        dea_ndvi_median,
        nbart_reflectance,
    )

    clear = clear_mask(scl, green, red, nir, swir16) & inside
    dea_median, n_compared, n_nodata = dea_ndvi_median(red_dn, nir_dn, clear)
    red_dea = nbart_reflectance(red_dn)
    nir_dea = nbart_reflectance(nir_dn)
    compared = (
        clear
        & (red_dn != NBART_NODATA)
        & (nir_dn != NBART_NODATA)
        & np.isfinite(ndvi(nir_dea, red_dea))
    )
    if int(compared.sum()) != n_compared:
        raise ValueError(
            f"compared set holds {int(compared.sum())} pixels, "
            f"dea_ndvi_median counted {n_compared}"
        )
    counts = (int(inside.sum()), int(clear.sum()), n_compared, n_nodata)
    nan = float("nan")
    if n_compared == 0:
        return Measures(*counts, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan)
    pipeline_ndvi = ndvi(nir, red)[compared]
    pipeline_ndvi = pipeline_ndvi[np.isfinite(pipeline_ndvi)]
    red_pipeline = float(np.median(red[compared]))
    nir_pipeline = float(np.median(nir[compared]))
    red_reference = float(np.median(red_dea[compared]))
    nir_reference = float(np.median(nir_dea[compared]))
    d_red = red_pipeline - red_reference
    d_nir = nir_pipeline - nir_reference
    return Measures(
        *counts,
        ndvi_pipeline_same=(
            float(np.median(pipeline_ndvi)) if pipeline_ndvi.size else nan
        ),
        ndvi_dea=dea_median,
        red_pipeline=red_pipeline,
        nir_pipeline=nir_pipeline,
        red_dea=red_reference,
        nir_dea=nir_reference,
        d_red=d_red,
        d_nir=d_nir,
        band_max=max(abs(d_red), abs(d_nir)),
        s_pipeline=float(np.median(red[compared] + nir[compared])),
        s_dea=float(np.median(red_dea[compared] + nir_dea[compared])),
    )


def read_dea_window(
    dea: Any, red_href: str, nir_href: str, window10: Any, shape: tuple[int, ...]
) -> tuple[np.ndarray, np.ndarray]:
    """The DEA red and NIR digital numbers of a window, both of the given shape."""
    red_dn = dea.read(red_href, window10)
    nir_dn = dea.read(nir_href, window10)
    if red_dn.shape != shape or nir_dn.shape != shape:
        raise ValueError(
            f"DEA window shapes {red_dn.shape}, {nir_dn.shape} differ from {shape}"
        )
    return red_dn, nir_dn


def grid_difference(
    item_epsg: int, dea_epsg: int, scene_epsg: int, aligned: bool, operation_epsg: int
) -> str:
    """Why a recorded DEA item is not on the scene's grid, or an empty string."""
    if {item_epsg, dea_epsg, scene_epsg} != {operation_epsg}:
        return (
            f"recorded item EPSG {item_epsg}, recorded grid EPSG {dea_epsg}, "
            f"scene grid EPSG {scene_epsg}"
        )
    return "" if aligned else "recorded grid transform differs from the scene's"


@dataclass(frozen=True, slots=True)
class ReportValue:
    """One scored ndvi_vs_dea_nbart ramsar row of a committed report."""

    ndvi_median: float
    dea_ndvi_median: float
    n_compared: int
    passed: bool
    dea_collection: str
    dea_item: str
    dea_maturity: str


def load_report_values() -> dict[tuple[str, str], ReportValue]:
    """Report rows keyed by (item id, polygon id)."""
    values: dict[tuple[str, str], ReportValue] = {}
    for path in REPORTS.values():
        data = json.loads(path.read_text(encoding="utf-8"))
        for check in data["checks"]:
            detail = check["detail"]
            polygon = str(detail.get("polygon_id", ""))
            if check["name"] != "ndvi_vs_dea_nbart" or not polygon.startswith(
                "ramsar-"
            ):
                continue
            if check["passed"] is None:
                continue
            values[(str(detail["item"]), polygon)] = ReportValue(
                ndvi_median=float(detail["ndvi_median"]),
                dea_ndvi_median=float(detail["dea_ndvi_median"]),
                n_compared=int(detail["n_compared"]),
                passed=bool(check["passed"]),
                dea_collection=str(detail["dea_collection"]),
                dea_item=str(detail["dea_item"]),
                dea_maturity=str(detail["dea_maturity"]),
            )
    return values


def fetch_recorded_item(collection: str, item_id: str) -> Any:
    """The DEA item recorded in a report, or None when DEA no longer serves it.

    A 404 means not served. Any other failure raises, including a request error.
    """
    import requests

    from wetland_change.verify.ndvi import parse_nbart_item
    from wetland_change.verify.wo import DEA_STAC

    response = requests.get(
        f"{DEA_STAC}/collections/{collection}/items/{item_id}", timeout=60
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return parse_nbart_item(response.json())


def _scene_row(sample: str, date: str, item_id: str, status: str, reason: str) -> Row:
    return Row(
        sample=sample,
        pass_date=date,
        item_id=item_id,
        tile=tile_of(item_id),
        polygon_id="",
        status=status,
        reason=reason,
    )


def _polygon_row(
    sample: str,
    date: str,
    item_id: str,
    tile: str,
    source_epsg: int,
    operation_epsg: int,
    seen_keys: set[tuple[str, str, str]],
    report_values: dict[tuple[str, str], ReportValue],
    polygon_id: str,
    status: str,
    **fields: Any,
) -> Row:
    """A row of one polygon with the report values and the seen flag filled in."""
    report = report_values.get((item_id, polygon_id))
    known: dict[str, Any] = {}
    if report is not None:
        known = {
            "report_ndvi_median": report.ndvi_median,
            "report_dea_ndvi_median": report.dea_ndvi_median,
            "report_n_compared": report.n_compared,
            "report_passed": report.passed,
            "recorded_dea_item": report.dea_item,
            "recorded_dea_maturity": report.dea_maturity,
        }
    return Row(
        sample=sample,
        pass_date=date,
        item_id=item_id,
        tile=tile,
        polygon_id=polygon_id,
        status=status,
        source_epsg=source_epsg,
        operation_epsg=operation_epsg,
        seen_failing=(date, item_id, polygon_id) in seen_keys,
        **{**known, **fields},
    )


def measure(sample: str, ramsar_path: Path) -> list[Row]:
    """Read every scene-tile of the sample once and return its rows.

    sample is "nomination" (the eight seen scene-tiles, with the recorded DEA
    items and the report values) or "confirm". Guard failures of the scene read
    (grid, EPSG, scaling) raise. A DEA lookup, DEA grid open or recorded-item
    fetch failure, and a per-polygon read failure, give read_error rows, except
    that a network error on a seen failing nomination row raises.
    """
    from wetland_change.aoi import load_ramsar, union_bbox_4326
    from wetland_change.catalogue.search import discover, open_client
    from wetland_change.config import load_config
    from wetland_change.mask import clear_mask
    from wetland_change.pipeline import SceneGridError
    from wetland_change.raster.read import RasterioReader, read_stack
    from wetland_change.raster.scaling import check_band_scaling, parse_product_metadata
    from wetland_change.stats import rasterise, summarise
    from wetland_change.verify.ndvi import dea_ndvi_median, find_nbart_item
    from wetland_change.verify.wo import dea_reader
    from wetland_change.windows import plan_window

    if sample not in ("nomination", "confirm"):
        raise ValueError(f"sample must be nomination or confirm, got {sample!r}")
    plan = SEEN_SAMPLE if sample == "nomination" else CONFIRM_SAMPLE
    config = load_config(REPO / "config" / "pipeline.toml")
    config = config.model_copy(
        update={"aoi": config.aoi.model_copy(update={"ramsar_path": ramsar_path})}
    )
    if config.stac.collection != COLLECTION:
        raise ValueError(
            f"config collection {config.stac.collection!r} is not {COLLECTION!r}"
        )
    operation_epsg = config.aoi.operation_epsg
    polygons = load_ramsar(
        config.aoi.ramsar_path,
        site_prefixes=config.aoi.site_prefixes,
        operation_epsg=operation_epsg,
    )
    client = open_client(config.stac.endpoint)
    bbox = union_bbox_4326(polygons)
    report_values = load_report_values() if sample == "nomination" else {}
    seen_keys = set(SEEN_FAILING)
    reader = RasterioReader()
    dea = dea_reader()
    rows: list[Row] = []

    for date in sorted(plan):
        expected = plan[date]
        day = datetime.fromisoformat(date).replace(tzinfo=UTC)
        found = discover(
            client,
            config.stac,
            bbox=bbox,
            polygons_4326=[polygon.geometry_4326 for polygon in polygons],
            created_from=None,
            seen=set(),
            datetime_range=(
                day,
                day.replace(hour=23, minute=59, second=59),
            ),
        )
        rejected = dict(found.rejected)
        returned = {scene.item_id: scene for scene in found.scenes}
        for item_id, reason in sorted(rejected.items()):
            rows.append(
                _scene_row(sample, date, item_id, "rejected_by_discover", reason)
            )
        for item_id in expected:
            if item_id not in returned and item_id not in rejected:
                rows.append(
                    _scene_row(
                        sample,
                        date,
                        item_id,
                        "not_returned",
                        "discover did not return it",
                    )
                )
        for item_id in sorted(returned):
            if item_id not in expected:
                rows.append(
                    _scene_row(
                        sample,
                        date,
                        item_id,
                        "not_in_sample",
                        "returned by discover but not in the sample; not read",
                    )
                )
        for item_id in sorted(expected):
            scene = returned.get(item_id)
            if scene is None:
                continue
            grid = reader.open_grid(scene.bands["green"].href)
            if grid.epsg != operation_epsg or scene.epsg != operation_epsg:
                raise SceneGridError(
                    f"{scene.item_id}: grid EPSG {grid.epsg}, item EPSG "
                    f"{scene.epsg}, operation EPSG {operation_epsg}"
                )
            esa = parse_product_metadata(reader.read_text(scene.product_metadata_href))
            for band in scene.bands.values():
                check_band_scaling(band, esa)
            planned = [
                (polygon, window)
                for polygon in polygons
                if (window := plan_window(polygon.geometry, grid)) is not None
            ]
            base_row = functools.partial(
                _polygon_row,
                sample,
                date,
                item_id,
                scene.tile,
                grid.epsg,
                operation_epsg,
                seen_keys,
                report_values,
            )
            nbart: Any = None
            item_fields: dict[str, Any] = {}
            run_status: str | None = None
            run_reason = ""
            # (item or None, why it is not on the scene's grid, or empty)
            recorded: dict[tuple[str, str], tuple[Any, str]] = {}
            try:
                nbart = with_retries(
                    functools.partial(find_nbart_item, scene, bbox),
                    tries=DEA_LOOKUP_TRIES,
                    delay_s=DEA_LOOKUP_DELAY_S,
                    sleep=time.sleep,
                )
                if nbart is None:
                    run_status = "no_dea_item"
                    run_reason = "find_nbart_item found no DEA ARD item"
                else:
                    dea_grid = dea.open_grid(nbart.red_href)
                    item_fields = {
                        "dea_collection": nbart.collection,
                        "dea_item": nbart.item_id,
                        "dea_maturity": nbart.maturity,
                        "dea_epsg": dea_grid.epsg,
                    }
                    if {nbart.epsg, dea_grid.epsg, grid.epsg} != {operation_epsg}:
                        run_status = "crs_differs"
                        run_reason = (
                            f"item EPSG {nbart.epsg}, DEA grid EPSG "
                            f"{dea_grid.epsg}, scene grid EPSG {grid.epsg}"
                        )
                    elif dea_grid.transform != grid.transform:
                        run_status = "grid_differs"
                        run_reason = "DEA grid transform differs from the scene's"
                for polygon, _ in planned:
                    report = report_values.get((item_id, polygon.polygon_id))
                    if report is None:
                        continue
                    key = (report.dea_collection, report.dea_item)
                    if nbart is not None and report.dea_item == nbart.item_id:
                        if run_status is not None:
                            recorded[key] = (nbart, run_reason)
                        continue
                    if key not in recorded:
                        item = with_retries(
                            functools.partial(fetch_recorded_item, *key),
                            tries=DEA_LOOKUP_TRIES,
                            delay_s=DEA_LOOKUP_DELAY_S,
                            sleep=time.sleep,
                        )
                        why = ""
                        if item is not None:
                            recorded_grid = dea.open_grid(item.red_href)
                            why = grid_difference(
                                item.epsg,
                                recorded_grid.epsg,
                                grid.epsg,
                                recorded_grid.transform == grid.transform,
                                operation_epsg,
                            )
                        recorded[key] = (item, why)
            except Exception as err:
                # A scene-level DEA failure gives read_error rows for every
                # planned polygon, unless it is a network error on a seen row.
                if any(
                    propagate_read_error(
                        sample, (date, item_id, polygon.polygon_id) in seen_keys, err
                    )
                    for polygon, _ in planned
                ):
                    raise
                for polygon, _ in planned:
                    row = base_row(
                        polygon.polygon_id,
                        "read_error",
                        reason=f"{type(err).__name__}: {err}",
                        **item_fields,
                    )
                    rows.append(
                        dataclasses.replace(row, matches_report=report_match(row))
                    )
                continue

            for polygon, window in planned:
                seen_failing = (date, item_id, polygon.polygon_id) in seen_keys
                report = report_values.get((item_id, polygon.polygon_id))
                if run_status is not None and report is None:
                    rows.append(
                        base_row(
                            polygon.polygon_id,
                            run_status,
                            reason=run_reason,
                            **item_fields,
                        )
                    )
                    continue
                try:
                    stack = read_stack(scene, window, reader)
                    inside = rasterise(polygon.geometry, stack.transform, stack.shape)
                    ndvi_stored = summarise(
                        polygon, scene, stack, window, water=config.water, run_id=RUN_ID
                    ).ndvi_median
                    measures = None
                    if run_status is None:
                        if nbart is None:
                            raise ValueError("no DEA item for a scene with no status")
                        red_dn, nir_dn = read_dea_window(
                            dea,
                            nbart.red_href,
                            nbart.nir_href,
                            window.window10,
                            stack.shape,
                        )
                        measures = compare_pixels(
                            scl=stack.scl,
                            green=stack.green,
                            red=stack.red,
                            nir=stack.nir,
                            swir16=stack.swir16,
                            inside=inside,
                            red_dn=red_dn,
                            nir_dn=nir_dn,
                        )
                    served: bool | None = None
                    recorded_ndvi: float | None = None
                    recorded_n: int | None = None
                    recorded_why = ""
                    if (
                        report is not None
                        and measures is not None
                        and nbart is not None
                        and report.dea_item == nbart.item_id
                    ):
                        served = True
                        recorded_ndvi = measures.ndvi_dea
                        recorded_n = measures.n_compared
                    elif report is not None:
                        item, recorded_why = recorded[
                            (report.dea_collection, report.dea_item)
                        ]
                        served = item is not None
                        if item is not None and not recorded_why:
                            recorded_red, recorded_nir = read_dea_window(
                                dea,
                                item.red_href,
                                item.nir_href,
                                window.window10,
                                stack.shape,
                            )
                            clear = (
                                clear_mask(
                                    stack.scl,
                                    stack.green,
                                    stack.red,
                                    stack.nir,
                                    stack.swir16,
                                )
                                & inside
                            )
                            recorded_ndvi, recorded_n, _ = dea_ndvi_median(
                                recorded_red, recorded_nir, clear
                            )
                    recorded_fields: dict[str, Any] = {
                        "ndvi_stored": float(ndvi_stored),
                        "recorded_dea_served": served,
                        "recorded_ndvi_dea": recorded_ndvi,
                        "recorded_n_compared": recorded_n,
                        "recorded_reason": recorded_why,
                        **item_fields,
                    }
                    if run_status is not None or measures is None:
                        # The run-day DEA item gave no comparison, but the
                        # reproduction gate still tests ndvi_stored and the
                        # recorded-item values.
                        row = base_row(
                            polygon.polygon_id,
                            run_status or "read_error",
                            reason=run_reason,
                            **recorded_fields,
                        )
                    else:
                        status = row_status(ndvi_stored, measures.n_compared)
                        row = base_row(
                            polygon.polygon_id,
                            status,
                            reason=(
                                ""
                                if status == "scored"
                                else "pipeline median not finite or fewer than "
                                f"{MIN_PIXELS} compared pixels"
                            ),
                            n_inside=measures.n_inside,
                            n_clear=measures.n_clear,
                            n_compared=measures.n_compared,
                            n_dea_nodata=measures.n_dea_nodata,
                            ndvi_pipeline_same=measures.ndvi_pipeline_same,
                            ndvi_dea=measures.ndvi_dea,
                            abs_diff=abs(float(ndvi_stored) - measures.ndvi_dea),
                            red_pipeline=measures.red_pipeline,
                            nir_pipeline=measures.nir_pipeline,
                            red_dea=measures.red_dea,
                            nir_dea=measures.nir_dea,
                            d_red=measures.d_red,
                            d_nir=measures.d_nir,
                            band_max=measures.band_max,
                            s_pipeline=measures.s_pipeline,
                            s_dea=measures.s_dea,
                            **recorded_fields,
                        )
                except Exception as err:
                    if propagate_read_error(sample, seen_failing, err):
                        raise
                    row = base_row(
                        polygon.polygon_id,
                        "read_error",
                        reason=f"{type(err).__name__}: {err}",
                        **item_fields,
                    )
                rows.append(dataclasses.replace(row, matches_report=report_match(row)))
            logger.info("read %s", item_id)
    return sorted(rows, key=_row_order)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NDVI row rule against DEA NBART (st-da75)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, out, report, help_text in (
        (
            "nominate",
            NOMINATION_CSV,
            NOMINATION_TXT,
            "re-read the eight seen scene-tiles",
        ),
        ("confirm", ROWS_CSV, ROWS_TXT, "read the confirmatory sample once"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--ramsar", required=True, type=Path)
        command.add_argument("--out", type=Path, default=out)
        command.add_argument("--report", type=Path, default=report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.command == "nominate":
        rows = measure("nomination", args.ramsar)
        write_rows(args.out, rows)
        text = build_nomination_report(rows)
        args.report.write_text(text, encoding="utf-8")
        print(text)
        return 0 if all(ok for _, ok, _ in reproduction(rows)) else 1
    message = nomination_committed(REPO, [NOMINATION_CSV, NOMINATION_TXT])
    if message is None:
        nomination_rows = load_rows(NOMINATION_CSV)
        message = nomination_ready(
            nomination_rows, NOMINATION_TXT.read_text(encoding="utf-8")
        )
    if message is None:
        existing = [
            path
            for path in dict.fromkeys((ROWS_CSV, ROWS_TXT, args.out, args.report))
            if path.exists()
        ]
        if existing:
            message = (
                "confirm reads its sample once and results already exist: "
                + ", ".join(str(path) for path in existing)
            )
    if message is not None:
        print(message)
        return 2
    rows = measure("confirm", args.ramsar)
    write_rows(args.out, rows)
    text = build_report(rows, nomination_rows)
    args.report.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
