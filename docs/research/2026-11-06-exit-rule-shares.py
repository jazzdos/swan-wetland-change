"""Exit-rule candidates K1 to K4 for wet-area failures, scored on the committed gap CSV.

Implements Part A of the st-7047 pre-registration in LEARNINGS.md: for each
measured date (the 6 newest pass_date values, each with every polygon scored) it
decides whether `verify` would exit 3 under each candidate rule, then applies the
decision rule to pick one. It reads only the committed
`2026-11-05-wet-area-gap.csv` (stdlib only, no rasters, no network) and is
deterministic for that file.

  uv run python docs/research/2026-11-06-exit-rule-shares.py \
      [--gap-csv CSV] [--out CSV] [--report TXT]

Paths default to files beside this script.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any, Final

HERE: Final = Path(__file__).resolve().parent
DEFAULT_GAP: Final = HERE / "2026-11-05-wet-area-gap.csv"
DEFAULT_OUT: Final = HERE / "2026-11-06-exit-rule-shares.csv"
DEFAULT_REPORT: Final = HERE / "2026-11-06-exit-rule-shares.txt"

MIN_CLEAR_PIXELS: Final = 100
GAP_LIMIT_PP: Final = 5.0
MEASURED_DATE_COUNT: Final = 6
MIN_ROWS_PER_MEASURED_DATE: Final = 25
CANDIDATES: Final = ("K1", "K2", "K3", "K4")
# A candidate maps to the candidates whose failing runs it also fails.
INCLUDES: Final = {
    "K1": frozenset({"K2", "K3", "K4"}),
    "K3": frozenset({"K2"}),
    "K4": frozenset({"K2"}),
}

Row = dict[str, Any]


def load_rows(path: Path) -> list[Row]:
    """Read the gap CSV and keep rows with at least MIN_CLEAR_PIXELS clear pixels."""
    rows: list[Row] = []
    with Path(path).open(newline="") as handle:
        for raw in csv.DictReader(handle):
            clear_pixels = int(raw["n_mutually_clear"])
            if clear_pixels < MIN_CLEAR_PIXELS:
                continue
            rows.append(
                {
                    "polygon_id": raw["polygon_id"],
                    "tile": raw["tile"],
                    "item_id": raw["item_id"],
                    "pass_date": raw["pass_date"],
                    "n_mutually_clear": clear_pixels,
                    "agreement": float(raw["agreement"]),
                    "agreement_min": float(raw["agreement_min"]),
                    "pipeline_wet_share": float(raw["pipeline_wet_share"]),
                    "wo_wet_share": float(raw["wo_wet_share"]),
                    "gap_pp": float(raw["gap_pp"]),
                    "passes_agreement": raw["passes_agreement"] == "True",
                }
            )
    return rows


def _pooled_gap_pp(rows: list[Row]) -> float:
    total = sum(row["n_mutually_clear"] for row in rows)
    pipeline_wet = sum(
        round(row["pipeline_wet_share"] * row["n_mutually_clear"]) for row in rows
    )
    wo_wet = sum(round(row["wo_wet_share"] * row["n_mutually_clear"]) for row in rows)
    return 100.0 * (pipeline_wet - wo_wet) / total


def date_outcomes(rows: list[Row]) -> list[Row]:
    """One dict per pass_date, newest first, with the four candidate outcomes."""
    rows_by_date: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        rows_by_date[row["pass_date"]].append(row)
    dates = sorted(rows_by_date, reverse=True)
    measured_dates = set(dates[:MEASURED_DATE_COUNT])
    for date in measured_dates:
        assert len(rows_by_date[date]) >= MIN_ROWS_PER_MEASURED_DATE, (
            date,
            len(rows_by_date[date]),
        )

    outcomes: list[Row] = []
    for date in dates:
        group = rows_by_date[date]
        fails_agreement = sum(1 for row in group if not row["passes_agreement"])
        clause_only = [
            row
            for row in group
            if row["passes_agreement"] and abs(row["gap_pp"]) > GAP_LIMIT_PP
        ]
        any_clause_failure = any(abs(row["gap_pp"]) > GAP_LIMIT_PP for row in group)
        rows_by_polygon: dict[str, list[Row]] = defaultdict(list)
        for row in group:
            rows_by_polygon[row["polygon_id"]].append(row)
        has_persistent_polygon = any(
            all(abs(row["gap_pp"]) > GAP_LIMIT_PP for row in polygon_rows)
            for polygon_rows in rows_by_polygon.values()
        )
        pooled_gap_pp = _pooled_gap_pp(group)
        agreement_fails = fails_agreement > 0
        outcomes.append(
            {
                "pass_date": date,
                "measured": date in measured_dates,
                "n_rows": len(group),
                "n_fail_agreement": fails_agreement,
                "n_fail_clause_only": len(clause_only),
                "clause_only_polygons": sorted(
                    {row["polygon_id"] for row in clause_only}
                ),
                "pooled_gap_pp": pooled_gap_pp,
                "k1": agreement_fails or any_clause_failure,
                "k2": agreement_fails,
                "k3": agreement_fails or has_persistent_polygon,
                "k4": agreement_fails or abs(pooled_gap_pp) > GAP_LIMIT_PP,
            }
        )
    return outcomes


def _break_tie(tied: list[str]) -> str:
    """Prefer the candidate whose failing condition includes the other's; else the first."""
    champion = tied[0]
    for challenger in tied[1:]:
        if challenger in INCLUDES.get(champion, frozenset()):
            continue
        if champion in INCLUDES.get(challenger, frozenset()):
            champion = challenger
    return champion


def choose(outcomes: list[Row]) -> dict[str, Any]:
    """Apply the pre-registered decision rule over the measured dates."""
    measured = [outcome for outcome in outcomes if outcome["measured"]]
    counts = {
        candidate: sum(1 for outcome in measured if outcome[candidate.lower()])
        for candidate in CANDIDATES
    }
    agreement_alone = counts["K2"]
    admissible = [c for c in CANDIDATES if counts[c] <= agreement_alone + 1]
    most_failing = max(counts[candidate] for candidate in admissible)
    tied = [c for c in admissible if counts[c] == most_failing]
    return {
        "counts": counts,
        "admissible": admissible,
        "chosen": _break_tie(tied),
        "B": agreement_alone,
    }


def _write_csv(outcomes: list[Row], path: Path) -> None:
    with Path(path).open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "pass_date",
                "measured",
                "n_rows",
                "n_fail_agreement",
                "n_fail_clause_only",
                "clause_only_polygons",
                "pooled_gap_pp",
                "k1",
                "k2",
                "k3",
                "k4",
            ]
        )
        for outcome in outcomes:
            writer.writerow(
                [
                    outcome["pass_date"],
                    str(outcome["measured"]),
                    outcome["n_rows"],
                    outcome["n_fail_agreement"],
                    outcome["n_fail_clause_only"],
                    ";".join(outcome["clause_only_polygons"]),
                    f"{outcome['pooled_gap_pp']:.3f}",
                    str(outcome["k1"]),
                    str(outcome["k2"]),
                    str(outcome["k3"]),
                    str(outcome["k4"]),
                ]
            )


def _flag(fails: bool) -> str:
    return "FAIL" if fails else "ok"


def _report(
    gap_csv: Path,
    total_rows: int,
    rows: list[Row],
    outcomes: list[Row],
    result: dict[str, Any],
) -> str:
    digest = hashlib.sha256(Path(gap_csv).read_bytes()).hexdigest()
    measured = [outcome for outcome in outcomes if outcome["measured"]]
    unmeasured = [outcome for outcome in outcomes if not outcome["measured"]]
    clause_alone = sum(outcome["n_fail_clause_only"] for outcome in outcomes)
    lines = [
        f"input: {Path(gap_csv).name}",
        f"sha256: {digest}",
        f"rows used: {len(rows)} (n_mutually_clear >= {MIN_CLEAR_PIXELS})",
        f"rows excluded for n < {MIN_CLEAR_PIXELS}: {total_rows - len(rows)}",
        "",
        f"measured dates ({len(measured)}, newest first); FAIL means verify would exit 3",
        "pass_date   n_rows  fail_agreement  clause_only  pooled_gap_pp  K1    K2    K3    K4",
    ]
    for outcome in measured:
        lines.append(
            f"{outcome['pass_date']}  {outcome['n_rows']:>6}  "
            f"{outcome['n_fail_agreement']:>14}  {outcome['n_fail_clause_only']:>11}  "
            f"{outcome['pooled_gap_pp']:>13.3f}  "
            f"{_flag(outcome['k1']):<4}  {_flag(outcome['k2']):<4}  "
            f"{_flag(outcome['k3']):<4}  {_flag(outcome['k4']):<4}"
        )
    lines.append("")
    for candidate in CANDIDATES:
        failing = result["counts"][candidate]
        lines.append(
            f"{candidate}: dates failing={failing} of {MEASURED_DATE_COUNT}, "
            f"share={failing / MEASURED_DATE_COUNT:.4f}"
        )
    lines += [
        f"B (agreement alone)={result['B']}",
        f"admissible: {', '.join(result['admissible'])}",
        f"chosen: {result['chosen']}",
        "",
        f"rows failing the clause alone (pass agreement, abs gap > {GAP_LIMIT_PP} pp): "
        f"{clause_alone} of {len(rows)}, share={clause_alone / len(rows):.4f}",
        "",
        "unmeasured dates (ramsar-28 only, not counted in the shares above):",
    ]
    for outcome in unmeasured:
        lines.append(f"  {outcome['pass_date']}: {outcome['n_rows']} rows")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Score exit-rule candidates K1 to K4.")
    parser.add_argument("--gap-csv", type=Path, default=DEFAULT_GAP)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    with args.gap_csv.open(newline="") as handle:
        total_rows = sum(1 for _ in csv.DictReader(handle))
    rows = load_rows(args.gap_csv)
    outcomes = date_outcomes(rows)
    result = choose(outcomes)
    _write_csv(outcomes, args.out)
    args.report.write_text(_report(args.gap_csv, total_rows, rows, outcomes, result))


if __name__ == "__main__":
    main()
