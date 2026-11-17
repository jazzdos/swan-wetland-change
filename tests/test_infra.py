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


SETTINGS: Final = (
    "block_public_acls",
    "ignore_public_acls",
    "block_public_policy",
    "restrict_public_buckets",
)


def _assert_private(main: str) -> None:
    """All four access-block settings are on and nothing grants access."""
    assert main.count('resource "aws_s3_bucket_public_access_block"') == 1
    block = _block(main, 'resource "aws_s3_bucket_public_access_block"')
    settings = dict(
        re.findall(r"^\s*(\w+)\s*=\s*(true|false)\s*$", block, re.MULTILINE)
    )
    assert settings == {name: "true" for name in SETTINGS}
    assert "aws_s3_bucket_policy" not in main
    assert "aws_s3_bucket_cors_configuration" not in main
    assert "public_read" not in main
    assert "aws_s3_bucket_acl" not in main
    assert not re.search(r"^\s*acl\s*=", main, re.MULTILINE)
    names = re.findall(r'data "aws_iam_policy_document" "([^"]+)"', main)
    assert sorted(names) == ["pipeline_access", "pipeline_trust"]
    principals = _blocks(main, r"^\s*principals\s*\{")
    assert principals
    for principal in principals:
        assert re.search(r'type\s*=\s*"Federated"', principal), principal
        assert '"*"' not in principal
    assert not re.search(r'identifiers\s*=\s*\["\*"\]', main)


def test_main_tf_is_private() -> None:
    _assert_private(_read("main.tf"))


def _flip_setting(name: str) -> Callable[[str], str]:
    return lambda main: re.sub(rf"({name}\s*=\s*)true", r"\1false", main)


def _append_bucket_policy(main: str) -> str:
    return (
        main
        + '\nresource "aws_s3_bucket_policy" "extra" {\n'
        + "  bucket = aws_s3_bucket.outputs.id\n"
        + '  policy = "{}"\n'
        + "}\n"
    )


def _append_wildcard_principal(main: str) -> str:
    policy = _block(main, 'data "aws_iam_policy_document" "pipeline_access"')
    statement = (
        "\n  statement {\n"
        '    effect    = "Allow"\n'
        '    actions   = ["s3:GetObject"]\n'
        '    resources = ["${aws_s3_bucket.outputs.arn}/*"]\n'
        "\n    principals {\n"
        '      type        = "*"\n'
        '      identifiers = ["*"]\n'
        "    }\n"
        "  }\n"
    )
    return main.replace(policy, policy[:-1] + statement + "}")


def _append_cors(main: str) -> str:
    return (
        main
        + '\nresource "aws_s3_bucket_cors_configuration" "extra" {\n'
        + "  bucket = aws_s3_bucket.outputs.id\n"
        + "\n  cors_rule {\n"
        + '    allowed_methods = ["GET"]\n'
        + '    allowed_origins = ["https://example.org"]\n'
        + "  }\n"
        + "}\n"
    )


PRIVATE_MUTATIONS: Final[dict[str, Callable[[str], str]]] = {
    **{f"{name}-false": _flip_setting(name) for name in SETTINGS},
    "bucket-policy-added": _append_bucket_policy,
    "wildcard-principal-added": _append_wildcard_principal,
    "cors-added": _append_cors,
}


@pytest.mark.parametrize("mutation", sorted(PRIVATE_MUTATIONS))
def test_private_check_fails_when_the_bucket_gains_access(mutation: str) -> None:
    main = _read("main.tf")
    mutated = PRIVATE_MUTATIONS[mutation](main)
    assert mutated != main
    with pytest.raises(AssertionError):
        _assert_private(mutated)


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
def test_bucket_descriptions_say_private_and_name_the_pending_apply(
    name: str, header: str
) -> None:
    text = _description(name, header)
    assert "ADR 0017" in text
    assert "AWS credentials" in text
    assert "until the 0017 apply" in text
    assert "anonymous read" not in text.lower()
    if "ADR 0016" in text:
        assert re.search(r"until the 0017 apply.*ADR 0016", text), text


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


def test_infra_readme_has_no_public_read_section() -> None:
    assert "\n## Applying public read\n" not in _read("README.md")


def test_infra_readme_gives_plan_review_apply_and_header_check() -> None:
    section = _readme_section("Applying the private configuration")
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
    assert "output -raw bucket_url" in check
    assert "/stac/catalog.json" in check
    assert "Origin" not in check
    assert lines.index(plan) < lines.index(apply) < lines.index(check)
    for needed in (
        "0 to add",
        "1 to change",
        "2 to destroy",
        "aws_s3_bucket_public_access_block.outputs",
        "aws_s3_bucket_policy.public_read",
        "aws_s3_bucket_cors_configuration.outputs",
        "403",
        "docs/decisions/0017-private-output-bucket-again.md",
        "never by an agent",
        "xfail",
    ):
        assert needed in section, needed


def test_infra_readme_documents_presigned_urls_and_stays_private() -> None:
    lowered = _read("README.md").lower()
    assert "presigned" in lowered
    assert "aws s3 presign" in lowered
    for forbidden in (
        "intentionally public",
        "access-control-allow-origin",
        "the bucket is public",
    ):
        assert forbidden not in lowered, forbidden


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
