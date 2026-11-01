"""Offline structural checks for the daily pipeline workflow.

No GitHub repository exists to run the workflow, so these tests read
`.github/workflows/pipeline.yml` and assert the properties that matter:
the schedule, pinned actions, least-privilege permissions, step order, the
commit step surviving a failed verify, OIDC role assumption and no secrets.
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

BUCKET_URI: Final = "s3://${{ vars.OUTPUT_BUCKET }}"
PINNED_USES: Final = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
RUN_PATTERN: Final = r"wetland-change run --output-root s3://"


def _workflow() -> dict[Any, Any]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
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


def test_steps_run_fetch_run_catalogue_verify_commit_in_order() -> None:
    steps = _steps(_workflow())
    fetch = _index(steps, r"scripts/fetch_aoi\.py")
    run = _index(steps, RUN_PATTERN)
    catalogue = _index(steps, r"wetland-change build-catalogue")
    verify = _index(steps, r"wetland-change verify")
    commit = _index(steps, r"git commit")
    assert fetch < run < catalogue < verify < commit

    for position in (run, catalogue, verify):
        command = steps[position]["run"]
        assert "--output-root" in command
        assert BUCKET_URI in command


def test_commit_step_still_runs_when_verify_fails() -> None:
    steps = _steps(_workflow())
    run = _index(steps, RUN_PATTERN)
    verify = _index(steps, r"wetland-change verify")
    commit = _index(steps, r"git commit")

    condition = _normalised_condition(steps[commit])
    assert "steps.manifest.outputs.processed > 0" in condition
    assert "!cancelled()" in condition or "always()" in condition
    assert "success()" not in condition

    assert "continue-on-error" not in steps[verify]

    manifest = [
        position for position, step in enumerate(steps) if step.get("id") == "manifest"
    ]
    assert len(manifest) == 1
    assert run < manifest[0] < verify
    assert "GITHUB_OUTPUT" in steps[manifest[0]]["run"]
    assert "processed" in steps[manifest[0]]["run"]


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
