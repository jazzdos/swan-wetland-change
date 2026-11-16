"""st-22f1 acceptance criterion: no live file states DBCA-010 is CC BY-SA 4.0.

The criterion reads "No file outside docs/decisions and the dated docs/research
notes states that DBCA-010 is CC BY-SA 4.0". The check is stricter than the
criterion: every git-listed live file, minus history (.git/, .venv/, stories/,
.agents/, docs/decisions/, docs/research/, docs/handoffs/, docs/plans/*milestone*)
and this file, holds no by-sa or share-alike text at all except eight allowlisted
occurrences that state no DBCA-010 licence.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve().relative_to(REPO).as_posix()
DASHES = "\\-_\u2010-\u2015\u2212"
NEEDLE = re.compile(
    rf"by[\s{DASHES}]+sa(?![a-z])|share[\s{DASHES}]*alike", re.IGNORECASE
)
EXCLUDED_PREFIXES = (
    ".git/",
    ".venv/",
    "stories/",
    ".agents/",
    "docs/decisions/",
    "docs/research/",
    "docs/handoffs/",
)
MILESTONE = re.compile(r"docs/plans/[^/]*milestone[^/]*")
DESIGN = "docs/plans/2026-10-29-swan-wetland-change-design.md"
AMENDMENT = (
    "(amended 2026-11-15, st-22f1: "
    "see docs/research/2026-11-14-public-release-licences.md)"
)
ALLOWED: dict[str, tuple[str, ...]] = {
    "tests/test_public_release_licences.py": (
        'SHAREALIKE: Final = "CC BY-SA 4.0 ShareAlike"',
        'if "BY-SA" not in licence:',
        "    SHAREALIKE,",
        "{row[SHAREALIKE] for row in published_rows()}",
    ),
    "tests/test_catalogue.py": ('for banned in ("SA-4.0", "SA 4.0", "ShareAlike"):',),
    "tests/test_dbca_attribution.py": (
        '"forbidden", [chr(0x2014), "ShareAlike", "SA 4.0", "SA-4.0"], ids=repr',
        "def test_dbca_attribution_has_no_em_dash_or_sharealike_wording(",
    ),
    DESIGN: ("(CC BY-NC on data.wa.gov.au, CC BY-SA on data.gov.au)",),
}


def is_scanned(path: str) -> bool:
    if path.startswith(EXCLUDED_PREFIXES):
        return False
    return not (MILESTONE.fullmatch(path) or path == SELF)


def live_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=REPO,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("git is not installed")
    if result.returncode != 0:
        pytest.skip("not running inside a git checkout")
    names = [name for name in result.stdout.decode("utf-8").split("\0") if name]
    return [name for name in names if is_scanned(name) and (REPO / name).is_file()]


def test_scan_filter_excludes_history_and_keeps_live_files() -> None:
    for path in (
        "docs/research/verification-20261029T131944Z.md",
        "docs/research/2026-11-14-public-release-licences.md",
        "docs/decisions/0011-private-output-bucket.md",
        "docs/handoffs/2026-11-06-milestone-2.md",
        "docs/plans/2026-10-29-swan-wetland-change-milestone-1.md",
        "stories/st-22f1.md",
        ".agents/x.json",
        SELF,
    ):
        assert not is_scanned(path), path
    for path in (
        "README.md",
        "AGENTS.md",
        DESIGN,
        "src/wetland_change/stac/catalogue.py",
        "scripts/fetch_aoi.py",
        "tests/test_catalogue.py",
    ):
        assert is_scanned(path), path


def test_no_live_file_names_the_sharealike_licence() -> None:
    files = live_files()
    for path in ALLOWED:
        assert path in files, path
    hits: list[str] = []
    for path in files:
        data = (REPO / path).read_bytes()
        if b"\x00" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        for snippet in ALLOWED.get(path, ()):
            assert text.count(snippet) == 1, (path, snippet)
            text = text.replace(snippet, "")
        for number, line in enumerate(text.splitlines(), start=1):
            if NEEDLE.search(line):
                hits.append(f"{path}:{number}")
    assert not hits, hits


def test_design_carries_the_amendment_note_three_times() -> None:
    text = (REPO / DESIGN).read_text(encoding="utf-8")
    assert text.count(AMENDMENT) == 3
    assert "CC BY-NC 4.0" in text


@pytest.mark.parametrize(
    "line",
    [
        "CC BY-SA 4.0",
        "cc_by_sa",
        "CC BY SA 4.0",
        "CC BY‐SA 4.0",
        "CC BY‑SA 4.0",
        "CC BY–SA 4.0",
        "CC BY−SA 4.0",
        "Attribution-ShareAlike 4.0",
        "Attribution‑ShareAlike 4.0",
        "share alike terms",
        "SHARE-ALIKE",
    ],
)
def test_needle_matches_sharealike_variants(line: str) -> None:
    assert NEEDLE.search(line), line


@pytest.mark.parametrize(
    "line",
    ["stored by same polygon", "Dubai SA office", "bypass a gate", "CC BY-NC 4.0"],
)
def test_needle_ignores_unrelated_text(line: str) -> None:
    assert not NEEDLE.search(line), line
