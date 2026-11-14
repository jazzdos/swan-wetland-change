"""Which AOI layer a live check's limit applies to.

See docs/decisions/0012-live-check-limits-apply-to-their-calibrated-layer.md.
The live per-polygon limits (`water_vs_dea_s2_wo` agreement and wet area,
`ndvi_vs_dea_nbart` median tolerance) were calibrated on the ramsar layer.
Ramsar rows keep their verdict, including per-polygon overrides and the
ADR 0008 warn rule. A row on any other layer keeps its measured value,
reference and detail but gets `passed` None, `detail["advisory"]` True and
`detail["within_ramsar_limit"]`, the verdict it would have had on the ramsar
limits. Advisory rows are reported as one summary per live check and layer.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any, Final

from wetland_change.verify.checks import Check
from wetland_change.verify.ndvi import CHECK_NAME as NDVI_CHECK
from wetland_change.verify.ndvi import MEDIAN_TOLERANCE
from wetland_change.verify.wo import (
    WET_AREA_MAX_PP,
    pooled_agreement,
    pooled_wet_area,
)

BLOCKING_LAYER: Final = "ramsar"
WO_CHECK: Final = "water_vs_dea_s2_wo"
LIVE_CHECKS: Final = (WO_CHECK, NDVI_CHECK)
LAYER_RULE: Final = (
    "docs/decisions/0012-live-check-limits-apply-to-their-calibrated-layer.md"
)


def apply_layer_rule(checks: Iterable[Check], layers: Mapping[str, str]) -> list[Check]:
    """Mark live rows by layer; rows off the ramsar layer become advisory.

    `layers` maps polygon_id to its AOI layer. Only a live check whose detail
    names a polygon_id in `layers` changes. Scene-level rows, unknown polygon
    ids, pooled and correlation checks, history rows and non-live checks are
    returned as they are. Returns a new list and never mutates its input.
    """
    out: list[Check] = []
    for check in checks:
        polygon_id = check.detail.get("polygon_id")
        if (
            check.name not in LIVE_CHECKS
            or not isinstance(polygon_id, str)
            or polygon_id not in layers
        ):
            out.append(check)
            continue
        layer = layers[polygon_id]
        if layer == BLOCKING_LAYER:
            out.append(replace(check, detail={**check.detail, "layer": layer}))
            continue
        detail = {
            **check.detail,
            "layer": layer,
            "advisory": True,
            "within_ramsar_limit": check.passed,
            "advisory_rule": LAYER_RULE,
        }
        if check.name == WO_CHECK:
            detail["wet_area_only"] = check.wet_area_only_failure
        out.append(replace(check, passed=None, detail=detail))
    return out


def advisory_summaries(checks: Iterable[Check]) -> list[dict[str, Any]]:
    """One summary per live check and non-ramsar layer present in the rows.

    Both live checks are always summarised for a layer, so a check with no rows
    there reports zero counts. Returns an empty list when no row is advisory.
    """
    rows = [c for c in checks if c.advisory]
    summaries: list[dict[str, Any]] = []
    for layer in sorted({str(c.detail["layer"]) for c in rows}):
        for name in LIVE_CHECKS:
            mine = [c for c in rows if c.name == name and c.detail["layer"] == layer]
            scored = [
                c for c in mine if c.detail.get("within_ramsar_limit") is not None
            ]
            summary: dict[str, Any] = {
                "check": name,
                "layer": layer,
                "advisory": True,
                "rule": LAYER_RULE,
                "n_rows": len(mine),
                "n_scored": len(scored),
                "n_skipped": len(mine) - len(scored),
                "n_errored": sum(c.errored for c in mine),
                "n_outside_ramsar_limit": sum(
                    c.detail.get("within_ramsar_limit") is False for c in scored
                ),
            }
            if name == WO_CHECK:
                agreement = pooled_agreement(scored)
                wet = pooled_wet_area(scored)
                summary.update(
                    n_wet_area_only=sum(
                        c.detail.get("wet_area_only") is True for c in scored
                    ),
                    pooled_agreement=agreement[0] if agreement else None,
                    n_mutually_clear=agreement[1] if agreement else 0,
                    pooled_wet_gap_pp=wet.gap_pp if wet else None,
                    wet_area_max_pp=WET_AREA_MAX_PP,
                    units=(
                        "agreement as a fraction of mutually clear pixels; "
                        "wet gap in percentage points"
                    ),
                )
            else:
                differences = [
                    c.measured
                    for c in scored
                    if c.measured is not None and math.isfinite(c.measured)
                ]
                summary.update(
                    median_abs_diff=(
                        statistics.median(differences) if differences else None
                    ),
                    tolerance=MEDIAN_TOLERANCE,
                    units="NDVI (unitless)",
                )
            summaries.append(summary)
    return summaries


def advisory_note(summary: Mapping[str, Any]) -> str:
    """One report line for a summary; no pipe and no polygon id."""
    counts = (
        f"{summary['n_scored']} scored, {summary['n_skipped']} skipped "
        f"({summary['n_errored']} errored), "
        f"{summary['n_outside_ramsar_limit']} outside the ramsar limit"
    )
    if summary["check"] == WO_CHECK:
        agreement = summary["pooled_agreement"]
        gap = summary["pooled_wet_gap_pp"]
        pooled = (
            f"{agreement:.4f} over {summary['n_mutually_clear']} px"
            if agreement is not None
            else "n/a"
        )
        wet = f"{gap:+.2f} pp" if gap is not None else "n/a"
        return (
            f"{counts} ({summary['n_wet_area_only']} on wet area alone); "
            f"pooled agreement {pooled}, pooled wet gap {wet} "
            f"(ramsar limit {summary['wet_area_max_pp']} pp); advisory under ADR 0012"
        )
    median = summary["median_abs_diff"]
    text = f"{median:.4f}" if median is not None else "n/a"
    return (
        f"{counts}; median absolute difference {text} "
        f"(ramsar tolerance {summary['tolerance']}); advisory under ADR 0012"
    )
