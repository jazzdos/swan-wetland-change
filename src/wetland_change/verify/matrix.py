"""The design's known-good verification matrix, scored from a run's checks.

Each row lists the check names that belong to it. Rows with no runtime check
are standing: a test or one-off script covers them, so a verify report shows
them as not-run with a note saying where.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wetland_change.verify.copernicus import CHECK_NAME as DISCOVERY_CHECK
from wetland_change.verify.ndvi import CHECK_NAME as NDVI_CHECK
from wetland_change.verify.ndvi import CORRELATION_CHECK_NAME as NDVI_CORRELATION_CHECK
from wetland_change.verify.waterbodies import CHECK_NAME as WATERBODIES_CHECK
from wetland_change.verify.waterbodies import SPEARMAN_CHECK_NAME as SPEARMAN_CHECK
from wetland_change.verify.wo import POOLED_WET_AREA_CHECK

if TYPE_CHECKING:
    from wetland_change.verify.checks import Check

PASS = "pass"
FAIL = "fail"
WARN = "warn"
NOT_RUN = "not-run"

PIXELS_CHECK = "pixels_vs_planetary_computer"
SCENE_GRID_CHECK = "scene_grid"
SCALING_CHECK = "reflectance_scaling"
SCL_SHARE_PREFIX = "scl_share"
WO_CHECK = "water_vs_dea_s2_wo"
FRESHNESS_PREFIX = "freshness_"

END_TO_END = "End to end"


@dataclass(frozen=True)
class MatrixRow:
    row: str
    names: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    note: str = ""

    def matches(self, name: str) -> bool:
        return name in self.names or name.startswith(self.prefixes)


MATRIX_ROWS: tuple[MatrixRow, ...] = (
    MatrixRow("Discovery finds every scene", (DISCOVERY_CHECK,)),
    MatrixRow("Reads the right bytes", (PIXELS_CHECK, SCENE_GRID_CHECK)),
    MatrixRow("Reflectance scaling", (SCALING_CHECK,)),
    # Covers scl_share_<class> and the scl_shares name given to an error.
    MatrixRow("SCL read and alignment", prefixes=(SCL_SHARE_PREFIX,)),
    MatrixRow(
        "Index arithmetic",
        note=(
            "no runtime check; standing test tests/test_indices.py, one-off "
            "scripts/compare_dea_tools_indices.py"
        ),
    ),
    MatrixRow("Water extent, live", (WO_CHECK, POOLED_WET_AREA_CHECK)),
    MatrixRow("Water extent, history", (WATERBODIES_CHECK, SPEARMAN_CHECK)),
    MatrixRow("NDVI", (NDVI_CHECK, NDVI_CORRELATION_CHECK)),
    MatrixRow(
        "GeoParquet output",
        note="no runtime check; standing test tests/test_geoparquet.py",
    ),
    MatrixRow(
        "STAC catalogue",
        note="no runtime check; standing test tests/test_catalogue.py",
    ),
    MatrixRow(
        "Incremental and idempotent",
        note="no runtime check; standing test tests/test_golden_run.py",
    ),
    MatrixRow(
        "Change detection",
        note="no runtime check; standing test tests/test_change.py",
    ),
    MatrixRow(
        "Scheduled job alive",
        prefixes=(FRESHNESS_PREFIX,),
        note=(
            "not produced by verify; freshness is a separate command, "
            "run `wetland-change freshness`"
        ),
    ),
    MatrixRow(END_TO_END, note="derived from the other rows and the overall verdict"),
)


def _row_status(matched: list[Check]) -> str:
    if any(c.blocking for c in matched):
        return FAIL
    if any(c.wet_area_only_failure for c in matched):
        return WARN
    if any(c.passed for c in matched) and not any(c.errored for c in matched):
        return PASS
    return NOT_RUN


def matrix_status(checks: list[Check]) -> list[dict[str, Any]]:
    """One entry per design row: status is pass, fail, warn or not-run.

    `n_fail` counts blocking failures; `n_warn` counts live water checks that
    failed only the wet area clause
    (docs/decisions/0008-exit-code-for-live-water-check-failures.md).
    `n_skipped` counts skips that carry a reason only; skips whose source
    raised are in `n_errored`, so the five counts add up to the row's checks.
    Advisory rows (ADR 0012, docs/decisions/0012-live-check-limits-apply-to-their-
    calibrated-layer.md) are left out of the status and of those five counts
    and are counted in `n_advisory`.
    """
    verdict = [c for c in checks if not c.advisory]
    rows: list[dict[str, Any]] = []
    for spec in MATRIX_ROWS:
        matched = (
            []
            if spec.row == END_TO_END
            else [c for c in verdict if spec.matches(c.name)]
        )
        rows.append(
            {
                "row": spec.row,
                "status": _row_status(matched) if matched else NOT_RUN,
                "n_pass": sum(c.passed is True for c in matched),
                "n_fail": sum(c.blocking for c in matched),
                "n_warn": sum(c.wet_area_only_failure for c in matched),
                "n_skipped": sum(c.passed is None and not c.errored for c in matched),
                "n_errored": sum(c.errored for c in matched),
                "n_advisory": (
                    0
                    if spec.row == END_TO_END
                    else sum(c.advisory and spec.matches(c.name) for c in checks)
                ),
                "check_names": list(dict.fromkeys(c.name for c in matched)),
                "note": "" if matched else spec.note,
            }
        )
    end = next(r for r in rows if r["row"] == END_TO_END)
    if any(r["status"] == FAIL for r in rows):
        end["status"] = FAIL
    elif not any(c.blocking or c.errored for c in verdict):
        if any(c.wet_area_only_failure for c in verdict):
            end["status"] = WARN
        elif any(c.passed for c in verdict):
            end["status"] = PASS
    return rows
