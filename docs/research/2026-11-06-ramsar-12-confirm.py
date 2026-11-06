"""Confirmatory sample for a ramsar-12 water-setting override (st-2a78).

Implements the st-2a78 pre-registration in LEARNINGS.md, section
"Pre-registered hypotheses (st-2a78, 2026-11-06)". The rule R1 to R6, the
candidates, the window and the exclusions are fixed there and in the constants
below; they are not changed after results are seen. Anonymous public reads of
Earth Search and DEA only. The script is read-only apart from the two files it
writes (--out and --report), and it never calls verify_run.

  uv run python docs/research/2026-11-06-ramsar-12-confirm.py \
      --ramsar <geojson> [--out CSV] [--report TXT]

--ramsar is the DBCA-010 Ramsar layer (config aoi.ramsar_path is relative and
absent in a worktree); it may be
/Users/jarrodbaker/Documents/swan-wetland-change-data/aoi/dbca_010_ramsar_sites.geojson
and is only read. Output paths default to files beside this script. The
outputs hold no timestamps, so a rerun on the same data is deterministic.

For every Earth Search `sentinel-2-c1-l2a` item that the pipeline's own
`discover` returns for ramsar-12 between 2026-08-15 and 2026-11-05, outside the
six dates of 2026-11-06-ramsar-12-gap.csv, the stack and the DEA WO raster are
read once. clear is clear_mask(...) & inside and the WO clear rule is
`(wo & WO_EXCLUDE) == 0`, as in wo_check. n is the count of mutually clear
pixels, a counts the pixels the pipeline calls wet and WO calls dry, b the
reverse, gap_pp = 100 * (a - b) / n and agreement = 1 - (a + b) / n. Each scene
first passes the pipeline's guards (grid and item EPSG equal to the operation
EPSG, band scale and offset checked against the ESA product XML), and a failure
raises. Scene-tiles with no WO item, a WO grid transform that differs from the
scene's ("grid differs", as in wo_check) or fewer than 100 mutually clear
pixels are dropped and listed.

The functions above `measure` are pure so that tests can import them without
the network or the AOI file.
"""

import argparse
import csv
import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

HERE: Final = Path(__file__).resolve().parent
REPO: Final = HERE.parents[1]
POLYGON: Final = "ramsar-12"
COLLECTION: Final = "sentinel-2-c1-l2a"
DEFAULT_OUT: Final = HERE / "2026-11-06-ramsar-12-confirm.csv"
DEFAULT_REPORT: Final = HERE / "2026-11-06-ramsar-12-confirm.txt"
SEEN_CSV: Final = HERE / "2026-11-06-ramsar-12-gap.csv"

GLOBAL_THRESHOLD: Final = -0.10
CANDIDATES: Final = (0.0, 0.05, 0.10)
NOMINEE: Final = 0.05
REPORTED_THRESHOLDS: Final = (GLOBAL_THRESHOLD, *CANDIDATES)
WINDOW_START: Final = date(2026, 8, 15)
WINDOW_END: Final = date(2026, 11, 5)
GLOBAL_AGREEMENT_MIN: Final = 0.91

MIN_CLEAR_PIXELS: Final = 100
MIN_ROWS: Final = 6
MIN_DATES: Final = 3
LIMIT_PP: Final = 5.0
MIN_POOLED_GAIN: Final = Fraction(1, 200)
MIN_WIN_SHARE: Final = Fraction(2, 3)
MAX_MEAN_SIGNED_PP: Final = 2.0
AGREEMENT_MARGIN: Final = Fraction(2, 100)
AGREEMENT_MIN_FLOOR: Final = Fraction(91, 100)
THRESHOLD_DECIMALS: Final = 2
SELECTION_DECIMALS: Final = 9

COLUMNS: Final = (
    "item_id",
    "pass_date",
    "tile",
    "method",
    "threshold",
    "n_mutually_clear",
    "a_pipeline_only",
    "b_wo_only",
    "gap_pp",
    "agreement",
)
CONDITIONS: Final = ("R1", "R2", "R3", "R4", "R5", "R6")

Row = dict[str, Any]
Dropped = tuple[str, str]


@dataclass(frozen=True, slots=True, kw_only=True)
class Decision:
    """Outcome of the pre-registered rule and the numbers behind it.

    `threshold` and `agreement_min` are set only for an override. `selected` is
    the candidate chosen by the selection rule, whatever the outcome. The
    numbers after `n_dates` are None when R1 failed and the rest was not
    evaluated.
    """

    outcome: str
    threshold: float | None
    agreement_min: float | None
    failed: tuple[str, ...]
    inconclusive: bool
    selected: float | None
    n_rows: int
    n_dates: int
    max_abs_gap_pp: float | None = None
    pooled_selected: Fraction | None = None
    pooled_global: Fraction | None = None
    pooled_gain: Fraction | None = None
    win_count: int | None = None
    win_share: Fraction | None = None
    mean_signed_gap_pp: float | None = None
    floor: Fraction | None = None
    n_pooled_rows: int | None = None
    n_below_floor: int | None = None


def _same_threshold(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return round(left, THRESHOLD_DECIMALS) == round(right, THRESHOLD_DECIMALS)


def _mndwi_at(rows: Iterable[Row], threshold: float) -> list[Row]:
    return [
        row
        for row in rows
        if row["method"] == "mndwi" and _same_threshold(row["threshold"], threshold)
    ]


def _disagreement(rows: Sequence[Row]) -> int:
    return sum(row["a_pipeline_only"] + row["b_wo_only"] for row in rows)


def _pixels(rows: Sequence[Row]) -> int:
    return sum(row["n_mutually_clear"] for row in rows)


def _pooled_agreement(rows: Sequence[Row]) -> Fraction:
    return 1 - Fraction(_disagreement(rows), _pixels(rows))


def _row_agreement(row: Row) -> Fraction:
    return 1 - Fraction(
        row["a_pipeline_only"] + row["b_wo_only"], row["n_mutually_clear"]
    )


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def load_rows(path: Path) -> list[Row]:
    """Rows of a seen or confirmatory CSV; extra columns are ignored."""
    rows: list[Row] = []
    with path.open(newline="") as handle:
        for record in csv.DictReader(handle):
            threshold = record["threshold"]
            rows.append(
                {
                    "item_id": record["item_id"],
                    "pass_date": record["pass_date"],
                    "tile": record["tile"],
                    "method": record["method"],
                    "threshold": float(threshold) if threshold != "" else None,
                    "n_mutually_clear": int(record["n_mutually_clear"]),
                    "a_pipeline_only": int(record["a_pipeline_only"]),
                    "b_wo_only": int(record["b_wo_only"]),
                    "gap_pp": float(record["gap_pp"]),
                    "agreement": float(record["agreement"]),
                }
            )
    return rows


def seen_dates(seen_rows: Iterable[Row]) -> set[str]:
    return {row["pass_date"] for row in seen_rows}


def write_rows(rows: Iterable[Row], path: Path) -> None:
    ordered = sorted(
        rows,
        key=lambda row: (
            row["pass_date"],
            row["tile"],
            row["method"],
            -math.inf if row["threshold"] is None else row["threshold"],
        ),
    )
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in ordered:
            writer.writerow(
                {name: "" if row[name] is None else row[name] for name in COLUMNS}
            )


def select_threshold(confirm_rows: Iterable[Row]) -> float:
    """Candidate with the lowest mean abs gap_pp; ties to nearest +0.05, then lower."""
    rows = list(confirm_rows)
    keys: list[tuple[float, float, float]] = []
    for candidate in CANDIDATES:
        gaps = [abs(row["gap_pp"]) for row in _mndwi_at(rows, candidate)]
        if gaps:
            keys.append(
                (
                    round(_mean(gaps), SELECTION_DECIMALS),
                    round(abs(candidate - NOMINEE), SELECTION_DECIMALS),
                    candidate,
                )
            )
    if not keys:
        raise ValueError("no confirmatory mndwi rows at any candidate threshold")
    return min(keys)[2]


def agreement_floor(a_plus_b: int, n: int) -> Fraction:
    """Floor to 0.01 of (1 - a_plus_b / n - AGREEMENT_MARGIN), in exact arithmetic."""
    value = 1 - Fraction(a_plus_b, n) - AGREEMENT_MARGIN
    return Fraction(math.floor(value * 100), 100)


def _check_items(rows: Sequence[Row], selected: float) -> None:
    item_ids = sorted({row["item_id"] for row in rows})
    for item_id in item_ids:
        own = [row for row in rows if row["item_id"] == item_id]
        for threshold in (GLOBAL_THRESHOLD, selected):
            if len(_mndwi_at(own, threshold)) != 1:
                raise ValueError(
                    f"{item_id}: expected one mndwi row at {threshold:+.2f}, "
                    f"found {len(_mndwi_at(own, threshold))}"
                )


def decide(confirm_rows: Sequence[Row], seen_rows: Sequence[Row]) -> Decision:
    """Apply R1 to R6 of the st-2a78 pre-registration."""
    overlap = {row["pass_date"] for row in confirm_rows} & seen_dates(seen_rows)
    if overlap:
        raise ValueError(
            f"confirmatory rows on seen dates: {', '.join(sorted(overlap))}"
        )
    if not confirm_rows:
        return Decision(
            outcome="keep-global",
            threshold=None,
            agreement_min=None,
            failed=("R1",),
            inconclusive=True,
            selected=None,
            n_rows=0,
            n_dates=0,
        )
    selected = select_threshold(confirm_rows)
    _check_items(confirm_rows, selected)
    at_selected = _mndwi_at(confirm_rows, selected)
    at_global = {
        row["item_id"]: row for row in _mndwi_at(confirm_rows, GLOBAL_THRESHOLD)
    }
    n_rows = len(at_selected)
    n_dates = len({row["pass_date"] for row in at_selected})
    if n_rows < MIN_ROWS or n_dates < MIN_DATES:
        return Decision(
            outcome="keep-global",
            threshold=None,
            agreement_min=None,
            failed=("R1",),
            inconclusive=True,
            selected=selected,
            n_rows=n_rows,
            n_dates=n_dates,
        )

    failed: list[str] = []
    max_abs_gap = max(abs(row["gap_pp"]) for row in at_selected)
    if max_abs_gap > LIMIT_PP:
        failed.append("R2")
    pooled_selected = _pooled_agreement(at_selected)
    pooled_global = _pooled_agreement(list(at_global.values()))
    pooled_gain = pooled_selected - pooled_global
    if pooled_gain < MIN_POOLED_GAIN:
        failed.append("R3")
    win_count = sum(
        _row_agreement(row) > _row_agreement(at_global[row["item_id"]])
        for row in at_selected
    )
    win_share = Fraction(win_count, n_rows)
    if win_share < MIN_WIN_SHARE:
        failed.append("R4")
    mean_signed = _mean([row["gap_pp"] for row in at_selected])
    if abs(mean_signed) > MAX_MEAN_SIGNED_PP:
        failed.append("R5")
    pooled_rows = _mndwi_at(seen_rows, selected) + at_selected
    floor = agreement_floor(_disagreement(pooled_rows), _pixels(pooled_rows))
    if floor < AGREEMENT_MIN_FLOOR:
        failed.append("R6")
    n_below = sum(_row_agreement(row) < floor for row in pooled_rows)

    adopted = not failed
    return Decision(
        outcome="override" if adopted else "keep-global",
        threshold=selected if adopted else None,
        agreement_min=float(floor) if adopted else None,
        failed=tuple(failed),
        inconclusive=False,
        selected=selected,
        n_rows=n_rows,
        n_dates=n_dates,
        max_abs_gap_pp=max_abs_gap,
        pooled_selected=pooled_selected,
        pooled_global=pooled_global,
        pooled_gain=pooled_gain,
        win_count=win_count,
        win_share=win_share,
        mean_signed_gap_pp=mean_signed,
        floor=floor,
        n_pooled_rows=len(pooled_rows),
        n_below_floor=n_below,
    )


def _label(threshold: float | None) -> str:
    return "scl6" if threshold is None else f"{threshold:+.2f}"


def _cell(row: Row | None) -> str:
    if row is None:
        return "n/a"
    return (
        f"a={row['a_pipeline_only']} b={row['b_wo_only']} n={row['n_mutually_clear']} "
        f"gap_pp={row['gap_pp']:+.3f} agreement={row['agreement']:.4f}"
    )


def _condition_lines(decision: Decision) -> list[str]:
    def verdict(name: str) -> str:
        return "fail" if name in decision.failed else "pass"

    if decision.inconclusive:
        lines = [
            f"R1 sample: rows={decision.n_rows} dates={decision.n_dates}, need rows "
            f">= {MIN_ROWS} and dates >= {MIN_DATES}: fail"
        ]
        lines.extend(f"{name} not evaluated (R1 failed)" for name in CONDITIONS[1:])
        return lines
    assert decision.pooled_selected is not None
    assert decision.pooled_global is not None
    assert decision.pooled_gain is not None
    assert decision.win_share is not None
    assert decision.floor is not None
    assert decision.max_abs_gap_pp is not None
    assert decision.mean_signed_gap_pp is not None
    return [
        f"R1 sample: rows={decision.n_rows} dates={decision.n_dates}, need rows "
        f">= {MIN_ROWS} and dates >= {MIN_DATES}: pass",
        f"R2 clause: max abs gap_pp={decision.max_abs_gap_pp:.3f}, need <= "
        f"{LIMIT_PP:.1f}: {verdict('R2')}",
        f"R3 gain: pooled agreement {float(decision.pooled_selected):.4f} minus "
        f"{float(decision.pooled_global):.4f} = {float(decision.pooled_gain):+.4f}, "
        f"need >= {float(MIN_POOLED_GAIN):.3f}: {verdict('R3')}",
        f"R4 consistency: rows with higher agreement {decision.win_count} of "
        f"{decision.n_rows} (share {float(decision.win_share):.4f}), need >= "
        f"{float(MIN_WIN_SHARE):.4f}: {verdict('R4')}",
        f"R5 no over-correction: mean signed "
        f"gap_pp={decision.mean_signed_gap_pp:+.3f}, "
        f"need abs <= {MAX_MEAN_SIGNED_PP:.1f}: {verdict('R5')}",
        f"R6 floor: agreement_min={float(decision.floor):.2f} over "
        f"{decision.n_pooled_rows} rows (seen plus confirmatory), need >= "
        f"{float(AGREEMENT_MIN_FLOOR):.2f}: {verdict('R6')}",
    ]


def build_report(
    confirm_rows: Sequence[Row],
    seen_rows: Sequence[Row],
    decision: Decision,
    dropped: Sequence[Dropped],
) -> str:
    out = [
        "ramsar-12 confirmatory sample (LEARNINGS.md st-2a78 pre-registration)",
        "",
        "n is mutually clear pixels, a is pipeline wet and WO dry, b is WO wet and "
        "pipeline dry, gap_pp = 100 * (a - b) / n, agreement = 1 - (a + b) / n.",
        "",
        "== Parameters ==",
        f"collection={COLLECTION} polygon={POLYGON}",
        f"window={WINDOW_START.isoformat()} to {WINDOW_END.isoformat()} inclusive, "
        f"seen dates excluded: {', '.join(sorted(seen_dates(seen_rows)))}",
        f"global threshold={GLOBAL_THRESHOLD:+.2f} "
        f"agreement_min={GLOBAL_AGREEMENT_MIN}",
        f"candidates={', '.join(f'{c:+.2f}' for c in CANDIDATES)} "
        f"nominee={NOMINEE:+.2f}",
        f"min_clear_pixels={MIN_CLEAR_PIXELS} min_rows={MIN_ROWS} "
        f"min_dates={MIN_DATES} "
        f"limit_pp={LIMIT_PP} min_pooled_gain={float(MIN_POOLED_GAIN)} "
        f"min_win_share={float(MIN_WIN_SHARE):.4f} "
        f"max_mean_signed_pp={MAX_MEAN_SIGNED_PP} "
        f"agreement_margin={float(AGREEMENT_MARGIN)} "
        f"agreement_min_floor={float(AGREEMENT_MIN_FLOOR)}",
        "",
        f"== Dropped scene-tiles ({len(dropped)}) ==",
    ]
    out.extend(f"{item_id}: {reason}" for item_id, reason in dropped)
    if not dropped:
        out.append("none")

    row_count = len(_mndwi_at(confirm_rows, GLOBAL_THRESHOLD))
    out.extend(
        [
            "",
            f"== Confirmatory rows ({row_count}) ==",
        ]
    )
    item_ids = sorted(
        {row["item_id"] for row in confirm_rows},
        key=lambda item_id: next(
            (r["pass_date"], r["tile"], item_id)
            for r in confirm_rows
            if r["item_id"] == item_id
        ),
    )
    for item_id in item_ids:
        own = [row for row in confirm_rows if row["item_id"] == item_id]
        out.append(f"{item_id} ({own[0]['pass_date']}, {own[0]['tile']})")
        for threshold in REPORTED_THRESHOLDS:
            found = _mndwi_at(own, threshold)
            out.append(f"  {_label(threshold)}: {_cell(found[0] if found else None)}")
        scl6 = [row for row in own if row["method"] == "scl6"]
        out.append(f"  scl6: {_cell(scl6[0] if scl6 else None)}")

    out.extend(
        [
            "",
            "== Per threshold over the confirmatory rows ==",
            "threshold: rows, pooled agreement, mean abs gap_pp, mean signed gap_pp",
        ]
    )
    for threshold in REPORTED_THRESHOLDS:
        group = _mndwi_at(confirm_rows, threshold)
        if not group:
            out.append(f"{_label(threshold)}: no rows")
            continue
        gaps = [row["gap_pp"] for row in group]
        out.append(
            f"{_label(threshold)}: rows={len(group)} "
            f"pooled_agreement={float(_pooled_agreement(group)):.4f} "
            f"mean_abs_gap={_mean([abs(g) for g in gaps]):.3f} "
            f"mean_gap={_mean(gaps):+.3f}"
        )
    scl_group = [row for row in confirm_rows if row["method"] == "scl6"]
    if scl_group:
        gaps = [row["gap_pp"] for row in scl_group]
        out.append(
            f"scl6 (context only): rows={len(scl_group)} "
            f"pooled_agreement={float(_pooled_agreement(scl_group)):.4f} "
            f"mean_abs_gap={_mean([abs(g) for g in gaps]):.3f} "
            f"mean_gap={_mean(gaps):+.3f}"
        )

    out.extend(["", "== Decision =="])
    if decision.selected is None:
        out.append("Selected T: none (no confirmatory rows)")
    else:
        out.append(f"Selected T: {decision.selected:+.2f}")
    out.extend(_condition_lines(decision))
    if decision.floor is not None and decision.n_pooled_rows is not None:
        out.append(
            f"rows below agreement_min={float(decision.floor):.2f}: "
            f"{decision.n_below_floor} of {decision.n_pooled_rows} "
            "(seen plus confirmatory rows at T)"
        )
    if decision.selected is not None:
        equal = _same_threshold(decision.selected, NOMINEE)
        out.append(f"T equals {NOMINEE:+.2f}: {'yes' if equal else 'no'}")
    out.append("")
    out.append(f"Chosen outcome: {decision.outcome}")
    if decision.outcome == "override":
        assert decision.threshold is not None and decision.agreement_min is not None
        out.append(f"threshold = {decision.threshold:.2f}")
        out.append(f"agreement_min = {decision.agreement_min:.2f}")
    else:
        out.append(f"Failed: {', '.join(decision.failed)}")
        out.append(f"Inconclusive: {'yes' if decision.inconclusive else 'no'}")
    return "\n".join(out) + "\n"


def disagreement_counts(
    water: Any, mutually_clear: Any, wo_wet: Any
) -> tuple[int, int, int]:
    """(n, a, b) over the mutually clear pixels."""
    count = int(mutually_clear.sum())
    pipeline_only = int((water & ~wo_wet & mutually_clear).sum())
    wo_only = int((~water & wo_wet & mutually_clear).sum())
    return count, pipeline_only, wo_only


def measure(
    ramsar_path: Path, excluded_dates: set[str]
) -> tuple[list[Row], list[Dropped]]:
    """Read each eligible ramsar-12 scene-tile once; return rows and dropped ones."""
    from wetland_change.aoi import load_ramsar, union_bbox_4326
    from wetland_change.catalogue.search import discover, open_client
    from wetland_change.config import WaterSetting, load_config
    from wetland_change.mask import clear_mask
    from wetland_change.pipeline import SceneGridError
    from wetland_change.raster.read import RasterioReader, read_stack
    from wetland_change.raster.scaling import check_band_scaling, parse_product_metadata
    from wetland_change.stats import rasterise, water_pixels
    from wetland_change.verify.wo import (
        WO_EXCLUDE,
        WO_WET,
        dea_reader,
        find_wo_href,
    )
    from wetland_change.windows import plan_window

    config = load_config(REPO / "config" / "pipeline.toml")
    config = config.model_copy(
        update={"aoi": config.aoi.model_copy(update={"ramsar_path": ramsar_path})}
    )
    assert config.stac.collection == COLLECTION
    polygons = load_ramsar(
        config.aoi.ramsar_path,
        site_prefixes=config.aoi.site_prefixes,
        operation_epsg=config.aoi.operation_epsg,
    )
    polygon = next(p for p in polygons if p.polygon_id == POLYGON)
    client = open_client(config.stac.endpoint)
    bbox = union_bbox_4326(polygons)
    found = discover(
        client,
        config.stac,
        bbox=bbox,
        polygons_4326=[polygon.geometry_4326],
        created_from=None,
        seen=set(),
        datetime_range=(
            datetime.combine(WINDOW_START, datetime.min.time(), tzinfo=UTC),
            datetime(
                WINDOW_END.year,
                WINDOW_END.month,
                WINDOW_END.day,
                23,
                59,
                59,
                tzinfo=UTC,
            ),
        ),
    )
    dropped: list[Dropped] = [
        (item_id, f"rejected by discover: {reason}")
        for item_id, reason in found.rejected
    ]
    reader = RasterioReader()
    dea = dea_reader()
    settings: list[tuple[str, float | None, Any]] = [
        (
            "mndwi",
            threshold,
            WaterSetting(
                method="mndwi",
                threshold=threshold,
                agreement_min=GLOBAL_AGREEMENT_MIN,
            ),
        )
        for threshold in REPORTED_THRESHOLDS
    ]
    settings.append(
        (
            "scl6",
            None,
            WaterSetting(method="scl6", agreement_min=GLOBAL_AGREEMENT_MIN),
        )
    )
    rows: list[Row] = []
    for scene in sorted(found.scenes, key=lambda s: s.item_id):
        pass_date = scene.datetime.date().isoformat()
        if pass_date in excluded_dates:
            dropped.append((scene.item_id, f"acquired on seen date {pass_date}"))
            continue
        grid = reader.open_grid(scene.bands["green"].href)
        operation_epsg = config.aoi.operation_epsg
        if grid.epsg != operation_epsg or scene.epsg != operation_epsg:
            raise SceneGridError(
                f"{scene.item_id}: grid EPSG {grid.epsg}, item EPSG "
                f"{scene.epsg}, operation EPSG {operation_epsg}"
            )
        esa = parse_product_metadata(reader.read_text(scene.product_metadata_href))
        for band in scene.bands.values():
            check_band_scaling(band, esa)
        planned = plan_window(polygon.geometry, grid)
        if planned is None:
            dropped.append((scene.item_id, "no planned window for ramsar-12"))
            continue
        wo_href = find_wo_href(scene, bbox)
        if wo_href is None:
            dropped.append((scene.item_id, "no DEA WO item"))
            continue
        if dea.open_grid(wo_href).transform != grid.transform:
            dropped.append((scene.item_id, "grid differs"))
            continue
        stack = read_stack(scene, planned, reader)
        inside = rasterise(polygon.geometry, stack.transform, stack.shape)
        wo = dea.read(wo_href, planned.window10)
        clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
        mutually_clear = clear & ((wo & WO_EXCLUDE) == 0)
        wo_wet = (wo & WO_WET) > 0
        clear_count = int(mutually_clear.sum())
        if clear_count < MIN_CLEAR_PIXELS:
            dropped.append(
                (
                    scene.item_id,
                    f"fewer than {MIN_CLEAR_PIXELS} mutually clear pixels "
                    f"({clear_count})",
                )
            )
            continue
        for method, threshold, setting in settings:
            water = water_pixels(setting, stack, clear)
            count, pipeline_only, wo_only = disagreement_counts(
                water, mutually_clear, wo_wet
            )
            rows.append(
                {
                    "item_id": scene.item_id,
                    "pass_date": pass_date,
                    "tile": scene.tile,
                    "method": method,
                    "threshold": threshold,
                    "n_mutually_clear": count,
                    "a_pipeline_only": pipeline_only,
                    "b_wo_only": wo_only,
                    "gap_pp": 100 * (pipeline_only - wo_only) / count,
                    "agreement": 1 - (pipeline_only + wo_only) / count,
                }
            )
        logger.info("read %s", scene.item_id)
    return rows, sorted(dropped)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ramsar-12 confirmatory sample (st-2a78)"
    )
    parser.add_argument("--ramsar", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    seen_rows = load_rows(SEEN_CSV)
    rows, dropped = measure(args.ramsar, seen_dates(seen_rows))
    write_rows(rows, args.out)
    decision = decide(rows, seen_rows)
    args.report.write_text(build_report(rows, seen_rows, decision, dropped))


if __name__ == "__main__":
    main()
