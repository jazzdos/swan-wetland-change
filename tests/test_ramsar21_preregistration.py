"""The st-b6bf pre-registration in LEARNINGS.md fixes its decision rule.

Story st-b6bf decides whether ramsar-21 gets a per-polygon water override
under ADR 0005, from ramsar-21 passes acquired after the rule was written.
These tests pin the section's place and its fixed parameters, so an edit that
drops one fails, and check that config/pipeline.toml holds no ramsar-21
override before ADR 0014 records the outcome. LEARNINGS.md is append only.
"""

import re
from pathlib import Path

import pytest

from wetland_change.config import load_config

REPO = Path(__file__).resolve().parents[1]
LEARNINGS = REPO / "LEARNINGS.md"
CONFIG = REPO / "config" / "pipeline.toml"
ADR_0014 = REPO / "docs" / "decisions" / "0014-ramsar-21-water-setting.md"
HEADING = "## Pre-registered hypotheses (st-b6bf, 2026-11-14)"
PREVIOUS = "## Pre-registered hypotheses (st-dd0d, 2026-11-14)"
NEXT = "## Spike results"

SEEN_ITEMS = (
    "S2B_T50HLJ_20260912T022111_L2A",
    "S2C_T50HLJ_20260917T022244_L2A",
    "S2B_T50HLJ_20261002T021907_L2A",
    "S2B_T50HLJ_20261012T021555_L2A",
    "S2C_T50HLJ_20261027T022351_L2A",
    "S2A_T50HLJ_20261029T021516_L2A",
    "S2B_T50HLJ_20261111T022009_L2A",
)

FIXED_PHRASES = (
    "2026-11-12T00:00:00Z to 2026-12-31T23:59:59Z",
    "cloud cover below `cloud_cover_max` 20.0 as `discover` applies it",
    "at least 6 rows on at least 3 distinct dates",
    "MNDWI above t for t in {-0.05, 0.00, +0.05, +0.10, +0.15, +0.20}",
    "scl6 is reported for context only",
    "lowest mean absolute gap_pp",
    "Ties go to the lower threshold",
    "Baseline: the global -0.10",
    "n is at least 100",
    "at most twice in total",
    "no earlier than the second UTC day after the closing date",
    "It computes no index, wet share, agreement or gap for a confirmatory item",
    "A reproduction gate failure is not such a stop",
    "R3, gain:",
    "R4, consistency:",
    "R5, no over-correction:",
    "R6, floor:",
    "within 0.01 pp",
    "R1, sample: at least 6 confirmatory rows",
    "on at least 3 distinct acquisition dates",
    "R2, clause: the absolute gap_pp at T is 5.0 or less on every confirmatory row",
    "is at least 0.005",
    "on at least two thirds of the confirmatory rows",
    "over the confirmatory rows is 2.0 or less",
    "the floor to 0.01 of (pooled agreement at T",
    "computed exactly with rational arithmetic",
    "agreement_min is at least 0.91",
    "`[water.overrides.ramsar-21]`",
    "`ramsar-21 water setting: keep-global`",
    "docs/research/2026-11-12-ramsar-21-confirm.py",
    "docs/decisions/0014-ramsar-21-water-setting.md",
    "not yet approved by Jarrod",
    "under Jarrod's request to complete the outstanding work",
    "The question labelled no recommendation",
    "'push & approved recommended'",
    "the orchestrator took option (b)",
    "9b53bbd3a877fc721610b7ca5f25dcadfe431a9db0db58223da583da213ba26a",
    "`verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`",
    "no run log of a `pipeline` or `verify.yml` run newer than 43475454140",
    "`git log -p`",
    "No limit is loosened without the confirmatory sample",
)

OUTCOME_PREFIXES = (
    "ramsar-21 water setting:",
    "ramsar-21 override:",
    "Failed rules:",
    "Outcome:",
)


def _text() -> str:
    return LEARNINGS.read_text(encoding="utf-8")


def _section() -> str:
    text = _text()
    assert HEADING in text, f"LEARNINGS.md has no {HEADING!r} heading"
    start = text.index(HEADING)
    end = text.find("\n## ", start + len(HEADING))
    return text[start:] if end == -1 else text[start:end]


def _paragraph(section: str, opening: str) -> str:
    start = section.index(opening)
    end = section.find("\n\n", start)
    return section[start:] if end == -1 else section[start:end]


def test_section_is_recorded_once_between_st_dd0d_and_spike_results() -> None:
    text = _text()
    assert text.count(HEADING) == 1
    assert text.index(PREVIOUS) < text.index(HEADING) < text.index(NEXT)


def test_section_fixes_the_decision_parameters() -> None:
    section = _section()
    missing = [p for p in FIXED_PHRASES if p not in section]
    assert missing == []


def test_section_names_the_seen_scene_tiles() -> None:
    seen = _paragraph(_section(), "Seen rows.")
    ids = re.findall(r"S2[ABC]_T50[A-Z]{3}_\d{8}T\d{6}_L2A", seen)
    assert tuple(ids) == SEEN_ITEMS


def test_section_does_not_say_jarrod_approved_the_terms() -> None:
    # Option (b) was the orchestrator's recommendation, taken as approved
    # under Jarrod's reply; the question labelled no recommendation.
    section = _section()
    assert "Jarrod approved" not in section
    assert "approved by Jarrod on" not in section


def test_section_states_the_outcome_format_inline_only() -> None:
    # The outcome lines belong to the later Spike results entry and ADR 0014,
    # and tests/test_config.py reads the first '^Outcome: ...$' line in the file.
    section = _section()
    for prefix in OUTCOME_PREFIXES:
        pattern = rf"^{re.escape(prefix)}"
        assert re.search(pattern, section, re.MULTILINE) is None, prefix


def test_no_ramsar_21_override_before_adr_0014() -> None:
    if ADR_0014.exists():
        pytest.skip("ADR 0014 records the outcome; tests/test_config.py owns it")
    assert "ramsar-21" not in load_config(CONFIG).water.overrides
