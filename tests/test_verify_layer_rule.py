"""The layer rule: a live check's limit applies to the layer it was calibrated on.

See docs/decisions/0012-live-check-limits-apply-to-their-calibrated-layer.md.
Ramsar rows keep their verdict; rows on other layers are measured, stored and
advisory.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from wetland_change.store import OutputStore
from wetland_change.verify.checks import (
    Check,
    check_note,
    verdict_checks,
    write_report,
)
from wetland_change.verify.layers import (
    LAYER_RULE,
    advisory_note,
    advisory_summaries,
    apply_layer_rule,
)
from wetland_change.verify.matrix import MATRIX_ROWS, matrix_status
from wetland_change.verify.wo import pooled_wet_area, pooled_wet_area_check

WO = "water_vs_dea_s2_wo"
NDVI = "ndvi_vs_dea_nbart"
ITEM = "S2A_T50HLJ_20261029T021516_L2A"

LAYERS = {
    "ramsar-12": "ramsar",
    "ramsar-13": "ramsar",
    "dea-a": "dea_waterbody",
    "dea-b": "dea_waterbody",
    "dea-c": "dea_waterbody",
    "dea-d": "dea_waterbody",
    "dea-e": "dea_waterbody",
}


def water(
    polygon_id: str,
    *,
    passed: bool,
    measured: float,
    n: int = 1000,
    pipeline: float = 0.5,
    wo: float = 0.5,
    wet_passed: bool = True,
    diff_pp: float = 0.0,
) -> Check:
    return Check(
        WO,
        passed,
        measured,
        0.91,
        f"wo.tif#{polygon_id}",
        {
            "polygon_id": polygon_id,
            "item": ITEM,
            "n_mutually_clear": n,
            "wet_area_pipeline": pipeline,
            "wet_area_wo": wo,
            "wet_area_diff_pp": diff_pp,
            "wet_area_max_pp": 5.0,
            "wet_area_passed": wet_passed,
        },
    )


def wet_only(polygon_id: str) -> Check:
    return water(
        polygon_id,
        passed=False,
        measured=0.95,
        pipeline=0.58,
        wo=0.50,
        wet_passed=False,
        diff_pp=8.0,
    )


def ndvi(polygon_id: str, abs_diff: float) -> Check:
    return Check(
        NDVI,
        abs_diff <= 0.05,
        abs_diff,
        0.05,
        f"nbart#{polygon_id}",
        {
            "polygon_id": polygon_id,
            "item": ITEM,
            "ndvi_median": 0.5,
            "dea_ndvi_median": 0.5 + abs_diff,
            "abs_diff": abs_diff,
        },
    )


def errored_dea() -> Check:
    detail = {"polygon_id": "dea-d", "error": "RasterioIOError: x"}
    return Check(WO, None, None, None, "r", detail)


def reason_skip_dea() -> Check:
    detail = {"polygon_id": "dea-e", "reason": "fewer than 100 mutually clear pixels"}
    return Check(WO, None, None, None, "r", detail)


def dea_water_rows() -> list[Check]:
    return [
        water("dea-a", passed=True, measured=0.99),
        water("dea-b", passed=False, measured=0.80, n=3000),
        wet_only("dea-c"),
        errored_dea(),
        reason_skip_dea(),
    ]


def ramsar_water_pass() -> Check:
    return water("ramsar-12", passed=True, measured=0.97)


def test_ramsar_row_keeps_its_verdict() -> None:
    row = water("ramsar-12", passed=False, measured=0.70)
    (out,) = apply_layer_rule([row], LAYERS)
    assert out.passed is False
    assert out.blocking is True
    assert out.detail["layer"] == "ramsar"
    assert "advisory" not in out.detail
    assert {k: v for k, v in out.detail.items() if k != "layer"} == row.detail
    assert (out.name, out.measured, out.threshold, out.reference) == (
        row.name,
        row.measured,
        row.threshold,
        row.reference,
    )


def test_other_layer_row_becomes_advisory() -> None:
    row = water("dea-a", passed=False, measured=0.70)
    (out,) = apply_layer_rule([row], LAYERS)
    assert out.passed is None
    assert (out.name, out.measured, out.threshold, out.reference) == (
        row.name,
        row.measured,
        row.threshold,
        row.reference,
    )
    for key, value in row.detail.items():
        assert out.detail[key] == value
    assert out.detail["layer"] == "dea_waterbody"
    assert out.detail["advisory"] is True
    assert out.detail["within_ramsar_limit"] is False
    assert out.detail["advisory_rule"] == LAYER_RULE
    assert out.advisory is True
    assert out.blocking is False
    assert out.wet_area_only_failure is False
    assert out.errored is False


def test_wet_area_only_flag_marks_wet_only_water_rows() -> None:
    wet, ok = apply_layer_rule(
        [wet_only("dea-a"), water("dea-b", passed=True, measured=0.99)], LAYERS
    )
    assert wet.detail["wet_area_only"] is True
    assert ok.detail["wet_area_only"] is False
    (ndvi_row,) = apply_layer_rule([ndvi("dea-a", 0.3)], LAYERS)
    assert "wet_area_only" not in ndvi_row.detail


def test_unscoped_rows_are_returned_unchanged() -> None:
    rows = [
        Check(WO, None, None, None, "r", {"reason": "no DEA WO scene found"}),
        water("unknown-1", passed=False, measured=0.5),
        Check("water_vs_dea_s2_wo_pooled_wet_area", False, 6.0, 5.0, "r", {}),
        Check(
            "water_vs_dea_waterbodies", False, 0.2, 0.5, "r", {"polygon_id": "dea-a"}
        ),
        Check("reflectance_scaling", True, 0.0, 0.0, "r", {}),
    ]
    assert apply_layer_rule(rows, LAYERS) == rows


def test_apply_layer_rule_does_not_mutate_its_input() -> None:
    rows = [
        water("dea-a", passed=False, measured=0.7),
        water("ramsar-12", passed=True, measured=0.9),
    ]
    before = copy.deepcopy(rows)
    out = apply_layer_rule(rows, LAYERS)
    assert rows == before
    assert out is not rows


def test_advisory_flag_alone_is_not_blocking_and_is_dropped_from_verdicts() -> None:
    row = Check(WO, False, 0.7, 0.91, "r", {"advisory": True, "wet_area_passed": False})
    assert row.blocking is False
    assert row.wet_area_only_failure is False
    kept = ramsar_water_pass()
    assert verdict_checks([row, kept]) == [kept]


def _dea_summaries() -> list[dict[str, Any]]:
    rows = apply_layer_rule(dea_water_rows() + [ramsar_water_pass()], LAYERS)
    return advisory_summaries(rows)


def test_water_summary_counts_and_pools_scored_rows() -> None:
    summaries = _dea_summaries()
    assert [(s["check"], s["layer"]) for s in summaries] == [
        (WO, "dea_waterbody"),
        (NDVI, "dea_waterbody"),
    ]
    water_summary, ndvi_summary = summaries
    assert water_summary["advisory"] is True
    assert water_summary["rule"] == LAYER_RULE
    assert water_summary["n_rows"] == 5
    assert water_summary["n_scored"] == 3
    assert water_summary["n_skipped"] == 2
    assert water_summary["n_errored"] == 1
    assert water_summary["n_outside_ramsar_limit"] == 2
    assert water_summary["n_wet_area_only"] == 1
    assert water_summary["pooled_agreement"] == pytest.approx(4340 / 5000)
    assert water_summary["n_mutually_clear"] == 5000
    assert water_summary["pooled_wet_gap_pp"] == pytest.approx(1.6)
    assert water_summary["wet_area_max_pp"] == 5.0
    assert ndvi_summary["n_rows"] == 0
    assert ndvi_summary["n_scored"] == 0
    assert ndvi_summary["median_abs_diff"] is None
    assert ndvi_summary["tolerance"] == 0.05


def _dea_ndvi_rows() -> list[Check]:
    return apply_layer_rule(
        [ndvi("dea-a", 0.01), ndvi("dea-b", 0.30), ndvi("dea-c", 0.04)], LAYERS
    )


def test_ndvi_summary_reports_the_median_absolute_difference() -> None:
    summary = next(
        s for s in advisory_summaries(_dea_ndvi_rows()) if s["check"] == NDVI
    )
    assert summary["median_abs_diff"] == pytest.approx(0.04)
    assert summary["n_outside_ramsar_limit"] == 1
    assert summary["n_scored"] == 3
    assert summary["tolerance"] == 0.05


def test_advisory_summaries_are_empty_for_ramsar_only_rows() -> None:
    rows = apply_layer_rule([ramsar_water_pass(), ndvi("ramsar-13", 0.01)], LAYERS)
    assert advisory_summaries(rows) == []


def test_advisory_note_states_counts_and_pooled_figures() -> None:
    water_summary, ndvi_summary = _dea_summaries()
    text = advisory_note(water_summary)
    for part in (
        "3 scored",
        "2 skipped (1 errored)",
        "2 outside the ramsar limit (1 on wet area alone)",
        "pooled agreement 0.8680 over 5000 px",
        "pooled wet gap +1.60 pp",
        "ADR 0012",
    ):
        assert part in text
    assert "|" not in text
    assert "dea-" not in text
    assert "n/a" in advisory_note(ndvi_summary)
    summary = next(
        s for s in advisory_summaries(_dea_ndvi_rows()) if s["check"] == NDVI
    )
    assert "median absolute difference 0.0400" in advisory_note(summary)


def _ramsar_rows() -> list[Check]:
    return [
        water("ramsar-12", passed=True, measured=0.97, pipeline=0.52, wo=0.50),
        water("ramsar-13", passed=True, measured=0.97, pipeline=0.51, wo=0.50),
    ]


def test_pooled_wet_area_check_layer_option_names_the_layer() -> None:
    rows = _ramsar_rows()
    plain = pooled_wet_area_check(rows)
    layered = pooled_wet_area_check(rows, layer="ramsar")
    assert plain is not None
    assert layered is not None
    assert "layer" not in plain.detail
    assert plain.detail["rule"] == (
        "pooled over every scored live water check in the run, ADR 0008"
    )
    assert layered.detail["layer"] == "ramsar"
    assert "ADR 0008" in layered.detail["rule"]
    assert "ADR 0012" in layered.detail["rule"]
    assert layered.measured == plain.measured


def test_pooled_wet_area_ignores_passed_but_the_check_needs_scored_rows() -> None:
    rows = apply_layer_rule(dea_water_rows(), LAYERS)
    pooled = pooled_wet_area(rows)
    assert pooled is not None
    assert pooled.gap_pp == pytest.approx(1.6)
    assert pooled.n_mutually_clear == 5000
    assert pooled.n_checks == 3
    assert pooled_wet_area_check(rows) is None


def test_check_note_names_the_pooled_layer() -> None:
    rows = [
        water(f"ramsar-{index}", passed=True, measured=0.97, pipeline=0.51, wo=0.50)
        for index in range(5)
    ]
    pooled = pooled_wet_area_check(rows, layer="ramsar")
    assert pooled is not None
    text = check_note(pooled)
    assert "pooled wet area gap" in text
    assert "over 5 checks, limit 5.0 pp" in text
    assert "ramsar layer only" in text


def test_matrix_leaves_advisory_rows_out_of_status_and_counts() -> None:
    rows = apply_layer_rule(
        [
            ramsar_water_pass(),
            water("dea-a", passed=False, measured=0.7),
            water("dea-b", passed=False, measured=0.6),
            ndvi("dea-a", 0.3),
            Check(WO, None, None, None, "r", {"polygon_id": "dea-d", "error": "boom"}),
        ],
        LAYERS,
    )
    matrix = {r["row"]: r for r in matrix_status(rows)}
    live = matrix["Water extent, live"]
    assert live["status"] == "pass"
    assert (live["n_pass"], live["n_fail"], live["n_warn"]) == (1, 0, 0)
    assert (live["n_skipped"], live["n_errored"], live["n_advisory"]) == (0, 0, 3)
    assert matrix["NDVI"]["status"] == "not-run"
    assert matrix["NDVI"]["n_advisory"] == 1
    assert matrix["End to end"]["status"] == "pass"


def test_every_matrix_row_has_n_advisory_and_end_to_end_has_none() -> None:
    matrix = matrix_status([ramsar_water_pass()])
    assert len(matrix) == len(MATRIX_ROWS)
    assert all("n_advisory" in row for row in matrix)
    assert next(r for r in matrix if r["row"] == "End to end")["n_advisory"] == 0


def _mixed() -> list[Check]:
    return apply_layer_rule(
        [
            ramsar_water_pass(),
            ndvi("ramsar-13", 0.01),
            water("dea-a", passed=False, measured=0.70),
            errored_dea(),
            ndvi("dea-b", 0.30),
        ],
        LAYERS,
    )


def _report(tmp_path: Path, checks: list[Check]) -> tuple[dict[str, Any], str]:
    store = OutputStore(str(tmp_path / "out"))
    _, markdown = write_report(
        checks,
        store=store,
        run_id="r1",
        docs_dir=tmp_path / "docs",
        generated_at=datetime(2026, 11, 12, tzinfo=UTC),
    )
    assert markdown is not None
    return json.loads(store.read_bytes("verification/r1.json")), markdown.read_text()


def test_report_json_counts_advisory_rows_apart(tmp_path: Path) -> None:
    payload, _ = _report(tmp_path, _mixed())
    assert payload["all_passed"] is True
    assert payload["n_scored"] == 2
    assert payload["n_skipped"] == 0
    assert payload["n_errored"] == 0
    assert payload["n_warned"] == 0
    assert payload["n_advisory"] == 3
    assert len(payload["checks"]) == 5
    dea = [c for c in payload["checks"] if c["detail"].get("layer") == "dea_waterbody"]
    assert len(dea) == 3
    for row in dea:
        assert row["passed"] is None
        assert row["detail"]["advisory"] is True
    first = next(c for c in dea if c["detail"]["polygon_id"] == "dea-a")
    assert first["measured"] == 0.70
    assert first["reference"] == "wo.tif#dea-a"
    assert len(payload["advisory"]) == 2
    assert payload["advisory"][0]["n_rows"] == 2
    assert payload["advisory"][0]["n_errored"] == 1


def test_report_markdown_summarises_advisory_rows_in_their_own_section(
    tmp_path: Path,
) -> None:
    _, text = _report(tmp_path, _mixed())
    lines = text.splitlines()
    assert not any("dea-" in line for line in lines)
    assert (
        lines.index("## Matrix")
        < lines.index("## Advisory")
        < lines.index("## Runtime")
    )
    water_prefix = "| water_vs_dea_s2_wo | dea_waterbody |"
    ndvi_prefix = "| ndvi_vs_dea_nbart | dea_waterbody |"
    assert sum(line.startswith(water_prefix) for line in lines) == 1
    assert sum(line.startswith(ndvi_prefix) for line in lines) == 1
    header = "| row | status | pass | fail | warn | skipped | errored | note |"
    assert header in lines
    assert text.endswith("|\n")


def test_report_without_advisory_rows_has_no_advisory_section(tmp_path: Path) -> None:
    payload, text = _report(tmp_path, [ramsar_water_pass()])
    assert "## Advisory" not in text
    assert payload["advisory"] == []
    assert payload["n_advisory"] == 0


def test_advisory_wet_only_row_does_not_warn_or_clear_all_passed(
    tmp_path: Path,
) -> None:
    rows = apply_layer_rule([ramsar_water_pass(), wet_only("dea-a")], LAYERS)
    payload, _ = _report(tmp_path, rows)
    assert payload["n_warned"] == 0
    assert payload["all_passed"] is True
