"""Tests for the ramsar-12 confirmatory script (st-2a78).

The script is a dated research file, so it is loaded by path. Every row here is
synthetic: no raster is read and nothing touches the network.
"""

import builtins
import importlib.util
import re
import socket
import sys
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "docs" / "research" / "2026-11-06-ramsar-12-confirm.py"
SEEN_CSV = REPO / "docs" / "research" / "2026-11-06-ramsar-12-gap.csv"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ramsar12_confirm", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ramsar12_confirm"] = module
    spec.loader.exec_module(module)
    return module


confirm = _load()

Counts = dict[Any, tuple[int, int]]

# (a, b) per setting on one scene-tile of 1000 mutually clear pixels. The global
# setting is 6 pp too wet, +0.05 is nearly even, 0.00 and +0.10 are worse.
GOOD: Counts = {
    -0.10: (60, 0),
    0.0: (30, 0),
    0.05: (10, 5),
    0.10: (0, 40),
    "scl6": (20, 0),
}
SEEN_DATES = ("2026-09-12", "2026-10-02")
CONFIRM_SLOTS = (
    ("2026-08-23", "50HLK"),
    ("2026-08-28", "50HLJ"),
    ("2026-08-28", "50HLK"),
    ("2026-08-30", "50HLK"),
    ("2026-09-07", "50HLJ"),
    ("2026-09-07", "50HLK"),
)


def _scene(
    pass_date: str, tile: str, counts: Counts, pixels: int = 1000
) -> list[dict[str, Any]]:
    rows = []
    for key, (pipeline_only, wo_only) in counts.items():
        rows.append(
            {
                "item_id": f"S2_{pass_date}_{tile}",
                "pass_date": pass_date,
                "tile": tile,
                "method": "scl6" if key == "scl6" else "mndwi",
                "threshold": None if key == "scl6" else key,
                "n_mutually_clear": pixels,
                "a_pipeline_only": pipeline_only,
                "b_wo_only": wo_only,
                "gap_pp": 100 * (pipeline_only - wo_only) / pixels,
                "agreement": 1 - (pipeline_only + wo_only) / pixels,
            }
        )
    return rows


def _sample(
    per_row: list[Counts] | None = None,
    slots: tuple[tuple[str, str], ...] = CONFIRM_SLOTS,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (pass_date, tile) in enumerate(slots):
        counts = per_row[index] if per_row is not None else GOOD
        rows.extend(_scene(pass_date, tile, counts))
    return rows


def _seen(counts: Counts | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pass_date in SEEN_DATES:
        rows.extend(_scene(pass_date, "50HLJ", counts or GOOD))
    return rows


def _with(base: Counts, updates: Counts) -> Counts:
    return {**base, **updates}


# -- selection ---------------------------------------------------------------


def test_select_threshold_picks_the_lowest_mean_abs_gap() -> None:
    assert confirm.select_threshold(_sample()) == 0.05
    low_zero = _with(GOOD, {0.0: (2, 0), 0.05: (30, 0)})
    assert confirm.select_threshold(_sample([low_zero] * 6)) == 0.0
    low_high = _with(GOOD, {0.0: (30, 0), 0.05: (30, 0), 0.10: (3, 0)})
    assert confirm.select_threshold(_sample([low_high] * 6)) == 0.10


def test_select_threshold_tie_prefers_nominee_then_lower() -> None:
    nominee_tie = _with(GOOD, {0.0: (10, 0), 0.05: (0, 10), 0.10: (30, 0)})
    assert confirm.select_threshold(_sample([nominee_tie] * 6)) == 0.05
    outer_tie = _with(GOOD, {0.0: (10, 0), 0.05: (30, 0), 0.10: (0, 10)})
    assert confirm.select_threshold(_sample([outer_tie] * 6)) == 0.0


# -- agreement floor ---------------------------------------------------------


@pytest.mark.parametrize(
    ("disagreeing", "pixels", "expected"),
    [
        (368, 10000, Fraction(94, 100)),
        (400, 10000, Fraction(94, 100)),
        (401, 10000, Fraction(93, 100)),
        (699, 10000, Fraction(91, 100)),
        (700, 10000, Fraction(91, 100)),
        (701, 10000, Fraction(90, 100)),
    ],
)
def test_agreement_floor_is_exact_at_the_hundredth_boundary(
    disagreeing: int, pixels: int, expected: Fraction
) -> None:
    assert confirm.agreement_floor(disagreeing, pixels) == expected


# -- loading and writing -----------------------------------------------------


def test_load_rows_reads_the_seen_csv() -> None:
    rows = confirm.load_rows(SEEN_CSV)
    assert len(confirm.seen_dates(rows)) == 6
    assert "2026-09-12" in confirm.seen_dates(rows)
    for threshold in (0.0, 0.05, 0.10):
        at_threshold = [
            row
            for row in rows
            if row["method"] == "mndwi"
            and row["threshold"] is not None
            and round(row["threshold"], 2) == threshold
        ]
        assert len(at_threshold) == 12
    assert all("csv_n" not in row and "csv_gap_pp" not in row for row in rows)
    scl6 = [row for row in rows if row["method"] == "scl6"]
    assert len(scl6) == 12 and all(row["threshold"] is None for row in scl6)
    assert isinstance(rows[0]["n_mutually_clear"], int)
    assert isinstance(rows[0]["gap_pp"], float)


def test_write_rows_round_trips_in_sorted_order(tmp_path: Path) -> None:
    rows = _sample()
    path = tmp_path / "out.csv"
    confirm.write_rows(list(reversed(rows)), path)
    raw = path.read_bytes().decode()
    assert "\r" not in raw
    assert raw.splitlines()[0] == (
        "item_id,pass_date,tile,method,threshold,n_mutually_clear,"
        "a_pipeline_only,b_wo_only,gap_pp,agreement"
    )
    loaded = confirm.load_rows(path)
    assert len(loaded) == len(rows)
    keys = [(row["pass_date"], row["tile"]) for row in loaded]
    assert keys == sorted(keys)
    first = [row for row in loaded if row["item_id"] == rows[0]["item_id"]]
    assert [row["threshold"] for row in first] == [-0.1, 0.0, 0.05, 0.1, None]
    assert [row["method"] for row in first] == ["mndwi"] * 4 + ["scl6"]
    by_key = {(r["item_id"], r["method"], r["threshold"]): r for r in rows}
    for row in loaded:
        assert row == by_key[(row["item_id"], row["method"], row["threshold"])]


# -- decision ----------------------------------------------------------------


def test_decide_overrides_when_every_condition_holds() -> None:
    decision = confirm.decide(_sample(), _seen())
    assert decision.outcome == "override"
    assert decision.threshold == 0.05
    assert decision.failed == ()
    assert not decision.inconclusive
    # 6 confirmatory and 2 seen rows at 15 of 1000 disagree: 1 - 0.015 - 0.02.
    assert decision.agreement_min == 0.96


def test_decide_fails_r2_alone_for_a_row_over_the_limit() -> None:
    wide = _with(GOOD, {0.05: (55, 0)})
    decision = confirm.decide(_sample([wide] + [GOOD] * 5), _seen())
    assert decision.outcome == "keep-global"
    assert decision.failed == ("R2",)
    assert not decision.inconclusive


def test_decide_fails_r3_alone_when_the_pooled_gain_is_small() -> None:
    small_win = _with(GOOD, {-0.10: (11, 5), 0.05: (10, 5)})
    small_loss = _with(GOOD, {-0.10: (11, 5), 0.05: (12, 5)})
    decision = confirm.decide(_sample([small_win] * 4 + [small_loss] * 2), _seen())
    assert decision.outcome == "keep-global"
    assert decision.failed == ("R3",)


def test_decide_fails_r4_alone_when_too_few_rows_improve() -> None:
    loss = _with(GOOD, {-0.10: (5, 0), 0.05: (10, 5)})
    decision = confirm.decide(_sample([GOOD] * 3 + [loss] * 3), _seen())
    assert decision.outcome == "keep-global"
    assert decision.failed == ("R4",)


def test_decide_passes_r4_at_exactly_two_thirds() -> None:
    loss = _with(GOOD, {-0.10: (5, 0), 0.05: (10, 5)})
    decision = confirm.decide(_sample([GOOD] * 4 + [loss] * 2), _seen())
    assert "R4" not in decision.failed


def test_decide_fails_r5_alone_when_the_mean_gap_is_over_corrected() -> None:
    over = _with(GOOD, {-0.10: (100, 0), 0.0: (45, 0), 0.05: (40, 0), 0.10: (50, 0)})
    decision = confirm.decide(_sample([over] * 6), _seen())
    assert decision.outcome == "keep-global"
    assert decision.failed == ("R5",)


def test_decide_fails_r6_alone_when_the_floor_is_below_the_minimum() -> None:
    noisy = _with(
        GOOD, {-0.10: (150, 0), 0.0: (100, 0), 0.05: (40, 40), 0.10: (0, 200)}
    )
    decision = confirm.decide(_sample([noisy] * 6), _seen(noisy))
    assert decision.outcome == "keep-global"
    assert decision.failed == ("R6",)
    assert not decision.inconclusive


def test_decide_reports_every_failed_condition() -> None:
    bad = _with(GOOD, {-0.10: (5, 0), 0.0: (80, 0), 0.05: (60, 0), 0.10: (0, 90)})
    decision = confirm.decide(_sample([bad] * 6), _seen())
    assert decision.outcome == "keep-global"
    assert decision.failed == ("R2", "R3", "R4", "R5")


def test_decide_is_inconclusive_with_five_rows() -> None:
    decision = confirm.decide(_sample(slots=CONFIRM_SLOTS[:5]), _seen())
    assert decision.outcome == "keep-global"
    assert decision.inconclusive
    assert decision.failed == ("R1",)


def test_decide_is_inconclusive_with_six_rows_on_two_dates() -> None:
    slots = tuple(
        (pass_date, tile)
        for pass_date in ("2026-08-28", "2026-09-07")
        for tile in ("50HLJ", "50HLK", "50HMJ")
    )
    decision = confirm.decide(_sample(slots=slots), _seen())
    assert decision.outcome == "keep-global"
    assert decision.inconclusive
    assert decision.failed == ("R1",)


def test_decide_raises_when_an_item_lacks_the_global_row() -> None:
    rows = [
        row
        for row in _sample()
        if not (row["item_id"] == "S2_2026-08-23_50HLK" and row["threshold"] == -0.10)
    ]
    with pytest.raises(ValueError, match="S2_2026-08-23_50HLK"):
        confirm.decide(rows, _seen())


def test_decide_raises_for_a_confirmatory_row_on_a_seen_date() -> None:
    slots = (("2026-09-12", "50HLK"),) + CONFIRM_SLOTS[1:]
    with pytest.raises(ValueError, match="seen"):
        confirm.decide(_sample(slots=slots), _seen())


def test_decide_compares_thresholds_with_a_tolerance() -> None:
    rows = _sample()
    for row in rows:
        if row["threshold"] == 0.05:
            row["threshold"] = 0.05000000000000001
    assert confirm.decide(rows, _seen()).outcome == "override"


# -- report ------------------------------------------------------------------


def test_build_report_ends_with_the_override_lines() -> None:
    confirmatory = _sample()
    seen = _seen()
    decision = confirm.decide(confirmatory, seen)
    text = confirm.build_report(
        confirmatory, seen, decision, [("S2_dropped", "no DEA WO item")]
    )
    assert re.search(r"^Chosen outcome: override$", text, re.MULTILINE)
    assert re.search(r"^threshold = 0\.05$", text, re.MULTILINE)
    assert re.search(r"^agreement_min = 0\.96$", text, re.MULTILINE)
    assert text.rstrip().splitlines()[-3:] == [
        "Chosen outcome: override",
        "threshold = 0.05",
        "agreement_min = 0.96",
    ]
    assert "S2_dropped" in text and "no DEA WO item" in text
    for condition in ("R1", "R2", "R3", "R4", "R5", "R6"):
        assert re.search(rf"^{condition}\b", text, re.MULTILINE)


def test_build_report_ends_with_the_keep_global_lines() -> None:
    wide = _with(GOOD, {0.05: (55, 0)})
    confirmatory = _sample([wide] + [GOOD] * 5)
    seen = _seen()
    decision = confirm.decide(confirmatory, seen)
    text = confirm.build_report(confirmatory, seen, decision, [])
    assert text.rstrip().splitlines()[-3:] == [
        "Chosen outcome: keep-global",
        "Failed: R2",
        "Inconclusive: no",
    ]


def test_build_report_marks_an_inconclusive_sample() -> None:
    confirmatory = _sample(slots=CONFIRM_SLOTS[:5])
    seen = _seen()
    decision = confirm.decide(confirmatory, seen)
    text = confirm.build_report(confirmatory, seen, decision, [])
    assert text.rstrip().splitlines()[-3:] == [
        "Chosen outcome: keep-global",
        "Failed: R1",
        "Inconclusive: yes",
    ]


# -- import hygiene ----------------------------------------------------------


def test_importing_the_script_does_no_network_or_file_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("I/O at import time")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(Path, "open", refuse)
    monkeypatch.setattr(Path, "read_text", refuse)
    monkeypatch.setattr(Path, "read_bytes", refuse)
    spec = importlib.util.spec_from_file_location("ramsar12_import_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ramsar12_import_check"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("ramsar12_import_check", None)
    assert module.NOMINEE == 0.05
    assert module.SEEN_CSV.name == "2026-11-06-ramsar-12-gap.csv"
