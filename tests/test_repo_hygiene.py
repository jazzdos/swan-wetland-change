"""Guards against source files that a fresh clone would not contain."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ["src", "tests", "scripts"]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_no_python_sources_are_gitignored() -> None:
    if shutil.which("git") is None or _git("rev-parse", "--git-dir").returncode:
        pytest.skip("not running inside a git checkout")
    listing = _git(
        "ls-files", "--others", "--ignored", "--exclude-standard", "--", *SOURCE_DIRS
    )
    assert listing.returncode == 0, listing.stderr
    ignored = [p for p in listing.stdout.splitlines() if p.endswith(".py")]
    assert ignored == []
