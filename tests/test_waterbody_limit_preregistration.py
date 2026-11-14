"""The st-dd0d pre-registration in LEARNINGS.md fixes its decision rule.

Story st-dd0d decides whether the dea_waterbody layer gets a run-level live
water limit, from advisory summaries of scheduled runs that did not exist when
the rule was written. These tests pin the section's place and its fixed
parameters, so an edit that drops one fails. LEARNINGS.md is append only.
"""

import re
from pathlib import Path

LEARNINGS = Path(__file__).resolve().parents[1] / "LEARNINGS.md"
HEADING = "## Pre-registered hypotheses (st-dd0d, 2026-11-14)"
PREVIOUS = "## Pre-registered hypotheses (st-da75, 2026-11-14)"
NEXT = "## Spike results"

FIXED_PHRASES = (
    "2db25a1956062302b11522308ac571a3ea0061b2",
    "event `schedule`",
    "run attempt 1",
    "no scene acquired on 2026-10-29 or 2026-11-11",
    "Runs of `.github/workflows/verify.yml`",
    "at least 30 scored waterbody rows",
    "at least 8 runs on at least 6 distinct acquisition dates",
    "2027-01-31 23:59:59 UTC",
    "the floor to 0.01 of (A_min minus 0.02)",
    "computed exactly in decimal arithmetic",
    "D1, sample: at least 8 runs on at least 6 distinct acquisition dates",
    "5.00 pp or less",
    "L is at least 0.85",
    "W is at least 0.9",
    "`Waterbody layer water limit: advisory`",
    "docs/decisions/0015-waterbody-layer-live-water-limit.md",
    "not yet approved by Jarrod",
    "the run logs of sample pipeline and `verify.yml` runs",
    "`verification/` objects in the output store",
    "`git log -p`",
    "Outside the script, only commit metadata and `gh run list` JSON fields",
)


def _text() -> str:
    return LEARNINGS.read_text(encoding="utf-8")


def _section() -> str:
    text = _text()
    assert HEADING in text, f"LEARNINGS.md has no {HEADING!r} heading"
    start = text.index(HEADING)
    end = text.find("\n## ", start + len(HEADING))
    return text[start:] if end == -1 else text[start:end]


def test_section_is_recorded_once_between_st_da75_and_spike_results() -> None:
    text = _text()
    assert text.count(HEADING) == 1
    assert text.index(PREVIOUS) < text.index(HEADING) < text.index(NEXT)


def test_section_fixes_the_decision_parameters() -> None:
    section = _section()
    missing = [p for p in FIXED_PHRASES if p not in section]
    assert missing == []


def test_section_states_the_outcome_format_inline_only() -> None:
    # The outcome line belongs to the later Spike results entry and ADR 0015;
    # the pre-registration names its format inside a sentence.
    section = _section()
    assert re.search(r"^Waterbody layer water limit:", section, re.MULTILINE) is None
