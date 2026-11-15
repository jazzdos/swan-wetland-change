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


def _query_blocks() -> list[str]:
    section = _section(_readme(), "Querying with DuckDB")
    return re.findall(r"```sql\n(.*?)```", section, flags=re.DOTALL)


def _s3_block(provider: str) -> str:
    blocks = [
        block
        for block in _query_blocks()
        if re.search(rf"provider\s+{provider}\b", block.lower())
    ]
    assert len(blocks) == 1, f"expected one S3 sql block with PROVIDER {provider}"
    return blocks[0]


def _assert_observations_query(block: str) -> None:
    assert "LOAD httpfs" in block
    assert "hive_partitioning = true" in block
    assert "type s3" in block.lower()
    glob = re.search(r"s3://[^/'\s]+/([^/'\s*]+)/", block)
    assert glob, "no s3://<bucket>/<first-segment>/ glob in the S3 sql block"
    assert glob.group(1) == "observations"


def test_readme_credentialed_s3_query_uses_credential_chain() -> None:
    block = _s3_block("credential_chain")
    _assert_observations_query(block)
    lowered = block.lower()
    for forbidden in ("key_id", "secret_key", "session_token", "provider config"):
        assert forbidden not in lowered, forbidden


def test_readme_anonymous_s3_query_names_only_the_region() -> None:
    block = _s3_block("config")
    _assert_observations_query(block)
    lowered = block.lower()
    assert "region '<aws_region>'" in lowered
    for forbidden in (
        "key_id",
        "secret_key",
        "session_token",
        "credential_chain",
        "load aws",
    ):
        assert forbidden not in lowered, forbidden


def test_readme_ties_anonymous_read_to_the_operator_apply() -> None:
    blocks = _query_blocks()
    credentialed = blocks.index(_s3_block("credential_chain"))
    assert credentialed < blocks.index(_s3_block("config"))
    section = _section(_readme(), "Querying with DuckDB")
    prose = re.sub(r"```sql\n.*?```", "", section, flags=re.DOTALL).lower()
    for needed in ("operator's apply", "credential", "0016-public-read-output-bucket"):
        assert needed in prose, needed
    deployment = _section(_readme(), "Deployment").lower()
    assert "0016-public-read-output-bucket" in deployment
    assert "operator's apply" in deployment
    assert "operator's apply" in _section(_readme(), "Limitations").lower()


def test_readme_does_not_call_the_bucket_public_before_the_apply() -> None:
    text = _readme().lower()
    for forbidden in (
        "bucket is public",
        "public bucket",
        "public-read bucket",
        "public s3",
        "intentionally public",
        "is publicly readable",
        "public_outputs",
    ):
        assert forbidden not in text, forbidden


@pytest.mark.parametrize(
    "needle",
    [
        "aws login",
        "aws configure export-credentials",
        "--format env",
        "unset AWS_PROFILE",
    ],
)
def test_readme_documents_aws_login_profile_route(needle: str) -> None:
    section = _section(_readme(), "Querying with DuckDB")
    prose = re.sub(r"```sql\n.*?```", "", section, flags=re.DOTALL)
    assert needle in section
    assert needle in prose


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


def test_readme_live_rows_state_the_layer_rule() -> None:
    rows = _table_rows(_section(_readme(), "Verification matrix"))
    by_name = {row[0]: row for row in rows}
    for name in ("Water extent, live", "NDVI"):
        text = " ".join(by_name[name])
        assert "0012" in text, name
        assert "ramsar" in text, name


BACKFILL_LINES = [
    f"uv run wetland-change {name} --output-root s3://<bucket>/{flag}"
    for name in (
        "add-observation-footers",
        "add-dea-attribution",
        "add-copernicus-notice",
        "add-dbca-attribution",
    )
    for flag in (" --dry-run", "")
] + ["uv run wetland-change build-catalogue --output-root s3://<bucket>/"]


@pytest.mark.parametrize("line", BACKFILL_LINES)
def test_backfill_section_lists_every_rewrite_command(line: str) -> None:
    section = _section(_readme(), "Attribution backfill", level=3)
    assert line in section.splitlines()


def test_backfill_section_names_the_dbca_licence_command_and_keys() -> None:
    section = _section(_readme(), "Attribution backfill", level=3)
    assert "CC BY-NC 4.0" in section
    assert "add-dbca-attribution" in section
    assert "`dbca_attribution`" in section
    assert "dbca_attribution_added_after_the_fact" in section
    assert "add-dbca-attribution" in _running_locally_subcommands()


def test_run_stages_describe_the_dbca_attribution() -> None:
    section = _section(_readme(), "Run stages", level=3)
    assert "dbca_attribution" in section
    assert "CC-BY-NC-4.0" in section
    assert "src/wetland_change/dbca_attribution.py" in section


def test_backfill_section_names_the_workflow_and_both_dispatch_lines() -> None:
    section = _section(_readme(), "Attribution backfill", level=3)
    assert ".github/workflows/backfill.yml" in section
    lines = section.splitlines()
    assert "gh workflow run backfill.yml -f dry_run=true" in lines
    assert "gh workflow run backfill.yml -f dry_run=false" in lines
