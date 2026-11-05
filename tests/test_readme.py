"""Tests that README.md matches the design, the CLI and the output layout."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import click
import duckdb
import pytest
from shapely.geometry.base import BaseGeometry
from typer.testing import CliRunner

from tests.test_pipeline import NOW, FakeClient, _polygons, _run
from wetland_change.cli import app

REPO = Path(__file__).parent.parent
README = REPO / "README.md"
DESIGN = REPO / "docs" / "plans" / "2026-10-29-swan-wetland-change-design.md"

REQUIRED_HEADINGS = [
    "Design choices",
    "Architecture",
    "Verification matrix",
    "Running locally",
    "Querying with DuckDB",
    "Deployment",
    "Limitations",
]
REQUIRED_SUBCOMMANDS = {
    "discover",
    "run",
    "backfill",
    "score",
    "verify",
    "build-catalogue",
    "freshness",
}
PATH_PREFIXES = ("src/", "tests/", "scripts/", "infra/", ".github/")


def _section(text: str, heading: str, level: int = 2) -> str:
    """Return the body under `heading`, up to the next heading of any level."""
    lines = text.splitlines()
    marker = "#" * level + " " + heading
    start = lines.index(marker) + 1
    body: list[str] = []
    for line in lines[start:]:
        if re.match(r"#{1,6} ", line):
            break
        body.append(line)
    return "\n".join(body)


def _table_rows(body: str) -> list[list[str]]:
    """Parse the first markdown table in `body`, dropping header and separator."""
    rows: list[list[str]] = []
    for line in body.splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows[2:]


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def test_readme_has_required_headings() -> None:
    headings = re.findall(r"^## (.+)$", _readme(), flags=re.MULTILINE)
    for required in REQUIRED_HEADINGS:
        assert headings.count(required) == 1, required


def test_readme_matrix_covers_every_design_row() -> None:
    design = DESIGN.read_text(encoding="utf-8")
    design_rows = _table_rows(_section(design, "Known-good verification matrix"))
    goals = [row[0] for row in design_rows]
    assert len(goals) == 14

    readme_rows = _table_rows(_section(_readme(), "Verification matrix"))
    readme_goals = [row[0] for row in readme_rows]
    for goal in goals:
        assert goal in readme_goals, goal


def test_readme_matrix_paths_exist_and_rows_are_accounted_for() -> None:
    readme_rows = _table_rows(_section(_readme(), "Verification matrix"))
    assert len(readme_rows) >= 14
    for row in readme_rows:
        goal, implementation = row[0], row[2]
        paths = [
            token
            for token in re.findall(r"`([^`]+)`", implementation)
            if token.startswith(PATH_PREFIXES)
        ]
        for path in paths:
            assert (REPO / path).exists(), f"{goal}: {path} does not exist"
        assert paths or "not implemented" in "|".join(row), goal


def test_readme_duckdb_query_returns_rows(
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = _section(_readme(), "Querying with DuckDB")
    match = re.search(r"```sql\n(.*?)```", section, flags=re.DOTALL)
    assert match, "no sql block in the DuckDB section"
    query = match.group(1)

    _run(
        tmp_path,
        FakeClient([copy.deepcopy(fixture_item)]),
        _polygons(fixture_polygon),
        NOW,
    )
    (tmp_path / "out").rename(tmp_path / "outputs")
    monkeypatch.chdir(tmp_path)

    rows = duckdb.connect().execute(query).fetchall()
    assert len(rows) >= 1


def _public_list_prefixes() -> list[str]:
    """Prefixes the public_read policy lets anonymous callers list."""
    main_tf = (REPO / "infra" / "main.tf").read_text(encoding="utf-8")
    policy = main_tf[main_tf.index('data "aws_iam_policy_document" "public_read"') :]
    policy = policy[: policy.index('resource "aws_s3_bucket_policy"')]
    match = re.search(
        r'variable\s*=\s*"s3:prefix".*?values\s*=\s*\[(.*?)\]', policy, re.DOTALL
    )
    assert match, "no s3:prefix condition in the public_read policy"
    return [v.removesuffix("/*") for v in re.findall(r'"([^"]+)"', match.group(1))]


def test_readme_anonymous_s3_query_matches_public_list_policy() -> None:
    section = _section(_readme(), "Querying with DuckDB")
    blocks = re.findall(r"```sql\n(.*?)```", section, flags=re.DOTALL)
    assert len(blocks) >= 2, "expected a local and an anonymous S3 sql block"
    block = blocks[1]
    lowered = block.lower()
    assert "LOAD httpfs" in block
    assert "hive_partitioning = true" in block
    assert "key_id" not in lowered
    assert "session_token" not in lowered
    glob = re.search(r"s3://[^/'\s]+/([^/'\s*]+)/", block)
    assert glob, "no s3://<bucket>/<first-segment>/ glob in the S3 sql block"
    assert glob.group(1) in _public_list_prefixes()


def _running_locally_subcommands() -> list[str]:
    section = _section(_readme(), "Running locally")
    blocks = re.findall(r"```\w*\n(.*?)```", section, flags=re.DOTALL)
    names: list[str] = []
    for block in blocks:
        for line in block.splitlines():
            match = re.search(r"uv run wetland-change ([a-z-]+)", line)
            if match and match.group(1) not in names:
                names.append(match.group(1))
    return names


def test_running_locally_names_the_expected_subcommands() -> None:
    assert REQUIRED_SUBCOMMANDS <= set(_running_locally_subcommands())


def test_every_running_locally_subcommand_answers_help() -> None:
    names = _running_locally_subcommands()
    assert names
    runner = CliRunner()
    for name in names:
        result = runner.invoke(app, [name, "--help"])
        assert result.exit_code == 0, name
        assert "Usage" in click.unstyle(result.output), name
