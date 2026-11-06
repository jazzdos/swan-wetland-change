"""The verification matrix: every row of the design, scored from the checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from wetland_change.store import OutputStore
from wetland_change.verify.checks import Check, write_report
from wetland_change.verify.copernicus import CHECK_NAME as DISCOVERY
from wetland_change.verify.freshness import (
    CHECK_CDSE,
    CHECK_ES,
    CHECK_EXHAUSTED,
    CHECK_NEWEST,
)
from wetland_change.verify.matrix import MATRIX_ROWS, matrix_status
from wetland_change.verify.ndvi import CHECK_NAME as NDVI
from wetland_change.verify.ndvi import CORRELATION_CHECK_NAME as NDVI_CORRELATION
from wetland_change.verify.waterbodies import CHECK_NAME as WATERBODIES
from wetland_change.verify.waterbodies import SPEARMAN_CHECK_NAME as SPEARMAN

DESIGN_ROWS = [
    "Discovery finds every scene",
    "Reads the right bytes",
    "Reflectance scaling",
    "SCL read and alignment",
    "Index arithmetic",
    "Water extent, live",
    "Water extent, history",
    "NDVI",
    "GeoParquet output",
    "STAC catalogue",
    "Incremental and idempotent",
    "Change detection",
    "Scheduled job alive",
    "End to end",
]
STANDING = [
    "Index arithmetic",
    "GeoParquet output",
    "STAC catalogue",
    "Incremental and idempotent",
    "Change detection",
]
REPO = Path(__file__).parent.parent


def _ok(name: str) -> Check:
    return Check(name, True, 1.0, 1.0, "r")


def _bad(name: str) -> Check:
    return Check(name, False, 0.5, 1.0, "r")


def _reason(name: str) -> Check:
    return Check(name, None, None, None, "r", {"reason": "not on PC yet"})


def _error(name: str) -> Check:
    return Check(name, None, None, None, "r", {"error": "RuntimeError: down"})


def _row(checks: list[Check], row: str) -> dict[str, Any]:
    return next(r for r in matrix_status(checks) if r["row"] == row)


def test_rows_are_the_design_rows_in_order() -> None:
    assert [r["row"] for r in matrix_status([])] == DESIGN_ROWS
    assert [r.row for r in MATRIX_ROWS] == DESIGN_ROWS


def test_row_names_match_the_design_and_readme_tables() -> None:
    design = (REPO / "docs/plans/2026-10-29-swan-wetland-change-design.md").read_text()
    readme = (REPO / "README.md").read_text()
    for name in DESIGN_ROWS:
        assert f"| {name} |" in design
        assert f"| {name} |" in readme


def test_empty_run_is_all_not_run() -> None:
    rows = matrix_status([])
    assert {r["status"] for r in rows} == {"not-run"}
    for r in rows:
        assert (r["n_pass"], r["n_fail"], r["n_skipped"], r["n_errored"]) == (0,) * 4
        assert r["check_names"] == []


@pytest.mark.parametrize("row", STANDING)
def test_standing_rows_are_not_run_with_a_note(row: str) -> None:
    result = _row([_ok("reflectance_scaling")], row)
    assert result["status"] == "not-run"
    assert result["check_names"] == []
    assert result["note"]


def test_standing_row_notes_name_their_tests_and_scripts() -> None:
    assert "tests/test_indices.py" in _row([], "Index arithmetic")["note"]
    assert (
        "scripts/compare_dea_tools_indices.py" in _row([], "Index arithmetic")["note"]
    )
    assert "tests/test_geoparquet.py" in _row([], "GeoParquet output")["note"]
    assert "tests/test_catalogue.py" in _row([], "STAC catalogue")["note"]
    assert "tests/test_golden_run.py" in _row([], "Incremental and idempotent")["note"]
    assert "tests/test_change.py" in _row([], "Change detection")["note"]
    for row in STANDING:
        for token in _row([], row)["note"].replace(";", " ").split():
            path = token.strip("`.,")
            if path.startswith(("tests/", "scripts/")):
                assert (REPO / path).exists(), path


def test_scheduled_job_row_points_at_the_freshness_command() -> None:
    result = _row([_ok("reflectance_scaling")], "Scheduled job alive")
    assert result["status"] == "not-run"
    assert "wetland-change freshness" in result["note"]


@pytest.mark.parametrize(
    ("row", "names"),
    [
        ("Discovery finds every scene", [DISCOVERY]),
        ("Reads the right bytes", ["pixels_vs_planetary_computer", "scene_grid"]),
        ("Reflectance scaling", ["reflectance_scaling"]),
        ("SCL read and alignment", ["scl_share_water", "scl_shares"]),
        ("Water extent, live", ["water_vs_dea_s2_wo"]),
        ("Water extent, history", [WATERBODIES, SPEARMAN]),
        ("NDVI", [NDVI, NDVI_CORRELATION]),
        (
            "Scheduled job alive",
            [CHECK_NEWEST, CHECK_EXHAUSTED, CHECK_ES, CHECK_CDSE],
        ),
    ],
)
def test_check_names_map_to_their_row(row: str, names: list[str]) -> None:
    for name in names:
        result = _row([_ok(name)], row)
        assert result["status"] == "pass", name
        assert result["check_names"] == [name]
        assert result["n_pass"] == 1


def test_a_check_maps_to_one_row_only() -> None:
    rows = matrix_status([_ok("reflectance_scaling")])
    matched = [r["row"] for r in rows if r["check_names"]]
    assert matched == ["Reflectance scaling"]


def test_check_names_are_unique_and_sorted_in_first_seen_order() -> None:
    checks = [_ok("scl_share_water"), _ok("scl_share_veg"), _ok("scl_share_water")]
    result = _row(checks, "SCL read and alignment")
    assert result["check_names"] == ["scl_share_water", "scl_share_veg"]
    assert result["n_pass"] == 3


def test_fail_beats_everything() -> None:
    checks = [
        _ok("reflectance_scaling"),
        _bad("reflectance_scaling"),
        _error("reflectance_scaling"),
    ]
    result = _row(checks, "Reflectance scaling")
    assert result["status"] == "fail"
    assert (result["n_pass"], result["n_fail"], result["n_errored"]) == (1, 1, 1)


def test_pass_with_a_reason_only_skip_still_passes() -> None:
    checks = [_ok("reflectance_scaling"), _reason("reflectance_scaling")]
    result = _row(checks, "Reflectance scaling")
    assert result["status"] == "pass"
    assert (result["n_pass"], result["n_skipped"], result["n_errored"]) == (1, 1, 0)


def test_partially_errored_row_is_not_run() -> None:
    checks = [_ok("reflectance_scaling"), _error("reflectance_scaling")]
    result = _row(checks, "Reflectance scaling")
    assert result["status"] == "not-run"
    assert (result["n_pass"], result["n_errored"]) == (1, 1)


def test_errored_only_and_reason_only_rows_are_not_run() -> None:
    assert _row([_error("scl_shares")], "SCL read and alignment")["status"] == (
        "not-run"
    )
    result = _row([_reason(NDVI)], "NDVI")
    assert result["status"] == "not-run"
    assert result["n_skipped"] == 1


def test_end_to_end_passes_when_the_verdict_holds() -> None:
    checks = [_ok("reflectance_scaling"), _reason(NDVI)]
    assert _row(checks, "End to end")["status"] == "pass"


def test_end_to_end_fails_when_any_row_fails() -> None:
    checks = [_ok("reflectance_scaling"), _bad(NDVI)]
    assert _row(checks, "End to end")["status"] == "fail"


def test_end_to_end_is_not_run_with_an_errored_check_or_nothing_scored() -> None:
    assert (
        _row([_ok("reflectance_scaling"), _error(NDVI)], "End to end")["status"]
        == "not-run"
    )
    assert _row([_reason(NDVI)], "End to end")["status"] == "not-run"
    assert _row([], "End to end")["status"] == "not-run"


def test_end_to_end_counts_checks_that_map_to_no_row() -> None:
    result = _row([_ok("mystery")], "End to end")
    assert result["status"] == "pass"
    assert result["check_names"] == []


def test_matrix_is_in_the_json_and_markdown_reports(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "out"))
    json_path, md_path = write_report(
        [_ok("reflectance_scaling"), _error(NDVI)],
        store=store,
        run_id="r",
        docs_dir=tmp_path / "docs",
        generated_at=datetime(2026, 11, 5, tzinfo=UTC),
    )
    raw = store.read_bytes(json_path).decode()
    payload = json.loads(raw)
    assert [r["row"] for r in payload["matrix"]] == DESIGN_ROWS
    assert {r["status"] for r in payload["matrix"]} <= {
        "pass",
        "fail",
        "warn",
        "not-run",
    }
    assert payload["n_errored"] == 1
    assert md_path is not None
    text = md_path.read_text()
    assert "## Matrix" in text
    assert "| row | status | pass | fail | warn | skipped | errored | note |" in text
    for name in DESIGN_ROWS:
        assert f"| {name} |" in text
