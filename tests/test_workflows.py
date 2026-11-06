"""Offline checks for the daily pipeline, weekly verify and alert workflows.

No GitHub repository exists to run the workflows, so these tests read
`.github/workflows/pipeline.yml`, `.github/workflows/verify.yml` and
`.github/workflows/alert.yml` and assert the properties that matter: the
schedule, pinned actions, least-privilege permissions, step order, the commit
step surviving a failed verify, OIDC role assumption and no secrets. The alert
workflow is checked for its `workflow_run` trigger on both workflows, its
condition (scheduled runs that did not succeed), and its script, which runs
against a fake `gh` to prove it opens one issue or comments on the open one.
"""

from __future__ import annotations

import os
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
ALERT_WORKFLOW: Final = REPO / ".github" / "workflows" / "alert.yml"

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
    assert triggers["schedule"] == [{"cron": "17 10 * * *"}]
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
CATALOGUE_CONDITION: Final = "!cancelled()"
RECOVERED_CONDITION: Final = "!cancelled() && steps.manifest.outputs.recovered != ''"
COMMIT_CONDITION: Final = (
    "!cancelled() && (steps.manifest.outputs.processed > 0 "
    "|| steps.manifest.outputs.recovered != '')"
)


def test_commit_step_still_runs_when_verify_fails() -> None:
    steps = _steps(_workflow())
    verify = _index(steps, r"wetland-change verify")
    commit = _index(steps, r"git commit")

    condition = _normalised_condition(steps[commit])
    assert condition == COMMIT_CONDITION
    for forbidden in ("steps.verify", "success()", "failure()"):
        assert forbidden not in condition

    assert "continue-on-error" not in steps[verify]


def test_catalogue_is_built_after_verify_and_survives_a_failed_verify() -> None:
    steps = _steps(_workflow())
    verify = _index(steps, r"wetland-change verify")
    catalogue = _index(steps, r"wetland-change build-catalogue")
    assert verify < catalogue

    condition = _normalised_condition(steps[catalogue])
    assert condition == CATALOGUE_CONDITION
    for forbidden in ("steps.verify", "success()", "failure()", "processed"):
        assert forbidden not in condition
    assert "continue-on-error" not in steps[catalogue]


def test_run_step_skips_the_catalogue_and_keeps_its_redirect() -> None:
    steps = _steps(_workflow())
    command = " ".join(str(steps[_index(steps, RUN_PATTERN)]["run"]).split())
    assert "--no-catalogue" in command
    assert command.index("--output-root") < command.index("--no-catalogue")
    assert re.search(r'--no-catalogue > "\$RUNNER_TEMP/run-manifest\.json"$', command)


def test_exactly_one_step_builds_the_catalogue() -> None:
    steps = _steps(_workflow())
    builders = [step for step in steps if "build-catalogue" in str(step.get("run", ""))]
    assert len(builders) == 1


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


def test_verify_and_commit_run_whenever_scenes_were_processed() -> None:
    steps = _steps(_workflow())
    manifest = next(
        position for position, step in enumerate(steps) if step.get("id") == "manifest"
    )
    for pattern, expected in (
        (r"wetland-change verify", PROCESSED_CONDITION),
        (r"git commit", COMMIT_CONDITION),
    ):
        position = _index(steps, pattern)
        assert position > manifest
        assert _normalised_condition(steps[position]) == expected


RECOVERED_STEP_NAME: Final = "Verify the runs this run recovered"
RECOVERED_IDS: Final = "20261101T101700Z 20261102T101700Z 20261103T101700Z"


def _manifest_step(steps: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [step for step in steps if step.get("id") == "manifest"]
    assert len(matches) == 1
    return matches[0]


def _verify_step_positions(steps: list[dict[str, Any]]) -> list[int]:
    return [
        position
        for position, step in enumerate(steps)
        if "wetland-change verify" in str(step.get("run", ""))
    ]


def _recovered_step(steps: list[dict[str, Any]]) -> dict[str, Any]:
    positions = _verify_step_positions(steps)
    assert len(positions) == 2
    return steps[positions[1]]


def test_manifest_step_emits_the_recovered_run_ids() -> None:
    script = str(_manifest_step(_steps(_workflow()))["run"])
    assert "recovered_runs" in script
    assert re.search(r'echo "recovered=.*>> "\$GITHUB_OUTPUT"', script)


def test_recovered_runs_step_verifies_each_recovered_run_by_id() -> None:
    steps = _steps(_workflow())
    positions = _verify_step_positions(steps)
    assert len(positions) == 2
    first, second = positions
    manifest = next(i for i, step in enumerate(steps) if step.get("id") == "manifest")
    catalogue = _index(steps, r"wetland-change build-catalogue")
    assert manifest < first < second < catalogue

    step = steps[second]
    assert step["name"] == RECOVERED_STEP_NAME
    condition = _normalised_condition(step)
    assert condition == RECOVERED_CONDITION
    for forbidden in ("steps.verify", "success()", "failure()"):
        assert forbidden not in condition
    assert "continue-on-error" not in step

    assert step["env"] == {"RECOVERED_RUNS": "${{ steps.manifest.outputs.recovered }}"}

    script = str(step["run"])
    assert "--run-id" in script
    assert "--output-root" in script
    assert BUCKET_URI in script
    assert re.search(r"\bfor \w+ in \$RECOVERED_RUNS\b", script)
    assert '"${RECOVERED_RUNS:?' in script


def test_verify_step_still_skips_a_day_with_nothing_processed() -> None:
    steps = _steps(_workflow())
    first = steps[_verify_step_positions(steps)[0]]
    condition = _normalised_condition(first)
    assert condition == PROCESSED_CONDITION
    assert "recovered" not in condition


@pytest.mark.parametrize(
    ("manifest", "processed", "recovered"),
    [
        (None, "0", ""),
        ('{"processed":0}', "0", ""),
        (
            '{"processed":0,"recovered_runs":["20261101T101700Z","20261102T101700Z"]}',
            "0",
            "20261101T101700Z 20261102T101700Z",
        ),
        ('{"processed":3,"recovered_runs":[]}', "3", ""),
    ],
)
def test_manifest_step_script_reports_recovered_runs(
    tmp_path: Path, manifest: str | None, processed: str, recovered: str
) -> None:
    bash = shutil.which("bash")
    if bash is None or shutil.which("jq") is None:
        pytest.skip("bash and jq are required")
    script = str(_manifest_step(_steps(_workflow()))["run"])
    if manifest is not None:
        (tmp_path / "run-manifest.json").write_text(manifest, encoding="utf-8")
    output = tmp_path / "out"
    output.write_text("", encoding="utf-8")
    env = {
        "PATH": os.environ["PATH"],
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
    }
    result = subprocess.run(
        [bash, "-e", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    values = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert values == {"processed": processed, "recovered": recovered}


def _run_recovered_script(
    tmp_path: Path, exit_codes: dict[str, int]
) -> tuple[int, list[str]]:
    """Run the recovered-runs script against a fake `uv`; return code and calls."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required")
    script = str(_recovered_step(_steps(_workflow()))["run"]).replace(
        "${{ vars.OUTPUT_BUCKET }}", "bucket"
    )
    assert "${{" not in script
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "uv.log"
    log.write_text("", encoding="utf-8")
    cases = "".join(
        f'  *"{run_id}"*) exit {code} ;;\n' for run_id, code in exit_codes.items()
    )
    fake = bindir / "uv"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'line="$*"\n'
        'printf \'%s\\n\' "$line" >> "$UV_LOG"\n'
        'case "$line" in\n' + cases + "  *) exit 0 ;;\nesac\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "UV_LOG": str(log),
        "RECOVERED_RUNS": RECOVERED_IDS,
    }
    result = subprocess.run(
        [bash, "-e", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
    return result.returncode, calls


def _assert_every_id_was_verified(calls: list[str]) -> None:
    ids = RECOVERED_IDS.split()
    assert len(calls) == len(ids)
    for call, run_id in zip(calls, ids, strict=True):
        assert "verify" in call
        assert f"--run-id {run_id}" in call
        assert "--output-root s3://bucket/" in call


def test_recovered_step_script_runs_verify_for_every_id_and_keeps_the_worst_exit(
    tmp_path: Path,
) -> None:
    code, calls = _run_recovered_script(tmp_path, {"20261102T101700Z": 3})
    _assert_every_id_was_verified(calls)
    assert code == 3


def test_recovered_step_script_exits_with_the_highest_failing_code(
    tmp_path: Path,
) -> None:
    code, calls = _run_recovered_script(
        tmp_path, {"20261101T101700Z": 6, "20261102T101700Z": 3}
    )
    _assert_every_id_was_verified(calls)
    assert code == 6


def test_recovered_step_script_treats_nothing_scored_as_not_a_failure(
    tmp_path: Path,
) -> None:
    code, calls = _run_recovered_script(tmp_path, {"20261102T101700Z": 4})
    _assert_every_id_was_verified(calls)
    assert code == 0


def test_recovered_step_script_still_fails_on_a_real_error_beside_nothing_scored(
    tmp_path: Path,
) -> None:
    code, calls = _run_recovered_script(
        tmp_path, {"20261101T101700Z": 4, "20261103T101700Z": 5}
    )
    _assert_every_id_was_verified(calls)
    assert code == 5


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


def test_both_crons_avoid_minute_zero() -> None:
    for doc in (_workflow(), _verify_doc()):
        triggers = doc.get("on", doc.get(True))
        minute = triggers["schedule"][0]["cron"].split()[0]
        assert re.fullmatch(r"[1-9]\d?", minute), minute
        assert 1 <= int(minute) <= 59


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


def test_verify_has_no_issue_step() -> None:
    for step in _steps(_verify_doc()):
        assert "gh issue" not in str(step.get("run", ""))


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


# --- alert workflow ---------------------------------------------------------

SECRET_NEEDLES: Final = (
    "aws-secret-access-key",
    "aws-access-key-id",
    "aws_secret_access_key",
    "aws_access_key_id",
    "secrets.",
)


def _alert_doc() -> dict[Any, Any]:
    return _workflow(ALERT_WORKFLOW)


def _alert_script() -> str:
    steps = _steps(_alert_doc())
    assert len(steps) == 1
    return str(steps[0]["run"])


def test_alert_triggers_on_completed_runs_of_both_workflows() -> None:
    doc = _alert_doc()
    triggers = doc.get("on", doc.get(True))
    assert list(triggers) == ["workflow_run"]
    run = triggers["workflow_run"]
    assert run["types"] == ["completed"]
    assert run["workflows"] == [
        _workflow(WORKFLOW)["name"],
        _workflow(VERIFY_WORKFLOW)["name"],
    ]


ALERT_CONDITION: Final = (
    "github.event.workflow_run.event == 'schedule' "
    "&& github.event.workflow_run.conclusion != 'success'"
)


def test_alert_job_fires_on_schedule_runs_that_did_not_succeed() -> None:
    assert _normalised_condition(_job(_alert_doc())) == ALERT_CONDITION


def test_alert_step_env_reads_the_finished_run_not_this_run() -> None:
    steps = _steps(_alert_doc())
    assert len(steps) == 1
    assert steps[0]["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GH_REPO": "${{ github.repository }}",
        "WORKFLOW_NAME": "${{ github.event.workflow_run.name }}",
        "CONCLUSION": "${{ github.event.workflow_run.conclusion }}",
        "RUN_URL": "${{ github.event.workflow_run.html_url }}",
    }


def test_alert_permissions_pins_and_inputs() -> None:
    doc = _alert_doc()
    assert doc["permissions"] == {"contents": "read"}
    assert doc["concurrency"] == {"group": "alert", "cancel-in-progress": False}
    job = _job(doc)
    assert job["permissions"] == {"contents": "read", "issues": "write"}
    assert job["runs-on"] == "ubuntu-24.04"
    for step in _steps(doc):
        if "uses" in step:
            assert PINNED_USES.match(step["uses"]), step["uses"]

    text = ALERT_WORKFLOW.read_text(encoding="utf-8")
    assert not re.search(r"AKIA[0-9A-Z]{16}", text)
    assert not re.search(r"ASIA[0-9A-Z]{16}", text)
    lowered = text.lower()
    for needle in SECRET_NEEDLES:
        assert needle not in lowered, needle
    for field in ("head_branch", "head_commit", "display_title"):
        assert field not in text, field

    assert "${{" not in _alert_script()


TITLE_VERIFY: Final = "verify workflow did not succeed"


def _run_alert_script(tmp_path: Path, listing: str) -> list[str]:
    """Run the alert script against a fake `gh`; return the logged calls."""
    bash = shutil.which("bash")
    if bash is None or shutil.which("jq") is None:
        pytest.skip("bash and jq are required")
    log = tmp_path / "gh.log"
    log.write_text("", encoding="utf-8")
    fake = tmp_path / "gh"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$GH_LOG"\n'
        'if [ "$1 $2" = "issue list" ]; then printf \'%s\' "$GH_LIST_JSON"; fi\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "GH_LOG": str(log),
        "GH_LIST_JSON": listing,
        "WORKFLOW_NAME": "verify",
        "CONCLUSION": "timed_out",
        "RUN_URL": "https://example.test/run/1",
    }
    result = subprocess.run(
        [bash, "-c", _alert_script()],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line]


def _write_calls(calls: list[str]) -> list[str]:
    return [call for call in calls if not call.startswith("issue list")]


def test_alert_script_opens_an_issue_when_none_is_open(tmp_path: Path) -> None:
    writes = _write_calls(_run_alert_script(tmp_path, "[]"))
    assert len(writes) == 1
    assert writes[0].startswith("issue create")
    assert TITLE_VERIFY in writes[0]
    assert "https://example.test/run/1" in writes[0]


def test_alert_script_comments_when_an_issue_is_open(tmp_path: Path) -> None:
    listing = (
        '[{"number":7,"title":"verify workflow did not succeed"},'
        '{"number":9,"title":"something else"}]'
    )
    writes = _write_calls(_run_alert_script(tmp_path, listing))
    assert len(writes) == 1
    assert writes[0].startswith("issue comment 7 ")
    assert "https://example.test/run/1" in writes[0]
    assert "timed_out" in writes[0]


def test_alert_script_ignores_an_issue_for_another_workflow(tmp_path: Path) -> None:
    listing = '[{"number":3,"title":"pipeline workflow did not succeed"}]'
    writes = _write_calls(_run_alert_script(tmp_path, listing))
    assert len(writes) == 1
    assert writes[0].startswith("issue create")
    assert TITLE_VERIFY in writes[0]


def test_actionlint_accepts_the_alert_workflow() -> None:
    executable = shutil.which("actionlint")
    if executable is None:
        pytest.skip("actionlint not installed")
    result = subprocess.run(
        [executable, str(ALERT_WORKFLOW)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
