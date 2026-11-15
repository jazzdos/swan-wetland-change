"""data/SOURCES.md must name every host the code reads and every fixture file."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
SOURCES_PATH: Final = REPO_ROOT / "data" / "SOURCES.md"
FIXTURE_DIRS: Final = (
    REPO_ROOT / "tests" / "fixtures" / "thomsons_20261027",
    REPO_ROOT / "tests" / "fixtures" / "aoi",
    REPO_ROOT / "tests" / "fixtures" / "footprint_edge_50hmk_20261014",
)

_PROVIDER_LINK: Final = (
    "provider homepage link in STAC catalogue metadata, no data read"
)

_ATTRIBUTION_LINK: Final = (
    "licence or attribution link carried in published metadata (st-8856), no data read"
)

NOT_A_DATASET: Final[dict[str, str]] = {
    "example.invalid": "reserved placeholder base URL, never resolved",
    "bucket": "placeholder bucket name in the store.py docstring",
    "www.element84.com": _PROVIDER_LINK,
    "www.esa.int": _PROVIDER_LINK,
    "www.dbca.wa.gov.au": _PROVIDER_LINK,
    "www.dea.ga.gov.au": _PROVIDER_LINK,
    "creativecommons.org": _ATTRIBUTION_LINK,
    "knowledge.dea.ga.gov.au": _ATTRIBUTION_LINK,
    "dx.doi.org": _ATTRIBUTION_LINK,
    "doi.org": _ATTRIBUTION_LINK,
    "files.pythonhosted.org": (
        "dea-tools wheel pinned by sha256 in scripts/compare_dea_tools_indices.py, "
        "a tool not a dataset"
    ),
}

HOST_PATTERN: Final = re.compile(r"(?:https?|s3)://([A-Za-z0-9][A-Za-z0-9.-]*)")


def unlisted_hosts(sources_text: str, files: dict[Path, str]) -> dict[str, Path]:
    """Return host -> first file naming it, for hosts absent from SOURCES table rows."""
    haystack = "\n".join(
        line for line in sources_text.splitlines() if line.startswith("|")
    ).lower()
    missing: dict[str, Path] = {}
    for path, text in files.items():
        for match in HOST_PATTERN.finditer(text):
            host = match.group(1).lower().rstrip(".")
            if host in NOT_A_DATASET or host in missing:
                continue
            if host not in haystack:
                missing[host] = path
    return missing


def fixture_files() -> list[Path]:
    return [
        path
        for root in FIXTURE_DIRS
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.startswith(".")
    ]


def test_every_host_in_src_and_scripts_is_in_sources() -> None:
    sources_text = SOURCES_PATH.read_text(encoding="utf-8")
    files = {
        path: path.read_text(encoding="utf-8")
        for root in (REPO_ROOT / "src", REPO_ROOT / "scripts")
        for path in sorted(root.rglob("*.py"))
    }
    missing = unlisted_hosts(sources_text, files)
    assert not missing, "hosts missing from data/SOURCES.md table rows: " + "; ".join(
        f"{host} (first in {path.relative_to(REPO_ROOT)})"
        for host, path in sorted(missing.items())
    )


def test_unlisted_host_is_reported_and_listed_or_empty_hosts_are_not() -> None:
    sources_text = SOURCES_PATH.read_text(encoding="utf-8")
    fake = Path("fake.py")
    reported = unlisted_hosts(
        sources_text, {fake: 'URL = "https://not-in-sources.example.org/x"'}
    )
    assert reported == {"not-in-sources.example.org": fake}
    listed = unlisted_hosts(
        sources_text, {fake: 'CDSE = "https://stac.dataspace.copernicus.eu/v1"'}
    )
    assert listed == {}
    assert unlisted_hosts(sources_text, {fake: 'PREFIX = "https://"'}) == {}


def test_fixture_directories_hold_files() -> None:
    assert len(fixture_files()) > 0


@pytest.mark.parametrize(
    "path",
    fixture_files(),
    ids=lambda path: str(path.relative_to(REPO_ROOT / "tests" / "fixtures")),
)
def test_fixture_checksum_appears_in_sources(path: Path) -> None:
    sources_text = SOURCES_PATH.read_text(encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest in sources_text, (
        f"sha256 of {path.relative_to(REPO_ROOT)} ({digest}) is not in data/SOURCES.md"
    )
