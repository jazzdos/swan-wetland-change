"""Offline text checks on the OpenTofu module in infra/ (no terraform binary needed)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

REPO = Path(__file__).resolve().parents[1]
INFRA = REPO / "infra"


def _read(name: str) -> str:
    return (INFRA / name).read_text(encoding="utf-8")


def _balanced(text: str, start: int) -> str:
    """Return the brace-balanced block whose header begins at index start."""
    open_at = text.index("{", start)
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError(f"unbalanced block at {start}")


def _block(text: str, header: str) -> str:
    """Return the brace-balanced block that starts at the given header line."""
    return _balanced(text, text.index(header))


def _blocks(text: str, header_re: str) -> list[str]:
    """Return every brace-balanced block whose header matches the regex."""
    return [
        _balanced(text, m.start()) for m in re.finditer(header_re, text, re.MULTILINE)
    ]


def _policy(name: str) -> str:
    return _block(_read("main.tf"), f'data "aws_iam_policy_document" "{name}"')


def test_infra_has_tf_files() -> None:
    names = {p.name for p in INFRA.glob("*.tf")}
    assert {"main.tf", "variables.tf", "outputs.tf", "versions.tf"} <= names


def test_trust_policy_pins_audience_and_main_branch_subject() -> None:
    policy = _policy("pipeline_trust")
    assert len(_blocks(policy, r"^\s*statement\s*\{")) == 1
    conditions = _blocks(policy, r"^\s*condition\s*\{")
    assert len(conditions) == 2
    by_variable = {}
    for cond in conditions:
        assert re.search(r'test\s*=\s*"StringEquals"', cond), cond
        variable = re.search(r'variable\s*=\s*"([^"]+)"', cond)
        values = re.search(r"values\s*=\s*\[(.*?)\]", cond, re.DOTALL)
        assert variable and values, cond
        by_variable[variable.group(1)] = re.findall(r'"([^"]+)"', values.group(1))
    assert by_variable == {
        "token.actions.githubusercontent.com:aud": ["sts.amazonaws.com"],
        "token.actions.githubusercontent.com:sub": [
            "repo:${var.github_repository}:ref:refs/heads/main"
        ],
    }


def test_public_access_block_sets_all_four_settings_to_true() -> None:
    main = _read("main.tf")
    assert main.count('resource "aws_s3_bucket_public_access_block"') == 1
    block = _block(main, 'resource "aws_s3_bucket_public_access_block"')
    for name in (
        "block_public_acls",
        "ignore_public_acls",
        "block_public_policy",
        "restrict_public_buckets",
    ):
        assert re.search(rf"^\s*{name}\s*=\s*true\s*$", block, re.MULTILINE), name
    assert not re.search(r"=\s*false", block)


def test_no_public_policy_document_or_bucket_policy() -> None:
    main = _read("main.tf")
    names = re.findall(r'data "aws_iam_policy_document" "([^"]+)"', main)
    assert set(names) == {"pipeline_trust", "pipeline_access"}
    assert "aws_s3_bucket_policy" not in main
    assert "public_read" not in main
    assert "aws_s3_bucket_acl" not in main
    assert not re.search(r"^\s*acl\s*=", main, re.MULTILINE)
    principals = _blocks(main, r"^\s*principals\s*\{")
    assert principals
    for block in principals:
        assert re.search(r'type\s*=\s*"Federated"', block), block
        assert '"*"' not in block
    assert not re.search(r'identifiers\s*=\s*\["\*"\]', main)
    assert "PublicRead" not in main
    assert "PublicList" not in main
    # The only S3 read actions in the module belong to the pipeline role.
    access = _policy("pipeline_access")
    assert "s3:ListBucket" in access
    assert "s3:GetObject" in access
    assert main.count("s3:ListBucket") == 1
    assert main.count("s3:GetObject") == 1


def test_no_cors_configuration() -> None:
    main = _read("main.tf")
    assert "aws_s3_bucket_cors_configuration" not in main
    assert "cors_rule" not in main
    assert "allowed_origins" not in main


def test_infra_text_describes_a_private_bucket() -> None:
    for name in ("variables.tf", "outputs.tf"):
        assert "public" not in _read(name).lower(), name
    readme = _read("README.md").lower()
    for forbidden in (
        "public-read",
        "public bucket",
        "cors",
        "stac-browser",
        "anonymous caller",
        "intentionally public",
    ):
        assert forbidden not in readme, forbidden
    assert "private" in readme


def test_oidc_provider_url_and_client_id() -> None:
    provider = _block(_read("main.tf"), 'resource "aws_iam_openid_connect_provider"')
    assert re.search(
        r'url\s*=\s*"https://token\.actions\.githubusercontent\.com"', provider
    )
    assert re.search(r'client_id_list\s*=\s*\["sts\.amazonaws\.com"\]', provider)


def test_required_variables_have_no_defaults() -> None:
    variables = _read("variables.tf")
    for name in ("bucket_name", "github_repository", "aws_region"):
        block = _block(variables, f'variable "{name}"')
        assert not re.search(r"^\s*default\s*=", block, re.MULTILINE), name


IMMUTABLE_REPOSITORY: Final = "jazzdos@33918812/swan-wetland-change@1438569874"


def _github_repository_pattern() -> re.Pattern[str]:
    block = _block(_read("variables.tf"), 'variable "github_repository"')
    call = re.search(r'regex\("((?:[^"\\]|\\.)*)",\s*var\.github_repository\)', block)
    assert call, (
        "github_repository validation must call regex(..., var.github_repository)"
    )
    raw = call.group(1).replace("\\\\", "\\")
    return re.compile(raw)


def test_github_repository_validation_accepts_immutable_subject_form() -> None:
    assert _github_repository_pattern().fullmatch(IMMUTABLE_REPOSITORY)


@pytest.mark.parametrize(
    "value",
    [
        "jazzdos/swan-wetland-change",
        "jazzdos@abc/swan-wetland-change@1438569874",
        "jazzdos@33918812/swan-wetland-change@abc",
        "jazzdos@33918812/swan-wetland-change",
        f"repo:{IMMUTABLE_REPOSITORY}",
        f"{IMMUTABLE_REPOSITORY}:ref:refs/heads/main",
    ],
    ids=[
        "plain-owner-name",
        "non-numeric-owner-id",
        "non-numeric-repo-id",
        "missing-repo-id",
        "repo-prefix",
        "ref-suffix",
    ],
)
def test_github_repository_validation_rejects_other_forms(value: str) -> None:
    assert not _github_repository_pattern().search(value)


def test_trust_subject_resolves_to_immutable_main_branch_subject() -> None:
    template = "repo:${var.github_repository}:ref:refs/heads/main"
    assert template in _read("main.tf")
    assert f"github_repository={IMMUTABLE_REPOSITORY} " in _read("README.md")
    assert template.replace("${var.github_repository}", IMMUTABLE_REPOSITORY) == (
        "repo:jazzdos@33918812/swan-wetland-change@1438569874:ref:refs/heads/main"
    )


def test_outputs_declared() -> None:
    outputs = _read("outputs.tf")
    for name in ("role_arn", "bucket_url"):
        assert f'output "{name}"' in outputs


def test_pipeline_access_scopes_actions_to_bucket_and_objects() -> None:
    policy = _policy("pipeline_access")
    statements = _blocks(policy, r"^\s*statement\s*\{")
    by_actions = {}
    for stmt in statements:
        assert re.search(r'effect\s*=\s*"Allow"', stmt), stmt
        actions = re.search(r"actions\s*=\s*\[(.*?)\]", stmt, re.DOTALL)
        resources = re.search(r"resources\s*=\s*\[(.*?)\]", stmt, re.DOTALL)
        assert actions and resources, stmt
        key = tuple(re.findall(r'"([^"]+)"', actions.group(1)))
        assert key not in by_actions, f"duplicate statement for {key}"
        by_actions[key] = resources.group(1).strip()
    assert len(statements) == 2
    assert by_actions == {
        ("s3:ListBucket",): "aws_s3_bucket.outputs.arn",
        ("s3:GetObject", "s3:PutObject", "s3:DeleteObject"): (
            '"${aws_s3_bucket.outputs.arn}/*"'
        ),
    }


def test_pipeline_role_max_session_duration_covers_the_job_timeout() -> None:
    role = _block(_read("main.tf"), 'resource "aws_iam_role" "pipeline"')
    match = re.search(r"max_session_duration\s*=\s*(\d+)", role)
    assert match is not None
    duration = int(match.group(1))
    assert 3600 <= duration <= 43200
    # The pipeline job's timeout-minutes in .github/workflows/pipeline.yml.
    job_timeout_minutes = 120
    assert duration >= job_timeout_minutes * 60


def test_oidc_provider_is_optional_and_trust_uses_local_arn() -> None:
    main = _read("main.tf")
    assert "count = var.create_oidc_provider ? 1 : 0" in _block(
        main, 'resource "aws_iam_openid_connect_provider"'
    )
    data = _block(main, 'data "aws_iam_openid_connect_provider"')
    assert "count = var.create_oidc_provider ? 0 : 1" in data
    assert "local.github_oidc_provider_arn" in _policy("pipeline_trust")
    block = _block(_read("variables.tf"), 'variable "create_oidc_provider"')
    assert re.search(r"type\s*=\s*bool", block)
    assert re.search(r"default\s*=\s*true", block)


def test_gitignore_covers_terraform_state() -> None:
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "infra/.terraform/" in lines
    assert "*.tfstate" in lines
    assert ".terraform.lock.hcl" not in "".join(lines)


def test_readme_documents_seeding_from_backfill() -> None:
    readme = _read("README.md")
    assert "backfill" in readme
    assert "initial_lookback_days" in readme
    assert "--output-root s3://" in readme


def test_readme_documents_catalogue_base_url_step() -> None:
    readme = _read("README.md")
    assert "catalogue.base_url" in readme
    assert "bucket_url" in readme
    assert "config/pipeline.toml" in readme


def test_lifecycle_aborts_incomplete_multipart_uploads_after_one_day() -> None:
    block = _block(
        _read("main.tf"),
        'resource "aws_s3_bucket_lifecycle_configuration" "outputs"',
    )
    assert re.search(r"bucket\s*=\s*aws_s3_bucket\.outputs\.id", block)
    rules = _blocks(block, r"^\s*rule\s*\{")
    assert len(rules) == 1
    rule = rules[0]
    assert re.search(r'status\s*=\s*"Enabled"', rule)
    abort = _blocks(rule, r"^\s*abort_incomplete_multipart_upload\s*\{")
    assert len(abort) == 1
    assert re.search(r"days_after_initiation\s*=\s*1\b", abort[0])
    assert "expiration" not in block
    assert "transition" not in block


def test_readme_documents_multipart_lifecycle() -> None:
    assert "multipart" in _read("README.md")
