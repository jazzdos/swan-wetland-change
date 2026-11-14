"""Per-layer counts for the live verify checks, recomputed from two committed reports.

Issue #2 (story st-a32a): `wetland-change verify` scores `water_vs_dea_s2_wo` and
`ndvi_vs_dea_nbart` on ramsar polygons (polygon_id `ramsar-<n>`) and on DEA
Waterbodies polygons (polygon_id `dea-<uid>`), with limits calibrated on ramsar
only. This script splits each check's rows by layer and reports pass, fail, warn,
skipped and errored counts, pooled agreement, pooled wet area gap, NDVI Pearson
correlation and the median absolute NDVI difference, plus water size bins by
n_mutually_clear. It then states what verify would exit under two rules: every
layer blocking (as run) and ramsar rows only (ADR 0012).

It reads only the two committed reproduction reports named in DEFAULT_INPUTS
(stdlib only, no rasters, no network) and is deterministic for those files.

  uv run python docs/research/2026-11-12-live-check-layers.py \
      [--input LABEL=JSON ...] [--out CSV] [--report TXT]

Paths default to files beside this script.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

HERE: Final = Path(__file__).resolve().parent
DEFAULT_INPUTS: Final[dict[str, Path]] = {
    "2026-11-11": HERE / "2026-11-12-issue-2-repro-20261111.json",
    "2026-10-29": HERE / "2026-11-12-issue-2-repro-20261029.json",
}
DEFAULT_OUT: Final = HERE / "2026-11-12-live-check-layers.csv"
DEFAULT_REPORT: Final = HERE / "2026-11-12-live-check-layers.txt"

FIELDS: Final = (
    "label",
    "run_id",
    "check",
    "layer",
    "size_bin",
    "n_rows",
    "n_pass",
    "n_fail",
    "n_warn",
    "n_skipped",
    "n_errored",
    "pooled_agreement",
    "n_mutually_clear",
    "pooled_wet_gap_pp",
    "n_wet_gap_rows",
    "pearson",
    "n_pearson_rows",
    "median_abs_diff",
)

WATER: Final = "water_vs_dea_s2_wo"
NDVI: Final = "ndvi_vs_dea_nbart"
POOLED_NAMES: Final = (
    "water_vs_dea_s2_wo_pooled_wet_area",
    "ndvi_correlation_vs_dea_nbart",
)
PER_POLYGON_CHECKS: Final = (WATER, NDVI)
LAYERS: Final = ("all", "ramsar", "dea_waterbody")
SIZE_BINS: Final = (
    ("<100", 0, 100),
    ("100-199", 100, 200),
    ("200-499", 200, 500),
    ("500-1999", 500, 2000),
    ("2000-9999", 2000, 10000),
    ("10000+", 10000, None),
)
GAP_LIMIT_PP: Final = 5.0
MIN_CORRELATION_ROWS: Final = 5
MIN_CORRELATION: Final = 0.95
RULES: Final = (("every layer", "all"), ("ADR 0012", "ramsar"))

Check = dict[str, Any]
Payload = dict[str, Any]


def load_payload(path: Path) -> Payload:
    """Read a verification report JSON."""
    with Path(path).open() as handle:
        payload: Payload = json.load(handle)
    return payload


def sha256(path: Path) -> str:
    """Hex SHA-256 of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _detail(check: Check) -> dict[str, Any]:
    detail = check.get("detail")
    return detail if isinstance(detail, dict) else {}


def layer_of(check: Check) -> str:
    """`ramsar`, `dea_waterbody` or `none`, from the detail polygon_id prefix."""
    polygon_id = _detail(check).get("polygon_id")
    if isinstance(polygon_id, str):
        if polygon_id.startswith("ramsar-"):
            return "ramsar"
        if polygon_id.startswith("dea-"):
            return "dea_waterbody"
    return "none"


def status_of(check: Check) -> str:
    """`pass`, `fail`, `warn` or `skipped` under the ramsar limit applied to every row.

    A warn is a water row whose agreement met its threshold and which failed only
    the wet area clause.
    """
    passed = check.get("passed")
    if passed is None:
        return "skipped"
    if passed is False:
        measured = check.get("measured")
        threshold = check.get("threshold")
        if (
            check.get("name") == WATER
            and _detail(check).get("wet_area_passed") is False
            and measured is not None
            and threshold is not None
            and measured >= threshold
        ):
            return "warn"
        return "fail"
    return "pass"


def _is_errored(check: Check) -> bool:
    return status_of(check) == "skipped" and "error" in _detail(check)


def _is_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _rows(payload: Payload, name: str, layer: str) -> list[Check]:
    return [
        check
        for check in payload["checks"]
        if check.get("name") == name and (layer == "all" or layer_of(check) == layer)
    ]


def _scored(rows: Sequence[Check]) -> list[Check]:
    return [row for row in rows if status_of(row) != "skipped"]


def _bin_of(n_clear: int) -> str:
    for bin_label, low, high in SIZE_BINS:
        if n_clear >= low and (high is None or n_clear < high):
            return bin_label
    raise ValueError(f"no size bin for n_mutually_clear={n_clear}")


def _pooled_agreement(rows: Sequence[Check]) -> tuple[float | None, int]:
    used = [
        (row["measured"], _detail(row)["n_mutually_clear"])
        for row in _scored(rows)
        if row.get("measured") is not None
        and (_detail(row).get("n_mutually_clear") or 0) > 0
    ]
    total = sum(n_clear for _, n_clear in used)
    if total == 0:
        return None, 0
    return sum(measured * n_clear for measured, n_clear in used) / total, total


def _pooled_gap(rows: Sequence[Check]) -> tuple[float | None, int]:
    """Integer wet pixel counts as ADR 0008: round(share * n) per row."""
    pipeline_wet = wo_wet = total = row_count = 0
    for row in _scored(rows):
        detail = _detail(row)
        n_clear = detail.get("n_mutually_clear") or 0
        pipeline = detail.get("wet_area_pipeline")
        reference = detail.get("wet_area_wo")
        if n_clear <= 0 or pipeline is None or reference is None:
            continue
        pipeline_wet += round(pipeline * n_clear)
        wo_wet += round(reference * n_clear)
        total += n_clear
        row_count += 1
    if total == 0:
        return None, 0
    return 100.0 * (pipeline_wet - wo_wet) / total, row_count


def _pearson(rows: Sequence[Check]) -> tuple[float | None, int]:
    pairs = [
        (_detail(row)["ndvi_median"], _detail(row)["dea_ndvi_median"])
        for row in _scored(rows)
        if _is_finite(_detail(row).get("ndvi_median"))
        and _is_finite(_detail(row).get("dea_ndvi_median"))
    ]
    if len(pairs) < 2:
        return None, len(pairs)
    pipeline_values = [pipeline for pipeline, _ in pairs]
    reference_values = [reference for _, reference in pairs]
    return statistics.correlation(pipeline_values, reference_values), len(pairs)


def _median_abs_diff(rows: Sequence[Check]) -> float | None:
    values = [
        row["measured"] for row in _scored(rows) if _is_finite(row.get("measured"))
    ]
    return statistics.median(values) if values else None


def _counts(rows: Sequence[Check]) -> dict[str, int]:
    statuses = [status_of(row) for row in rows]
    return {
        "n_rows": len(rows),
        "n_pass": statuses.count("pass"),
        "n_fail": statuses.count("fail"),
        "n_warn": statuses.count("warn"),
        "n_skipped": statuses.count("skipped"),
        "n_errored": sum(1 for row in rows if _is_errored(row)),
    }


def _fmt(value: float | int | None, spec: str = "") -> str:
    if value is None:
        return ""
    return format(value, spec)


def _base_row(
    label: str, payload: Payload, name: str, layer: str, size_bin: str
) -> dict[str, str]:
    row = dict.fromkeys(FIELDS, "")
    row.update(
        {
            "label": label,
            "run_id": str(payload["run_id"]),
            "check": name,
            "layer": layer,
            "size_bin": size_bin,
        }
    )
    return row


def _fill_counts(row: dict[str, str], rows: Sequence[Check]) -> None:
    for key, value in _counts(rows).items():
        row[key] = str(value)


def _fill_water(row: dict[str, str], rows: Sequence[Check]) -> None:
    agreement, n_clear = _pooled_agreement(rows)
    gap, gap_row_count = _pooled_gap(rows)
    row["pooled_agreement"] = _fmt(agreement, ".6f")
    row["n_mutually_clear"] = _fmt(n_clear if agreement is not None else None)
    row["pooled_wet_gap_pp"] = _fmt(gap, ".4f")
    row["n_wet_gap_rows"] = _fmt(gap_row_count if gap is not None else None)


def summarise(label: str, payload: Payload) -> list[dict[str, str]]:
    """CSV rows (as strings) for one report: layer rows first, then water size bins."""
    out: list[dict[str, str]] = []
    for name in PER_POLYGON_CHECKS:
        for layer in LAYERS:
            rows = _rows(payload, name, layer)
            row = _base_row(label, payload, name, layer, "all")
            _fill_counts(row, rows)
            if name == WATER:
                _fill_water(row, rows)
            else:
                pearson, pair_count = _pearson(rows)
                row["pearson"] = _fmt(pearson, ".6f")
                row["n_pearson_rows"] = _fmt(
                    pair_count if pearson is not None else None
                )
                row["median_abs_diff"] = _fmt(_median_abs_diff(rows), ".6f")
            out.append(row)
    for layer in ("ramsar", "dea_waterbody"):
        by_bin: dict[str, list[Check]] = {name: [] for name, _, _ in SIZE_BINS}
        for check in _scored(_rows(payload, WATER, layer)):
            n_clear = _detail(check).get("n_mutually_clear")
            if isinstance(n_clear, int):
                by_bin[_bin_of(n_clear)].append(check)
        for bin_label, _, _ in SIZE_BINS:
            rows = by_bin[bin_label]
            if bin_label == "<100" and not rows:
                continue
            row = _base_row(label, payload, WATER, layer, bin_label)
            _fill_counts(row, rows)
            _fill_water(row, rows)
            out.append(row)
    return out


def _blocking_ids(rows: Sequence[Check]) -> list[str]:
    return sorted(
        str(_detail(row).get("polygon_id")) for row in rows if status_of(row) == "fail"
    )


def outcome(payload: Payload) -> dict[str, Any]:
    """What verify would exit under each rule, keyed by rule name."""
    other_failing = sorted(
        {
            str(check["name"])
            for check in payload["checks"]
            if check.get("passed") is False
            and check["name"] not in PER_POLYGON_CHECKS
            and check["name"] not in POOLED_NAMES
        }
    )
    result: dict[str, Any] = {}
    for rule, layer in RULES:
        water_rows = _rows(payload, WATER, layer)
        ndvi_rows = _rows(payload, NDVI, layer)
        water_ids = _blocking_ids(water_rows)
        ndvi_ids = _blocking_ids(ndvi_rows)
        gap, gap_row_count = _pooled_gap(water_rows)
        pearson, pair_count = _pearson(ndvi_rows)
        is_gap_passed = gap is not None and abs(gap) <= GAP_LIMIT_PP
        is_correlation_passed = (
            pearson is not None
            and pair_count >= MIN_CORRELATION_ROWS
            and pearson >= MIN_CORRELATION
        )
        result[rule] = {
            "water_blocking": len(water_ids),
            "water_blocking_ids": water_ids,
            "ndvi_blocking": len(ndvi_ids),
            "ndvi_blocking_ids": ndvi_ids,
            "pooled_wet_gap_pp": gap,
            "n_wet_gap_rows": gap_row_count,
            "pooled_gap_passed": is_gap_passed,
            "ndvi_pearson": pearson,
            "n_pearson_rows": pair_count,
            "correlation_passed": is_correlation_passed,
            "other_failing_checks": other_failing,
            "exits_3": bool(
                water_ids
                or ndvi_ids
                or not is_gap_passed
                or not is_correlation_passed
                or other_failing
            ),
        }
    return result


LEFT_ALIGNED: Final = ("check", "layer", "size_bin")


def _table(rows: Sequence[Mapping[str, str]], columns: Sequence[str]) -> list[str]:
    widths = {
        column: max([len(column), *(len(row[column]) for row in rows)])
        for column in columns
    }
    lines = [
        "  ".join(column.ljust(widths[column]) for column in columns).rstrip(),
        "  ".join("-" * widths[column] for column in columns),
    ]
    for row in rows:
        cells = [
            row[column].ljust(widths[column])
            if column in LEFT_ALIGNED
            else row[column].rjust(widths[column])
            for column in columns
        ]
        lines.append("  ".join(cells).rstrip())
    return lines


def _ids(ids: Sequence[str]) -> str:
    return f" ({', '.join(ids)})" if ids else ""


def _verdict(is_passed: bool) -> str:
    return "pass" if is_passed else "FAIL"


def _outcome_lines(result: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for rule, _ in RULES:
        item = result[rule]
        lines += [
            f"  rule: {rule}",
            f"    water blocking rows: {item['water_blocking']}"
            f"{_ids(item['water_blocking_ids'])}",
            f"    NDVI blocking rows: {item['ndvi_blocking']}"
            f"{_ids(item['ndvi_blocking_ids'])}",
            f"    pooled wet gap: {_fmt(item['pooled_wet_gap_pp'], '+.4f')} pp over "
            f"{item['n_wet_gap_rows']} rows, limit abs <= {GAP_LIMIT_PP}: "
            f"{_verdict(item['pooled_gap_passed'])}",
            f"    NDVI correlation: {_fmt(item['ndvi_pearson'], '.6f')} over "
            f"{item['n_pearson_rows']} rows, limit n >= {MIN_CORRELATION_ROWS} and "
            f"r >= {MIN_CORRELATION}: {_verdict(item['correlation_passed'])}",
            "    other failing checks: "
            f"{', '.join(item['other_failing_checks']) or 'none'}",
            f"    verify exits 3: {'yes' if item['exits_3'] else 'no'}",
        ]
    return lines


WATER_COLUMNS: Final = (
    "layer",
    "n_rows",
    "n_pass",
    "n_fail",
    "n_warn",
    "n_skipped",
    "n_errored",
    "pooled_agreement",
    "n_mutually_clear",
    "pooled_wet_gap_pp",
    "n_wet_gap_rows",
)
NDVI_COLUMNS: Final = (
    "layer",
    "n_rows",
    "n_pass",
    "n_fail",
    "n_skipped",
    "n_errored",
    "pearson",
    "n_pearson_rows",
    "median_abs_diff",
)
BIN_COLUMNS: Final = (
    "size_bin",
    "n_rows",
    "n_pass",
    "n_fail",
    "n_warn",
    "pooled_agreement",
    "n_mutually_clear",
    "pooled_wet_gap_pp",
    "n_wet_gap_rows",
)


def report_text(inputs: Mapping[str, Path]) -> str:
    """Fixed-width report for the labelled inputs; deterministic for the files."""
    lines = [
        "Live verify checks split by layer (ramsar, dea_waterbody), issue #2, st-a32a",
        "Source CRS: EPSG:32750 (every item in both reports is a UTM zone 50S tile); "
        "operation CRS: EPSG:32750.",
        "Units: agreement and wet shares are fractions, wet area gaps are percentage "
        "points, NDVI values and differences are unitless.",
        "Status is the ramsar-limit verdict applied to every row (the reports pre-date "
        "ADR 0012); warn is a water row that met agreement and failed only the wet "
        "area clause.",
        "",
    ]
    rows_by_label: dict[str, list[dict[str, str]]] = {}
    outcome_by_label: dict[str, dict[str, Any]] = {}
    for label, path in inputs.items():
        payload = load_payload(path)
        rows_by_label[label] = summarise(label, payload)
        outcome_by_label[label] = outcome(payload)
        lines += [
            f"input {label}: {Path(path).name}",
            f"  sha256: {sha256(path)}",
            f"  run_id: {payload['run_id']}",
            f"  git_commit: {payload['git_commit']}",
            f"  generated_at: {payload['generated_at']}",
        ]
    for label, rows in rows_by_label.items():
        layer_rows = [row for row in rows if row["size_bin"] == "all"]
        water_rows = [row for row in layer_rows if row["check"] == WATER]
        ndvi_rows = [row for row in layer_rows if row["check"] == NDVI]
        bin_rows = [
            row
            for row in rows
            if row["size_bin"] != "all" and row["layer"] == "dea_waterbody"
        ]
        lines += [
            "",
            f"== {label}: {WATER} by layer ==",
            *_table(water_rows, WATER_COLUMNS),
            "",
            f"== {label}: {NDVI} by layer ==",
            *_table(ndvi_rows, NDVI_COLUMNS),
            "",
            f"== {label}: {WATER} on dea_waterbody by n_mutually_clear (scored) ==",
            *_table(bin_rows, BIN_COLUMNS),
            "",
            f"== {label}: verify outcome by rule ==",
            *_outcome_lines(outcome_by_label[label]),
        ]
    return "\n".join(lines) + "\n"


def _parse_inputs(values: Sequence[str] | None) -> dict[str, Path]:
    if not values:
        return dict(DEFAULT_INPUTS)
    parsed: dict[str, Path] = {}
    for value in values:
        label, separator, raw_path = value.partition("=")
        if not separator or not label or not raw_path:
            raise SystemExit(f"--input expects LABEL=JSON, got {value!r}")
        parsed[label] = Path(raw_path)
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Split live verify checks by layer.")
    parser.add_argument("--input", action="append", metavar="LABEL=JSON")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    inputs = _parse_inputs(args.input)
    rows: list[dict[str, str]] = []
    for label, path in inputs.items():
        rows += summarise(label, load_payload(path))
    with args.out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FIELDS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    args.report.write_text(report_text(inputs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
