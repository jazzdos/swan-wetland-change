"""Offline text checks on the OpenTofu module in infra/ (no terraform binary needed)."""

from __future__ import annotations

import re
from collections.abc import Callable
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


def _list_values(block: str, name: str) -> list[str]:
    """The quoted strings of the list attribute `name` in an HCL block."""
    match = re.search(rf"^\s*{name}\s*=\s*\[(.*?)\]", block, re.MULTILINE | re.DOTALL)
    assert match, f"no {name} list in block"
    return re.findall(r'"([^"]+)"', match.group(1))


def _statement_with(policy: str, action: str) -> str:
    statements = [
        s for s in _blocks(policy, r"^\s*statement\s*\{") if f'"{action}"' in s
    ]
    assert len(statements) == 1, f"expected one statement with {action}"
    return statements[0]


def _assert_public_read(policy: str) -> None:
    """Anonymous GetObject on objects, anonymous ListBucket under observations/."""
    assert len(_blocks(policy, r"^\s*statement\s*\{")) == 2
    get_stmt = _statement_with(policy, "s3:GetObject")
    list_stmt = _statement_with(policy, "s3:ListBucket")
    for stmt in (get_stmt, list_stmt):
        assert re.search(r'effect\s*=\s*"Allow"', stmt), stmt
        principals = _blocks(stmt, r"^\s*principals\s*\{")
        assert len(principals) == 1, stmt
        assert re.search(r'type\s*=\s*"\*"', principals[0]), stmt
        assert _list_values(principals[0], "identifiers") == ["*"]
    assert _list_values(get_stmt, "actions") == ["s3:GetObject"]
    assert _list_values(get_stmt, "resources") == ["${aws_s3_bucket.outputs.arn}/*"]
    assert not _blocks(get_stmt, r"^\s*condition\s*\{")
    assert _list_values(list_stmt, "actions") == ["s3:ListBucket"]
    assert re.search(r"resources\s*=\s*\[aws_s3_bucket\.outputs\.arn\]", list_stmt)
    conditions = _blocks(list_stmt, r"^\s*condition\s*\{")
    assert len(conditions) == 1, "the list statement needs one s3:prefix condition"
    condition = conditions[0]
    assert re.search(r'test\s*=\s*"StringLike"', condition)
    assert re.search(r'variable\s*=\s*"s3:prefix"', condition)
    assert _list_values(condition, "values") == ["observations/*"]
    for forbidden in ("s3:PutObject", "s3:DeleteObject", "s3:*"):
        assert forbidden not in policy, forbidden
    # An unconditioned public list would expose the bucket root and ledger/.
    assert policy.count("s3:ListBucket") == 1


def _drop_list_condition(policy: str) -> str:
    list_stmt = _statement_with(policy, "s3:ListBucket")
    condition = _blocks(list_stmt, r"^\s*condition\s*\{")[0]
    return policy.replace(condition, "")


PREFIX_MUTATIONS: Final[dict[str, Callable[[str], str]]] = {
    "condition-removed": _drop_list_condition,
    "prefix-widened": lambda p: re.sub(
        r'(values\s*=\s*)\["observations/\*"\]', r'\1["*"]', p
    ),
    "variable-changed": lambda p: p.replace('"s3:prefix"', '"s3:delimiter"'),
    "test-negated": lambda p: p.replace('"StringLike"', '"StringNotLike"'),
}


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


def test_public_access_block_keeps_acl_blocks_on_and_policy_blocks_off() -> None:
    main = _read("main.tf")
    assert main.count('resource "aws_s3_bucket_public_access_block"') == 1
    block = _block(main, 'resource "aws_s3_bucket_public_access_block"')
    settings = dict(
        re.findall(r"^\s*(\w+)\s*=\s*(true|false)\s*$", block, re.MULTILINE)
    )
    assert settings == {
        "block_public_acls": "true",
        "ignore_public_acls": "true",
        "block_public_policy": "false",
        "restrict_public_buckets": "false",
    }


def test_policy_documents_and_principals_outside_public_read() -> None:
    main = _read("main.tf")
    names = re.findall(r'data "aws_iam_policy_document" "([^"]+)"', main)
    assert sorted(names) == ["pipeline_access", "pipeline_trust", "public_read"]
    assert "aws_s3_bucket_acl" not in main
    assert not re.search(r"^\s*acl\s*=", main, re.MULTILINE)
    outside = main.replace(_policy("public_read"), "")
    principals = _blocks(outside, r"^\s*principals\s*\{")
    assert principals
    for block in principals:
        assert re.search(r'type\s*=\s*"Federated"', block), block
        assert '"*"' not in block
    assert not re.search(r'identifiers\s*=\s*\["\*"\]', outside)


def test_public_read_policy_is_getobject_plus_observations_list() -> None:
    _assert_public_read(_policy("public_read"))


@pytest.mark.parametrize("mutation", sorted(PREFIX_MUTATIONS))
def test_public_read_check_fails_when_the_list_statement_loses_its_prefix_condition(
    mutation: str,
) -> None:
    policy = _policy("public_read")
    mutated = PREFIX_MUTATIONS[mutation](policy)
    assert mutated != policy
    with pytest.raises(AssertionError):
        _assert_public_read(mutated)


def test_bucket_policy_attaches_public_read_after_the_access_block() -> None:
    main = _read("main.tf")
    assert main.count('resource "aws_s3_bucket_policy"') == 1
    block = _block(main, 'resource "aws_s3_bucket_policy" "public_read"')
    for line in (
        r"bucket\s*=\s*aws_s3_bucket\.outputs\.id",
        r"policy\s*=\s*data\.aws_iam_policy_document\.public_read\.json",
        r"depends_on\s*=\s*\[aws_s3_bucket_public_access_block\.outputs\]",
    ):
        assert re.search(rf"^\s*{line}\s*$", block, re.MULTILINE), line


def test_cors_allows_only_get_and_head_from_any_origin() -> None:
    main = _read("main.tf")
    assert main.count('resource "aws_s3_bucket_cors_configuration"') == 1
    cors = _block(main, 'resource "aws_s3_bucket_cors_configuration" "outputs"')
    assert re.search(
        r"^\s*bucket\s*=\s*aws_s3_bucket\.outputs\.id\s*$", cors, re.MULTILINE
    )
    rules = _blocks(cors, r"^\s*cors_rule\s*\{")
    assert len(rules) == 1
    assert _list_values(rules[0], "allowed_methods") == ["GET", "HEAD"]
    assert _list_values(rules[0], "allowed_origins") == ["*"]


def _description(name: str, header: str) -> str:
    match = re.search(r'description\s*=\s*"([^"]+)"', _block(_read(name), header))
    assert match, header
    return match.group(1)


@pytest.mark.parametrize(
    ("name", "header"),
    [
        ("variables.tf", 'variable "bucket_name"'),
        ("outputs.tf", 'output "bucket_url"'),
    ],
)
def test_bucket_descriptions_tie_public_read_to_the_operator_apply(
    name: str, header: str
) -> None:
    text = _description(name, header)
    assert "when the operator applies this module" in text
    assert "ADR 0016" in text
    assert "AWS credentials" in text


def test_infra_readme_records_adr_0016_and_its_limits() -> None:
    readme = _read("README.md")
    lowered = readme.lower()
    assert "docs/decisions/0016-public-read-output-bucket.md" in readme
    for needed in (
        "operator's apply",
        "never by an agent",
        "billed to the bucket owner",
        "observations/",
    ):
        assert needed in lowered, needed
    for forbidden in (
        "intentionally public",
        "nothing grants anonymous access",
        "never add a bucket policy that grants public access",
        "the bucket is public",
        "public-read s3 bucket",
    ):
        assert forbidden not in lowered, forbidden


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


def _readme_section(heading: str) -> str:
    readme = _read("README.md")
    start = readme.index(f"\n## {heading}\n")
    end = readme.find("\n## ", start + 1)
    return readme[start:] if end == -1 else readme[start:end]


def test_infra_readme_gives_plan_review_apply_and_header_check() -> None:
    section = _readme_section("Applying public read")
    lines = section.splitlines()
    plan = (
        "terraform -chdir=infra plan -var bucket_name=<bucket> "
        f"-var github_repository={IMMUTABLE_REPOSITORY} "
        "-var create_oidc_provider=false -var aws_region=<region>"
    )
    apply = plan.replace(" plan ", " apply ")
    checks = [line for line in lines if line.startswith("curl ")]
    assert len(checks) == 1
    check = checks[0]
    assert " -I " in check
    assert '-H "Origin: ' in check
    assert "output -raw bucket_url" in check
    assert "access-control-allow-origin" in check.lower()
    assert lines.index(plan) < lines.index(apply) < lines.index(check)
    for needed in (
        "review",
        "st-22f1",
        "backfill",
        "200",
        "Access-Control-Allow-Origin: *",
        "403",
        "xfail",
    ):
        assert needed in section, needed


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
