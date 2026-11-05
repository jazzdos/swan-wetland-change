"""Offline structural checks for the daily pipeline and weekly verify workflows.

No GitHub repository exists to run the workflows, so these tests read
`.github/workflows/pipeline.yml` and `.github/workflows/verify.yml` and
assert the properties that matter: the schedule, pinned actions,
least-privilege permissions, step order, the commit step surviving a failed
verify, the issue step firing on failure, OIDC role assumption and no secrets.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW: Final = REPO / ".github" / "workflows" / "pipeline.yml"
VERIFY_WORKFLOW: Final = REPO / ".github" / "workflows" / "verify.yml"

BUCKET_URI: Final = "s3://${{ vars.OUTPUT_BUCKET }}"
PINNED_USES: Final = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
RUN_PATTERN: Final = r"wetland-change run --output-root s3://"


def _workflow(path: Path = WORKFLOW) -> dict[Any, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _jobs(doc: dict[Any, Any]) -> dict[str, Any]:
    jobs = doc["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _job(doc: dict[Any, Any]) -> dict[str, Any]:
    jobs = _jobs(doc)
    assert len(jobs) == 1
    return next(iter(jobs.values()))


def _steps(doc: dict[Any, Any]) -> list[dict[str, Any]]:
    return list(_job(doc)["steps"])


def _normalised_condition(step: dict[str, Any]) -> str:
    text = " ".join(str(step.get("if", "")).split())
    match = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", text)
    return match.group(1) if match else text


def _index(steps: list[dict[str, Any]], pattern: str) -> int:
    """Index of the first step whose `run` or `uses` matches the regex."""
    for position, step in enumerate(steps):
        text = str(step.get("run", "")) + " " + str(step.get("uses", ""))
        if re.search(pattern, text):
            return position
    raise AssertionError(f"no step matches {pattern!r}")


def test_schedule_is_daily_with_manual_dispatch() -> None:
    doc = _workflow()
    triggers = doc.get("on", doc.get(True))
    assert triggers["schedule"] == [{"cron": "0 10 * * *"}]
    assert "workflow_dispatch" in triggers


def test_every_action_is_pinned_to_a_full_commit_sha() -> None:
    doc = _workflow()
    references = [
        step["uses"]
        for job in _jobs(doc).values()
        for step in job["steps"]
        if "uses" in step
    ]
    assert len(references) >= 3
    for reference in references:
        assert PINNED_USES.match(reference), reference
    names = {reference.split("@")[0] for reference in references}
    assert {
        "actions/checkout",
        "astral-sh/setup-uv",
        "aws-actions/configure-aws-credentials",
    } <= names


def test_job_permissions_are_exactly_contents_write_and_id_token_write() -> None:
    assert _job(_workflow())["permissions"] == {
        "contents": "write",
        "id-token": "write",
    }


def test_steps_run_fetch_run_verify_catalogue_commit_in_order() -> None:
    steps = _steps(_workflow())
    fetch = _index(steps, r"scripts/fetch_aoi\.py")
    run = _index(steps, RUN_PATTERN)
    catalogue = _index(steps, r"wetland-change build-catalogue")
    verify = _index(steps, r"wetland-change verify")
    commit = _index(steps, r"git commit")
    assert fetch < run < verify < catalogue < commit

    for position in (run, catalogue, verify):
        command = steps[position]["run"]
        assert "--output-root" in command
        assert BUCKET_URI in command


PROCESSED_CONDITION: Final = "!cancelled() && steps.manifest.outputs.processed > 0"


def test_commit_step_still_runs_when_verify_fails() -> None:
    steps = _steps(_workflow())
    verify = _index(steps, r"wetland-change verify")
    commit = _index(steps, r"git commit")

    condition = _normalised_condition(steps[commit])
    assert condition == PROCESSED_CONDITION
    for forbidden in ("steps.verify", "success()", "failure()"):
        assert forbidden not in condition

    assert "continue-on-error" not in steps[verify]


def test_catalogue_is_rebuilt_after_verify_and_survives_a_failed_verify() -> None:
    steps = _steps(_workflow())
    verify = _index(steps, r"wetland-change verify")
    catalogue = _index(steps, r"wetland-change build-catalogue")
    assert verify < catalogue

    condition = _normalised_condition(steps[catalogue])
    assert condition == PROCESSED_CONDITION
    for forbidden in ("steps.verify", "success()", "failure()"):
        assert forbidden not in condition
    assert "continue-on-error" not in steps[catalogue]


def test_manifest_step_reads_the_count_after_a_failed_run_step() -> None:
    steps = _steps(_workflow())
    run = _index(steps, RUN_PATTERN)
    manifest = [
        position for position, step in enumerate(steps) if step.get("id") == "manifest"
    ]
    assert len(manifest) == 1
    step = steps[manifest[0]]
    assert steps[run].get("id") == "run"
    assert run < manifest[0]
    assert _normalised_condition(step) == "!cancelled()"
    assert "continue-on-error" not in steps[run]
    assert "GITHUB_OUTPUT" in step["run"]
    assert "processed" in step["run"]


def test_catalogue_verify_and_commit_run_whenever_scenes_were_processed() -> None:
    steps = _steps(_workflow())
    manifest = next(
        position for position, step in enumerate(steps) if step.get("id") == "manifest"
    )
    for pattern in (
        r"wetland-change build-catalogue",
        r"wetland-change verify",
        r"git commit",
    ):
        position = _index(steps, pattern)
        assert position > manifest
        assert _normalised_condition(steps[position]) == PROCESSED_CONDITION


def test_commit_step_rebases_onto_main_before_pushing_with_a_retry() -> None:
    steps = _steps(_workflow())
    script = steps[_index(steps, r"git commit")]["run"]
    assert "git pull --rebase origin main" in script
    assert script.index("git pull --rebase") < script.index("git push")
    assert re.search(r"for \w+ in 1 2", script)


def test_aws_credentials_step_reads_role_and_region_from_variables() -> None:
    steps = _steps(_workflow())
    aws_steps = [
        step
        for step in steps
        if str(step.get("uses", "")).startswith(
            "aws-actions/configure-aws-credentials@"
        )
    ]
    assert len(aws_steps) == 1
    assert aws_steps[0]["with"]["role-to-assume"] == "${{ vars.AWS_ROLE_ARN }}"
    assert aws_steps[0]["with"]["aws-region"] == "${{ vars.AWS_REGION }}"


def test_aws_credentials_step_requests_the_role_maximum_duration() -> None:
    doc = _workflow()
    aws_steps = [
        step
        for step in _steps(doc)
        if str(step.get("uses", "")).startswith(
            "aws-actions/configure-aws-credentials@"
        )
    ]
    assert len(aws_steps) == 1
    requested = int(aws_steps[0]["with"]["role-duration-seconds"])
    assert requested >= int(_job(doc)["timeout-minutes"]) * 60

    text = (REPO / "infra" / "main.tf").read_text(encoding="utf-8")
    start = text.index('resource "aws_iam_role" "pipeline"')
    end = text.index("\n}\n", start)
    match = re.search(r"max_session_duration\s*=\s*(\d+)", text[start:end])
    assert match is not None
    assert requested == int(match.group(1))


def test_workflow_text_contains_no_secret_literals() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert not re.search(r"AKIA[0-9A-Z]{16}", text)
    assert not re.search(r"ASIA[0-9A-Z]{16}", text)
    lowered = text.lower()
    for needle in (
        "aws-secret-access-key",
        "aws-access-key-id",
        "aws_secret_access_key",
        "aws_access_key_id",
        "secrets.",
    ):
        assert needle not in lowered, needle


def test_actionlint_accepts_the_workflow() -> None:
    executable = shutil.which("actionlint")
    if executable is None:
        pytest.skip("actionlint not installed")
    result = subprocess.run(
        [executable, str(WORKFLOW)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --- weekly verify workflow -------------------------------------------------

LIVE_PATTERN: Final = r"pytest\b.*-m live"
VERIFY_PATTERN: Final = r"wetland-change verify"
FRESHNESS_PATTERN: Final = r"wetland-change freshness"


def _verify_doc() -> dict[Any, Any]:
    return _workflow(VERIFY_WORKFLOW)


def test_verify_schedule_is_weekly_with_manual_dispatch() -> None:
    doc = _verify_doc()
    triggers = doc.get("on", doc.get(True))
    schedule = triggers["schedule"]
    assert len(schedule) == 1
    fields = schedule[0]["cron"].split()
    assert len(fields) == 5
    assert fields[2] == "*"
    assert fields[3] == "*"
    assert re.fullmatch(r"[0-6]", fields[4])
    assert "workflow_dispatch" in triggers


def test_verify_every_action_is_pinned_to_a_full_commit_sha() -> None:
    doc = _verify_doc()
    references = [
        step["uses"]
        for job in _jobs(doc).values()
        for step in job["steps"]
        if "uses" in step
    ]
    assert len(references) >= 3
    for reference in references:
        assert PINNED_USES.match(reference), reference
    names = {reference.split("@")[0] for reference in references}
    assert {
        "actions/checkout",
        "astral-sh/setup-uv",
        "aws-actions/configure-aws-credentials",
    } <= names


def test_verify_permissions_are_least_privilege() -> None:
    doc = _verify_doc()
    assert doc["permissions"] == {"contents": "read"}
    assert _job(doc)["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "issues": "write",
    }


def test_verify_steps_run_aoi_live_verify_freshness_in_order() -> None:
    steps = _steps(_verify_doc())
    aws = _index(steps, r"aws-actions/configure-aws-credentials@")
    fetch = _index(steps, r"scripts/fetch_aoi\.py")
    live = _index(steps, LIVE_PATTERN)
    verify = _index(steps, VERIFY_PATTERN)
    freshness = _index(steps, FRESHNESS_PATTERN)
    assert fetch < live < aws < verify < freshness

    for position in (verify, freshness):
        command = steps[position]["run"]
        assert "--output-root" in command
        assert BUCKET_URI in command


def test_verify_aws_credentials_are_assumed_after_live_tests_and_survive_failure() -> (
    None
):
    steps = _steps(_verify_doc())
    aws = steps[_index(steps, r"aws-actions/configure-aws-credentials@")]
    assert _normalised_condition(aws) == "!cancelled()"
    assert "continue-on-error" not in aws


def test_verify_long_steps_have_timeouts_that_fit_inside_the_job_limit() -> None:
    doc = _verify_doc()
    steps = _steps(doc)
    timeouts = []
    for pattern in (
        r"scripts/fetch_aoi\.py",
        LIVE_PATTERN,
        VERIFY_PATTERN,
        FRESHNESS_PATTERN,
    ):
        timeout = steps[_index(steps, pattern)].get("timeout-minutes")
        assert isinstance(timeout, int), pattern
        timeouts.append(timeout)
    job_limit = _job(doc)["timeout-minutes"]
    assert sum(timeouts) <= job_limit - 10
    assert sum(timeouts) < 60


def test_verify_shares_the_pipeline_concurrency_group() -> None:
    verify = _verify_doc()["concurrency"]
    assert verify["group"] == _workflow()["concurrency"]["group"]
    assert verify["cancel-in-progress"] is False


def test_verify_aws_credentials_step_reads_role_and_region_from_variables() -> None:
    steps = _steps(_verify_doc())
    aws_steps = [
        step
        for step in steps
        if str(step.get("uses", "")).startswith(
            "aws-actions/configure-aws-credentials@"
        )
    ]
    assert len(aws_steps) == 1
    assert aws_steps[0]["with"]["role-to-assume"] == "${{ vars.AWS_ROLE_ARN }}"
    assert aws_steps[0]["with"]["aws-region"] == "${{ vars.AWS_REGION }}"


def test_verify_and_freshness_run_after_an_earlier_failure() -> None:
    steps = _steps(_verify_doc())
    for pattern in (VERIFY_PATTERN, FRESHNESS_PATTERN):
        assert _normalised_condition(steps[_index(steps, pattern)]) == "!cancelled()"
    for pattern in (LIVE_PATTERN, VERIFY_PATTERN, FRESHNESS_PATTERN):
        assert "continue-on-error" not in steps[_index(steps, pattern)]


def test_verify_last_step_opens_an_issue_with_the_run_url_on_failure() -> None:
    last = _steps(_verify_doc())[-1]
    assert _normalised_condition(last) == "failure()"
    assert "gh issue create" in last["run"]
    assert "${RUN_URL}" in last["run"] or "$RUN_URL" in last["run"]
    env = last["env"]
    assert env["GH_TOKEN"] == "${{ github.token }}"
    assert env["RUN_URL"] == (
        "${{ github.server_url }}/${{ github.repository }}"
        "/actions/runs/${{ github.run_id }}"
    )


def test_verify_workflow_text_contains_no_secret_literals() -> None:
    text = VERIFY_WORKFLOW.read_text(encoding="utf-8")
    assert not re.search(r"AKIA[0-9A-Z]{16}", text)
    assert not re.search(r"ASIA[0-9A-Z]{16}", text)
    lowered = text.lower()
    for needle in (
        "aws-secret-access-key",
        "aws-access-key-id",
        "aws_secret_access_key",
        "aws_access_key_id",
        "secrets.",
    ):
        assert needle not in lowered, needle


def test_actionlint_accepts_the_verify_workflow() -> None:
    executable = shutil.which("actionlint")
    if executable is None:
        pytest.skip("actionlint not installed")
    result = subprocess.run(
        [executable, str(VERIFY_WORKFLOW)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
