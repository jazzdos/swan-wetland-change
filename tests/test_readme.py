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


def test_readme_has_no_anonymous_duckdb_secret() -> None:
    lowered = _readme().lower()
    assert "provider config" not in lowered
    assert "anonymous_outputs" not in lowered
    _s3_block("credential_chain")


def test_readme_records_adr_0017() -> None:
    section = _section(_readme(), "Querying with DuckDB")
    prose = re.sub(r"```sql\n.*?```", "", section, flags=re.DOTALL).lower()
    for needed in ("0017", "credential", "presigned", "aws s3 presign"):
        assert needed in prose, needed
    deployment = _section(_readme(), "Deployment").lower()
    for needed in (
        "0017-private-output-bucket-again",
        "2026-11-17",
        "0016",
        "applied",
    ):
        assert needed in deployment, needed
    assert "pending" not in deployment
    assert "pending" not in prose
    limitations = _section(_readme(), "Limitations").lower()
    for needed in ("0017", "2026-11-17", "cannot be withdrawn"):
        assert needed in limitations, needed
    assert "its apply is pending" not in limitations
    assert "once the 0017 apply is done" not in limitations
    for forbidden in (
        "public read has been in effect",
        "public read is configured but not applied",
    ):
        assert forbidden not in limitations, forbidden
    assert "Applying public read" not in _readme()


def test_readme_ramsar_12_bullet_records_jarrods_approval() -> None:
    limitations = " ".join(_section(_readme(), "Limitations").split())
    assert "approved by Jarrod on 2026-11-06 (ADR 0010" in limitations
    assert "pending Jarrod's review" not in limitations


PUBLIC_READ_CLAIMS = (
    r"\b(publicly|anonymously)\s+readable\b",
    r"\breadable\s+(publicly|anonymously)\b",
    r"\bpublic[- ]read\s+bucket\b",
    r"\bpublicly\s+accessible\b",
)


def _claims_public_read(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(re.search(pattern, lowered) for pattern in PUBLIC_READ_CLAIMS)


@pytest.mark.parametrize(
    "sentence",
    [
        "The bucket is publicly readable.",
        "The catalogue is readable anonymously over https.",
        "The observations are anonymously readable.",
    ],
)
def test_claims_public_read_detector_flags(sentence: str) -> None:
    assert _claims_public_read(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "Every object was readable by key without credentials until the 0017 apply.",
        "The bucket is readable only with AWS credentials.",
    ],
)
def test_claims_public_read_detector_passes(sentence: str) -> None:
    assert not _claims_public_read(sentence)


def test_readme_has_no_public_read_claim() -> None:
    sentences = re.split(r"(?<=[.!?])\s+", _flat(_readme()))
    for sentence in sentences:
        assert not _claims_public_read(sentence), sentence


def test_readme_does_not_use_the_banned_public_phrases() -> None:
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


def test_readme_stac_row_names_adr_0017_and_claims_no_live_check() -> None:
    rows = [
        line for line in _readme().splitlines() if line.startswith("| STAC catalogue |")
    ]
    assert len(rows) == 1
    row = " ".join(rows[0].split()).lower()
    for needed in (
        "adr 0017",
        "credentials",
        "no live stac check is implemented",
        "spike 6",
    ):
        assert needed in row, needed
    for forbidden in ("readable anonymously", "cors", "bucket is private"):
        assert forbidden not in row, forbidden


def test_readme_claims_no_spike_ran() -> None:
    text = _readme().lower()
    for forbidden in (
        "spike 6 ran",
        "spike 6 has run",
        "spike 7 ran",
        "spike 7 has run",
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


def test_readme_documents_credential_expiry() -> None:
    section = _section(_readme(), "Querying with DuckDB")
    prose = re.sub(r"```sql\n.*?```", "", section, flags=re.DOTALL)
    for needle in ("15 minutes", "aws login", "not refreshed", "ExpiredToken"):
        assert needle in prose, needle


def test_readme_gives_standalone_credentialed_live_command() -> None:
    section = _section(_readme(), "Querying with DuckDB")
    command = "uv run pytest -q -m live tests/test_live_credentialed_read.py"
    blocks = re.findall(r"```sh\n(.*?)```", section, flags=re.DOTALL)
    holding = [block for block in blocks if command in block]
    assert holding
    block = holding[0]
    assert "aws configure export-credentials" in block
    assert block.index(command) > block.index("aws configure export-credentials")


def test_readme_limitations_dates_anonymous_live_pass() -> None:
    section = " ".join(_section(_readme(), "Limitations").split())
    for needle in (
        "no agent has run the test (the weekly",
        "Update 2026-11-16",
        "ebea401",
        "xfail",
        "0017",
        "403",
        "marker was removed",
        "unsigned",
    ):
        assert needle in section, needle
    assert "xfail(strict=True)" not in section


def test_readme_does_not_call_the_0017_apply_pending() -> None:
    flat = " ".join(_readme().split()).lower()
    for phrase in (
        "apply is pending",
        "apply pending",
        "until the 0017 apply is run",
        "once the 0017 apply is done",
    ):
        assert phrase not in flat, phrase


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


def _flat(text: str) -> str:
    return " ".join(text.split())


DBCA_CARRIERS = (
    "observation and change files",
    "STAC collection and items",
)
DBCA_NON_CARRIERS = (
    "ledger files",
    "run manifests",
    "verification JSON",
    "Markdown reports",
    "`catalog.json`",
    "`stac/write-index.json`",
)


def test_dbca_attribution_scope_is_stated_in_the_data_sources_section() -> None:
    section = _flat(_section(_readme(), "Data sources and licences"))
    marker = "The DBCA-010 attribution, term T3 of the same document, is carried by"
    assert marker in section
    scope = section[section.index(marker) :]
    carriers_sentence, _, rest = scope.partition(". ")
    non_carriers_sentence, found, _ = rest.partition("carry none.")
    assert found, scope
    for carrier in DBCA_CARRIERS:
        assert carrier in carriers_sentence, carrier
        assert carrier not in non_carriers_sentence, carrier
    for other in DBCA_NON_CARRIERS:
        assert other in non_carriers_sentence, other
        assert other not in carriers_sentence, other
    assert "They also carry the DBCA-010 attribution" not in section


def test_dbca_attribution_scope_does_not_contradict_across_sections() -> None:
    text = _flat(_readme())
    assert "hold no DBCA-010 material" not in text
    for heading, level in (("Running locally", 2), ("Attribution backfill", 3)):
        section = _flat(_section(_readme(), heading, level=level))
        assert (
            "`build-catalogue` writes `dbca_attribution` to the STAC collection"
            " and items"
        ) in section, heading
        assert "does not scan the catalogue" in section, heading


def test_attribution_backfill_names_the_adr_0016_gate() -> None:
    section = _flat(_section(_readme(), "Attribution backfill", level=3))
    assert "step 2 of 'Preconditions of the apply' in ADR 0016" in section
    assert "docs/decisions/0016-public-read-output-bucket.md" in section
    assert "ADR 0011 step 3" not in section
    assert "0011-private-output-bucket" not in section
