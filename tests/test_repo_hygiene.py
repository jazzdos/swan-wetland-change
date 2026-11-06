"""Guards against source files that a fresh clone would not contain."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ["src", "tests", "scripts", "docs/research"]
RESEARCH_DIR = REPO_ROOT / "docs" / "research"
# These two frozen records name scratch/ scripts because those scripts were
# untracked when the records were written.
FROZEN_SCRATCH_RECORDS = {
    "2026-11-04-milestone-2-review.md",
    "2026-11-06-reproducibility-audit.md",
}
SCRATCH_SCRIPT = re.compile(r"scratch/[\w./-]*\.(?:py|sh)")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def scratch_script_paths(text: str) -> set[str]:
    return set(SCRATCH_SCRIPT.findall(text))


def test_no_python_sources_are_gitignored() -> None:
    if shutil.which("git") is None or _git("rev-parse", "--git-dir").returncode:
        pytest.skip("not running inside a git checkout")
    listing = _git(
        "ls-files", "--others", "--ignored", "--exclude-standard", "--", *SOURCE_DIRS
    )
    assert listing.returncode == 0, listing.stderr
    ignored = [p for p in listing.stdout.splitlines() if p.endswith(".py")]
    assert ignored == []


def test_no_documented_scratch_script_is_gitignored() -> None:
    if shutil.which("git") is None or _git("rev-parse", "--git-dir").returncode:
        pytest.skip("not running inside a git checkout")
    docs = [REPO_ROOT / "LEARNINGS.md"]
    docs += [
        p
        for p in sorted(RESEARCH_DIR.glob("*.md"))
        if p.name not in FROZEN_SCRATCH_RECORDS
    ]
    offenders = []
    for doc in docs:
        for path in sorted(scratch_script_paths(doc.read_text(encoding="utf-8"))):
            if _git("check-ignore", "-q", path).returncode == 0:
                offenders.append(f"{doc.relative_to(REPO_ROOT)}: {path}")
    assert offenders == []


def test_scratch_script_paths_finds_scripts() -> None:
    text = "see scratch/spikes/x.py and scratch/a/b.sh, plus scratch/ and scratch/x.csv"
    assert scratch_script_paths(text) == {"scratch/spikes/x.py", "scratch/a/b.sh"}


def test_frozen_scratch_records_exist() -> None:
    for name in FROZEN_SCRATCH_RECORDS:
        assert (RESEARCH_DIR / name).is_file(), name
