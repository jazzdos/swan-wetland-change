"""Exit rule for live water checks.

See docs/decisions/0008-exit-code-for-live-water-check-failures.md. A check
that passes agreement and fails only the wet area clause is advisory (`warn`);
every other failure blocks. The pooled wet area check gates the run as a whole.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from wetland_change.store import OutputStore
from wetland_change.verify.checks import Check, write_report
from wetland_change.verify.matrix import matrix_status
from wetland_change.verify.wo import (
    POOLED_WET_AREA_CHECK,
    WET_AREA_MAX_PP,
    pooled_wet_area_check,
)

WO = "water_vs_dea_s2_wo"
ITEM = "S2A_T50HLJ_20261029T021516_L2A"


def wo_like(
    *,
    passed: bool | None,
    measured: float | None,
    threshold: float = 0.91,
    diff_pp: float = 0.0,
    wet_passed: bool | None = True,
    polygon_id: str = "ramsar-12",
    n: int = 1000,
    pipeline: float | None = 0.5,
    wo: float | None = 0.5,
) -> Check:
    return Check(
        WO,
        passed,
        measured,
        threshold,
        "https://example/wo.tif",
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


def wet_only() -> Check:
    return wo_like(passed=False, measured=0.9374, diff_pp=5.90, wet_passed=False)


def agreement_fail() -> Check:
    return wo_like(passed=False, measured=0.90, diff_pp=6.0, wet_passed=False)


def passing() -> Check:
    return wo_like(passed=True, measured=0.97)


def test_truth_table() -> None:
    only = wet_only()
    assert only.wet_area_only_failure is True and only.blocking is False
    both = agreement_fail()
    assert both.wet_area_only_failure is False and both.blocking is True
    ok = passing()
    assert ok.wet_area_only_failure is False and ok.blocking is False
    unscored = wo_like(passed=None, measured=None, wet_passed=None)
    assert unscored.wet_area_only_failure is False and unscored.blocking is False
    other = Check("scene_grid", False, 0.5, 1.0, "r")
    assert other.wet_area_only_failure is False and other.blocking is True


def test_agreement_failure_with_a_passing_clause_blocks() -> None:
    check = wo_like(passed=False, measured=0.90, wet_passed=True)
    assert check.wet_area_only_failure is False and check.blocking is True


def test_wet_only_failure_keeps_passed_false() -> None:
    assert wet_only().passed is False


def _markdown(tmp_path: Path, checks: list[Check]) -> str:
    _, md = write_report(
        checks,
        store=OutputStore(str(tmp_path / "out")),
        run_id="r1",
        docs_dir=tmp_path / "docs",
        generated_at=datetime(2026, 11, 6, tzinfo=UTC),
    )
    assert md is not None
    return md.read_text()


def _row_of(text: str, needle: str) -> str:
    return next(line for line in text.splitlines() if needle in line)


def test_markdown_marks_a_wet_only_failure_as_warn_with_the_gap(
    tmp_path: Path,
) -> None:
    text = _markdown(tmp_path, [wet_only()])
    assert "| check | passed | measured | threshold | reference | note |" in text
    row = _row_of(text, WO)
    assert "| warn |" in row
    assert "ramsar-12" in row and ITEM in row
    assert "+5.90 pp" in row and "limit 5.0 pp" in row


def test_markdown_negative_gap_is_signed(tmp_path: Path) -> None:
    check = wo_like(passed=False, measured=0.95, diff_pp=-5.99, wet_passed=False)
    assert "-5.99 pp" in _markdown(tmp_path, [check])


def test_markdown_agreement_failure_stays_no_with_an_empty_note(
    tmp_path: Path,
) -> None:
    row = _row_of(_markdown(tmp_path, [agreement_fail()]), WO)
    assert "| no |" in row and "warn" not in row
    assert row.endswith("|  |")


def test_json_counts_warned_and_keeps_the_failure(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "out"))
    write_report([passing(), wet_only()], store=store, run_id="r1", docs_dir=None)
    payload = json.loads(store.read_bytes("verification/r1.json"))
    assert payload["n_warned"] == 1
    assert payload["all_passed"] is False
    failed = payload["checks"][1]
    assert failed["passed"] is False
    assert failed["detail"]["wet_area_diff_pp"] == 5.90


def _live(checks: list[Check]) -> dict[str, Any]:
    return next(r for r in matrix_status(checks) if r["row"] == "Water extent, live")


def _end(checks: list[Check]) -> dict[str, Any]:
    return next(r for r in matrix_status(checks) if r["row"] == "End to end")


def test_matrix_wet_only_is_warn() -> None:
    checks = [wet_only()]
    row = _live(checks)
    assert (row["status"], row["n_fail"], row["n_warn"]) == ("warn", 0, 1)
    assert _end(checks)["status"] == "warn"


def test_matrix_wet_only_beside_a_pass_is_warn() -> None:
    checks = [passing(), wet_only()]
    row = _live(checks)
    assert (row["status"], row["n_pass"], row["n_fail"], row["n_warn"]) == (
        "warn",
        1,
        0,
        1,
    )
    assert _end(checks)["status"] == "warn"


def test_matrix_agreement_failure_is_fail() -> None:
    checks = [wet_only(), agreement_fail()]
    row = _live(checks)
    assert (row["status"], row["n_fail"], row["n_warn"]) == ("fail", 1, 1)
    assert _end(checks)["status"] == "fail"


def test_matrix_passes_stay_pass() -> None:
    checks = [passing(), passing()]
    assert _live(checks)["status"] == "pass"
    assert _live(checks)["n_warn"] == 0
    assert _end(checks)["status"] == "pass"


def test_matrix_counts_add_up_to_the_checks() -> None:
    checks = [passing(), wet_only(), agreement_fail()]
    row = _live(checks)
    total = (
        row["n_pass"]
        + row["n_fail"]
        + row["n_warn"]
        + row["n_skipped"]
        + row["n_errored"]
    )
    assert total == len(checks)


def test_matrix_markdown_has_an_n_warn_column(tmp_path: Path) -> None:
    text = _markdown(tmp_path, [wet_only()])
    assert "| row | status | pass | fail | warn | skipped | errored | note |" in text


# Pooled wet area check. Hand-computed: pipeline shares 0.60 and 0.40 with
# n 3000 and 1000 against WO shares 0.50 and 0.40.
# gap = 100 * (0.60*3000 + 0.40*1000 - 0.50*3000 - 0.40*1000) / 4000 = 7.5
# (pipeline share 0.55, WO share 0.475).
def test_pooled_gap_is_pixel_weighted_and_signed() -> None:
    a = wo_like(passed=True, measured=0.9, n=3000, pipeline=0.60, wo=0.50)
    b = wo_like(passed=True, measured=0.9, n=1000, pipeline=0.40, wo=0.40)
    pooled = pooled_wet_area_check([a, b])
    assert pooled is not None
    assert pooled.name == POOLED_WET_AREA_CHECK
    assert pooled.measured == pytest.approx(7.5)
    assert pooled.threshold == WET_AREA_MAX_PP
    assert pooled.passed is False
    assert pooled.reference == a.reference
    assert pooled.detail["n_checks"] == 2
    assert pooled.detail["n_mutually_clear"] == 4000
    assert pooled.detail["wet_area_pipeline"] == pytest.approx(0.55)
    assert pooled.detail["wet_area_wo"] == pytest.approx(0.475)
    assert pooled.detail["wet_area_max_pp"] == WET_AREA_MAX_PP
    assert "ADR 0008" in pooled.detail["rule"]


def test_pooled_gap_sign_is_negative_when_the_pipeline_is_drier() -> None:
    a = wo_like(passed=True, measured=0.9, n=1000, pipeline=0.40, wo=0.50)
    pooled = pooled_wet_area_check([a])
    assert pooled is not None and pooled.measured == pytest.approx(-10.0)
    assert pooled.passed is False


def test_pooled_just_over_the_limit_fails() -> None:
    check = wo_like(passed=True, measured=0.9, n=10000, pipeline=0.5501, wo=0.5)
    pooled = pooled_wet_area_check([check])
    assert pooled is not None
    assert pooled.measured == pytest.approx(5.01)
    assert pooled.passed is False


def test_pooled_exactly_five_passes() -> None:
    check = wo_like(passed=True, measured=0.9, n=1000, pipeline=0.55, wo=0.5)
    pooled = pooled_wet_area_check([check])
    assert pooled is not None
    assert pooled.measured == 5.0
    assert pooled.passed is True


def test_pooled_exactly_five_passes_with_integer_counts() -> None:
    # 62 and 56 wet of 120 is exactly 5.0 pp; float share * n would give
    # 5.000000000000005.
    check = wo_like(passed=True, measured=0.9, n=120, pipeline=62 / 120, wo=56 / 120)
    pooled = pooled_wet_area_check([check])
    assert pooled is not None
    assert pooled.measured == 5.0
    assert pooled.passed is True


def test_pooled_is_none_when_nothing_is_scored() -> None:
    assert pooled_wet_area_check([]) is None
    skipped = [
        wo_like(passed=None, measured=None, wet_passed=None),
        wo_like(passed=True, measured=0.9, n=0),
        wo_like(passed=True, measured=0.9, pipeline=None),
        wo_like(passed=True, measured=0.9, wo=None),
        Check("scene_grid", True, 1.0, 1.0, "r"),
        Check(WO, None, None, None, "r", {"error": "RuntimeError: down"}),
    ]
    assert pooled_wet_area_check(skipped) is None


def test_pooled_ignores_non_contributing_checks_beside_a_contributor() -> None:
    good = wo_like(passed=True, measured=0.9, n=1000, pipeline=0.6, wo=0.5)
    noise = [
        wo_like(passed=None, measured=None, wet_passed=None, pipeline=0.9, wo=0.1),
        wo_like(passed=True, measured=0.9, n=0, pipeline=0.9, wo=0.1),
    ]
    pooled = pooled_wet_area_check([*noise, good])
    assert pooled is not None
    assert pooled.detail["n_checks"] == 1
    assert pooled.measured == pytest.approx(10.0)


def _pooled(passed: bool) -> Check:
    return Check(
        POOLED_WET_AREA_CHECK,
        passed,
        2.5 if passed else 7.5,
        5.0,
        "https://example/wo.tif",
        {"n_checks": 3, "n_mutually_clear": 3000},
    )


def test_matrix_row_includes_the_pooled_check() -> None:
    row = _live([passing(), _pooled(True)])
    assert row["status"] == "pass" and row["n_pass"] == 2
    assert POOLED_WET_AREA_CHECK in row["check_names"]


def test_a_failed_pooled_check_blocks_the_row_and_end_to_end() -> None:
    checks = [passing(), wet_only(), _pooled(False)]
    row = _live(checks)
    assert (row["status"], row["n_fail"], row["n_warn"]) == ("fail", 1, 1)
    assert _end(checks)["status"] == "fail"
    assert _pooled(False).blocking is True


def test_pooled_note_in_markdown_reads_gap_and_count(tmp_path: Path) -> None:
    for passed, gap in ((True, "+2.50"), (False, "+7.50")):
        row = _row_of(_markdown(tmp_path, [_pooled(passed)]), POOLED_WET_AREA_CHECK)
        assert f"pooled wet area gap {gap} pp over 3 checks, limit 5.0 pp" in row
