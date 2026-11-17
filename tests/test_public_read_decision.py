"""ADR 0017 (private output bucket again) and the status lines of ADRs 0016 and 0011.

ADR 0017 supersedes 0016 on Jarrod's 2026-11-17 direction and records that its
apply is pending. It changes only the status paragraph of 0016, as 0016 did to
0011.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[1]
DECISIONS: Final = REPO / "docs" / "decisions"
ADR_0011: Final = DECISIONS / "0011-private-output-bucket.md"
ADR_0016_NAME: Final = "0016-public-read-output-bucket.md"
ADR_0017_NAME: Final = "0017-private-output-bucket-again.md"
# sha256 of ADR 0011 without its Status paragraph, as committed at 743793c.
ADR_0011_REST_SHA256: Final = (
    "a838a2dcf37348e4e5716dfb3ff61bfaf924ca1d32949d949f988201c45c5f03"
)
# sha256 of ADR 0016 without its Status paragraph.
ADR_0016_REST_SHA256: Final = (
    "f927c6309f7782cb0b9d853206e5c3f1ec5d036e5d64b48960de2eea5eb4c3ed"
)
QUOTE: Final = (
    "just make it password protected so its not public - im not contacting dbca"
)


def _adr_0017() -> str:
    matches = sorted(DECISIONS.glob("0017-*.md"))
    assert [p.name for p in matches] == [ADR_0017_NAME]
    return matches[0].read_text(encoding="utf-8")


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


def test_adr_0017_supersedes_0016() -> None:
    text = _adr_0017()
    status, _ = _status_split(text)
    assert _flat(status).startswith("Status: accepted, 2026-11-17")
    supersedes = next(
        line for line in text.splitlines() if line.startswith("Supersedes:")
    )
    assert "docs/decisions/0016-public-read-output-bucket.md" in supersedes


def test_adr_0017_records_jarrods_direction_verbatim() -> None:
    text = _flat(_section(_adr_0017(), "Decision-making"))
    for needed in (QUOTE, "2026-11-17", "Jarrod"):
        assert needed in text, needed


def test_adr_0017_drops_the_dbca_confirmation() -> None:
    text = _flat(_section(_adr_0017(), "DBCA confirmation"))
    for needed in ("st-4c87", "no longer sought", "precondition 3"):
        assert needed in text, needed


def test_adr_0017_records_the_exposure_window() -> None:
    text = _flat(_section(_adr_0017(), "Exposure window"))
    for needed in ("anonymously readable by key", "2026-11-16", "cannot be withdrawn"):
        assert needed in text, needed


def test_adr_0017_states_the_effect_on_the_design() -> None:
    text = _flat(_section(_adr_0017(), "Effect on the design"))
    for needed in ("success criteria 2 and 3", "credentialed", "spike 6", "st-9f02"):
        assert needed in text, needed


def test_adr_0017_describes_reader_access() -> None:
    text = _flat(_section(_adr_0017(), "Reader access"))
    assert "credential_chain" in text
    assert "presigned" in text


def test_adr_0017_states_the_expected_plan() -> None:
    text = _flat(_section(_adr_0017(), "Expected plan"))
    for needed in (
        "0 to add",
        "1 to change",
        "2 to destroy",
        "aws_s3_bucket_public_access_block.outputs",
        "aws_s3_bucket_policy.public_read",
        "aws_s3_bucket_cors_configuration.outputs",
    ):
        assert needed in text, needed


def test_adr_0017_says_the_apply_is_pending() -> None:
    text = _flat(_section(_adr_0017(), "Apply")).lower()
    assert "pending" in text
    assert "apply complete" not in text
    assert "was run by" not in text


def test_adr_0016_status_names_0017() -> None:
    status, _ = _status_split(_adr_0016())
    flat = _flat(status)
    assert "superseded by 0017" in flat.lower()
    assert f"docs/decisions/{ADR_0017_NAME}" in flat


def test_adr_0016_is_unchanged_outside_its_status_paragraph() -> None:
    _, rest = _status_split(_adr_0016())
    assert hashlib.sha256(rest.encode("utf-8")).hexdigest() == ADR_0016_REST_SHA256


def test_adr_0011_status_line_names_0016() -> None:
    status, _ = _status_split(ADR_0011.read_text(encoding="utf-8"))
    flat = _flat(status)
    assert "superseded by 0016" in flat
    assert f"docs/decisions/{ADR_0016_NAME}" in flat


def test_adr_0011_is_unchanged_outside_its_status_line() -> None:
    _, rest = _status_split(ADR_0011.read_text(encoding="utf-8"))
    assert hashlib.sha256(rest.encode("utf-8")).hexdigest() == ADR_0011_REST_SHA256
