"""Tests that the code licence is stated and kept apart from the data licences."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO = Path(__file__).parent.parent


def _readme_section(heading: str) -> str:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def test_licence_file_exists_with_mit_text() -> None:
    path = REPO / "LICENSE"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "Copyright (c) 2026 Jarrod Baker" in text
    assert "Permission is hereby granted, free of charge" in text


def test_pyproject_license_field_is_set_and_matches_licence_file() -> None:
    with (REPO / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    licence = project["license"]
    assert isinstance(licence, str)
    assert licence == "MIT"
    first_line = (REPO / "LICENSE").read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "MIT License"


def test_readme_states_code_and_data_licences_separately() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    section = _readme_section("## Data sources and licences")
    assert "MIT" in section
    assert "LICENSE" in section
    assert "CC BY-NC 4.0" in section
    assert "CC BY 4.0" in section
    assert "no licence file" not in readme


def test_readme_data_table_row_states_cc_by_nc_for_dbca_010() -> None:
    section = _readme_section("## Data sources and licences")
    rows = [
        line
        for line in section.splitlines()
        if line.startswith("| DBCA-010 Ramsar Sites")
    ]
    assert len(rows) == 1
    assert "CC BY-NC 4.0" in rows[0]


def test_agents_locked_decision_names_cc_by_nc_for_dbca_010() -> None:
    text = " ".join((REPO / "AGENTS.md").read_text(encoding="utf-8").split())
    assert "Ramsar sites (DBCA-010, CC BY-NC 4.0) are the reporting unit" in text
