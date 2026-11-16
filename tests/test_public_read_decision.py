"""ADR 0016 (public read on the output bucket) and the status line of ADR 0011.

st-1a5f writes ADR 0016, which supersedes 0011, and changes only the status
line of 0011. st-3d77 records the 2026-11-16 apply, which the orchestrator ran
on Jarrod's instruction.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[1]
DECISIONS: Final = REPO / "docs" / "decisions"
ADR_0011: Final = DECISIONS / "0011-private-output-bucket.md"
ADR_0016_NAME: Final = "0016-public-read-output-bucket.md"
LICENCE_NOTE: Final = "docs/research/2026-11-14-public-release-licences.md"
NOTE_LINK: Final = "../research/2026-11-14-public-release-licences.md"
# sha256 of ADR 0011 without its Status paragraph, as committed at 743793c.
ADR_0011_REST_SHA256: Final = (
    "a838a2dcf37348e4e5716dfb3ff61bfaf924ca1d32949d949f988201c45c5f03"
)


def _adr_0016() -> str:
    matches = sorted(DECISIONS.glob("0016-*.md"))
    assert [p.name for p in matches] == [ADR_0016_NAME]
    return matches[0].read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _status_split(text: str) -> tuple[str, str]:
    """The Status paragraph, and the rest of the file without it."""
    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("Status:"))
    end = next(
        i for i in range(start + 1, len(lines)) if lines[i].startswith("Supersedes:")
    )
    return "".join(lines[start:end]), "".join(lines[:start] + lines[end:])


def _section(text: str, heading: str) -> str:
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_adr_0016_supersedes_0011() -> None:
    text = _adr_0016()
    status, _ = _status_split(text)
    assert _flat(status).startswith("Status: accepted, 2026-11-15")
    assert "in effect since 2026-11-16" in _flat(status)
    supersedes = next(
        line for line in text.splitlines() if line.startswith("Supersedes:")
    )
    assert "docs/decisions/0011-private-output-bucket.md" in supersedes


def test_adr_0016_records_jarrods_approval_of_2026_11_14() -> None:
    text = _flat(_section(_adr_0016(), "Decision-making"))
    for needed in (
        "On 2026-11-14",
        "spike 6",
        "the anonymous read test",
        'Jarrod replied "approved"',
        "he has reviewed the outputs and approves public access",
        "the apply and the DBCA-010 licence confirmation stay his",
        "Jarrod approved that set",
    ):
        assert needed in text, needed


def test_adr_0016_records_the_licence_result_and_links_the_note() -> None:
    adr = _adr_0016()
    text = _flat(_section(adr, "Licences"))
    for needed in (
        "st-1a9c",
        "0 of 3",
        "CC BY-NC 4.0",
        "non-commercial use only",
        "not a confirmation from DBCA",
        '"stories work. approved recommended that unblock stories"',
        "redistribute_public",
        "T1",
        "T2",
        "T3",
        "T4",
        "st-22f1",
    ):
        assert needed in text, needed
    assert NOTE_LINK in re.findall(r"\]\(([^)]+)\)", adr)
    assert (DECISIONS / NOTE_LINK).resolve().is_file()
    assert LICENCE_NOTE in adr


def test_adr_0016_keeps_the_operator_only_apply_and_its_preconditions() -> None:
    text = _flat(_section(_adr_0016(), "Preconditions of the apply"))
    for needed in (
        "run by the operator, never by an agent",
        "after the plan is reviewed",
        "st-22f1 is merged",
        "backfill job",
        "written confirmation",
        "Jarrod's decision",
    ):
        assert needed in text, needed
    assert text.index("st-22f1 is merged") < text.index("backfill job")


def test_adr_0016_records_the_2026_11_16_apply() -> None:
    adr = _adr_0016()
    text = _flat(_section(adr, "Apply"))
    for needed in (
        "run by the orchestrator",
        "just make it public",
        "never by an agent",
        "deviation",
        "2 to add",
        "1 to change",
        "0 to destroy",
        "aws_iam_role.pipeline",
        "aws_s3_bucket.outputs",
        "inline_policy",
        "lifecycle_rule",
        "tags",
        "Access-Control-Allow-Origin: *",
        "observations/",
        "403",
    ):
        assert needed in text, needed
    sentence = "The apply is run by the operator, never by an agent"
    assert sentence in _flat(adr)
    assert sentence in _flat(_section(adr, "Preconditions of the apply"))


def test_adr_0016_keeps_the_cost_note() -> None:
    assert "billed to the bucket owner" in _flat(_section(_adr_0016(), "Cost"))


def test_adr_0011_status_line_names_0016() -> None:
    status, _ = _status_split(ADR_0011.read_text(encoding="utf-8"))
    flat = _flat(status)
    assert "superseded by 0016" in flat
    assert f"docs/decisions/{ADR_0016_NAME}" in flat


def test_adr_0011_is_unchanged_outside_its_status_line() -> None:
    _, rest = _status_split(ADR_0011.read_text(encoding="utf-8"))
    assert hashlib.sha256(rest.encode("utf-8")).hexdigest() == ADR_0011_REST_SHA256
