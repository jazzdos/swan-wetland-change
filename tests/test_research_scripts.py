"""Tests that the dated research scripts under docs/research are rerunnable.

The scripts are loaded by path because their filenames start with digits. Nothing here
reads a raster or touches the network: only argument parsing, the pure CSV writer,
header text and the driver's default path are exercised.
"""

import ast
import csv
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
RESEARCH = REPO / "docs" / "research"

WATER = "2026-10-29-water-calibration"
POLYGON = "2026-10-29-polygon-calibration"
TOLERANCE = "2026-10-30-waterbodies-tolerance"
BACKFILL = "2026-10-29-backfill-count"
CALIBRATION = [WATER, POLYGON]
ALL_SCRIPTS = [WATER, POLYGON, TOLERANCE, BACKFILL]


def _load(stem: str) -> ModuleType:
    path = RESEARCH / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(
        f"research_{stem.replace('-', '_')}", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _docstring(stem: str) -> str:
    tree = ast.parse((RESEARCH / f"{stem}.py").read_text())
    doc = ast.get_docstring(tree)
    assert doc is not None, f"{stem}.py has no module docstring"
    return doc


@pytest.mark.parametrize("stem", CALIBRATION)
def test_calibration_parser_requires_window_and_out(stem: str, tmp_path: Path) -> None:
    parser = _load(stem).build_parser()
    out = str(tmp_path / "out.csv")
    for argv in (
        [],
        ["--start", "2026-08-01", "--end", "2026-10-29"],
        ["--start", "2026-08-01", "--out", out],
        ["--end", "2026-10-29", "--out", out],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)
    args = parser.parse_args(
        ["--start", "2026-08-01", "--end", "2026-10-29", "--out", out]
    )
    assert str(args.start) == "2026-08-01"
    assert str(args.end) == "2026-10-29"
    assert Path(args.out) == Path(out)


def test_polygon_parser_keeps_dry_run_flag(tmp_path: Path) -> None:
    parser = _load(POLYGON).build_parser()
    base = [
        "--start",
        "2026-08-01",
        "--end",
        "2026-10-29",
        "--out",
        str(tmp_path / "o.csv"),
    ]
    assert parser.parse_args(base).dry_run is False
    assert parser.parse_args([*base, "--dry-run"]).dry_run is True


@pytest.mark.parametrize("stem", CALIBRATION)
def test_calibration_source_has_no_rolling_window(stem: str) -> None:
    assert "timedelta(days=90)" not in (RESEARCH / f"{stem}.py").read_text()


def test_write_csv_records_sorted_item_ids_on_every_row_of_a_lake(
    tmp_path: Path,
) -> None:
    module: Any = _load(WATER)
    tally = {
        ("lake-a", "ndwi", -0.05): [90, 100],
        ("lake-a", "scl6", 0.0): [80, 100],
        ("lake-b", "ndwi", -0.05): [45, 50],
    }
    items_by_lake = {
        "lake-a": {"S2B_T50HLJ_20260920T021516_L2A", "S2A_T50HLJ_20260915T021516_L2A"},
        "lake-b": {"S2A_T50HLJ_20260915T021516_L2A"},
    }
    out = tmp_path / "nested" / "water.csv"
    module.write_csv(tally, items_by_lake, out)

    with out.open(newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][-2:] == ["n_scenes", "item_ids"]
    assert rows[0] == [
        "lake",
        "method",
        "threshold",
        "agreement",
        "n_pixels",
        "n_scenes",
        "item_ids",
    ]
    body = rows[1:]
    assert len(body) == 3
    lake_a_rows = [row for row in body if row[0] == "lake-a"]
    assert len(lake_a_rows) == 2
    for row in lake_a_rows:
        assert row[5] == "2"
        assert row[6] == "S2A_T50HLJ_20260915T021516_L2A;S2B_T50HLJ_20260920T021516_L2A"
    lake_b_row = next(row for row in body if row[0] == "lake-b")
    assert lake_b_row[5] == "1"
    assert lake_b_row[6] == "S2A_T50HLJ_20260915T021516_L2A"
    assert lake_b_row[3] == "0.9000"


@pytest.mark.parametrize("stem", ALL_SCRIPTS)
def test_header_names_committed_csv_and_warns_of_drift(stem: str) -> None:
    doc = _docstring(stem)
    assert f"{stem}.csv" in doc
    assert (RESEARCH / f"{stem}.csv").exists()
    assert "may have changed" in doc
    assert "scratch/" not in doc


@pytest.mark.parametrize("stem", CALIBRATION)
def test_calibration_header_states_provisional_window_passed(stem: str) -> None:
    doc = _docstring(stem)
    assert "ga_s2_wo_provisional_3" in doc
    assert "provisional" in doc


def test_water_header_states_csv_predates_new_columns() -> None:
    doc = _docstring(WATER)
    assert "n_scenes" in doc
    assert "item_ids" in doc
    assert "predates" in doc


def test_tolerance_header_names_extra_csv_and_option() -> None:
    doc = _docstring(TOLERANCE)
    extra = "2026-10-30-waterbodies-tolerance-extra.csv"
    assert extra in doc
    assert (RESEARCH / extra).exists()
    source = (RESEARCH / f"{TOLERANCE}.py").read_text()
    assert "--extra-out" in source
    assert "scratch/" not in source


def test_spearman_windows_header_states_frozen_commit() -> None:
    doc = _docstring("2026-11-05-spearman-windows")
    assert "46e0e20" in doc
    assert "_history_paths" in doc
    assert "2026-11-05-spearman-windows.csv" in doc


def _wt_line() -> str:
    lines = (RESEARCH / "2026-11-02-backfill-driver.sh").read_text().splitlines()
    return next(line for line in lines if line.startswith("WT="))


def test_driver_wt_default_is_repository_root(tmp_path: Path) -> None:
    line = _wt_line()
    assert "st-b983" not in line
    assert ".worktrees" not in line
    probe_dir = tmp_path / "docs" / "research"
    probe_dir.mkdir(parents=True)
    probe = probe_dir / "probe.sh"
    probe.write_text(f'#!/bin/bash\n{line}\necho "$WT"\n')
    done = subprocess.run(
        ["bash", str(probe)],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin"},
        cwd=tmp_path,
    )
    assert done.stdout.strip() == str(tmp_path.resolve())


def test_driver_stub_test_always_sets_wt() -> None:
    text = (RESEARCH / "2026-11-02-backfill-driver-test.sh").read_text()
    assert 'env WT="$T/t$n/wt"' in text
    assert 'env WT="$T/t6/wt"' in text


def test_backfill_evidence_note_lists_the_differences() -> None:
    note = RESEARCH / "2026-11-03-backfill-evidence-frozen.md"
    assert note.exists()
    text = note.read_text()
    assert "114459b" in text
    assert "9ce8408c" in text
    assert "scratch/" not in text
    for field in (
        "h4.lakes[*].passed",
        "n_pairs",
        "n_unpaired",
        "per_pass",
        "rho",
        "00e8fb0",
        "runs.backfill_calls",
        "runs.backfill_seconds_sum",
        "runs.seconds_per_processed_scene",
        "--progress-log",
        "config_sha256",
        "git_head",
        "date",
        "reference.searched_at",
        "spearman_min",
    ):
        assert field in text, field
