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

import ast
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
BACKFILL_WORKFLOW: Final = REPO / ".github" / "workflows" / "backfill.yml"
CONFIG: Final = REPO / "config" / "pipeline.toml"
LIVE_ANONYMOUS: Final = REPO / "tests" / "test_live_anonymous_read.py"

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


def _verify_step_timeouts() -> dict[str, int]:
    steps = _steps(_verify_doc())
    timeouts: dict[str, int] = {}
    for name, pattern in (
        ("fetch", r"scripts/fetch_aoi\.py"),
        ("live", LIVE_PATTERN),
        ("verify", VERIFY_PATTERN),
        ("freshness", FRESHNESS_PATTERN),
    ):
        timeout = steps[_index(steps, pattern)].get("timeout-minutes")
        assert isinstance(timeout, int), name
        timeouts[name] = timeout
    return timeouts


def test_verify_long_steps_have_timeouts_that_fit_inside_the_job_limit() -> None:
    timeouts = _verify_step_timeouts()
    job_limit = _job(_verify_doc())["timeout-minutes"]
    assert sum(timeouts.values()) <= job_limit - 10
    # The credential step requests no `role-duration-seconds`, so its session
    # lasts the 1-hour default from minting. Verify and freshness are the
    # steps that use those credentials (the credential step runs after the
    # live tests), so together they must finish inside that hour.
    assert timeouts["verify"] + timeouts["freshness"] < 60


def test_verify_step_timeout_covers_the_measured_verify_runtime() -> None:
    # Pipeline run 43072355326 (2026-11-11, 5 scene-tiles) took 19m34s to
    # verify: 10m17s of per-scene reads (about 2.1 minutes per scene-tile)
    # plus 9m17s of run-level checks. A run with two full passes (up to 12
    # scene-tiles) needs about 12 x 2.1 + 9.3 = 35 minutes, which the 40
    # minute limit covers.
    assert _verify_step_timeouts()["verify"] >= 40


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


# --- backfill workflow ------------------------------------------------------

BACKFILL_COMMANDS: Final = {
    "footers": "add-observation-footers",
    "dea": "add-dea-attribution",
    "copernicus": "add-copernicus-notice",
    "dbca": "add-dbca-attribution",
    "catalogue": "build-catalogue",
}
BACKFILL_ADD_JOBS: Final = ("footers", "dea", "copernicus", "dbca")
BACKFILL_SUMMARY: Final = "scanned 3, rewritten 3, skipped 0, failed 1"


def _backfill_doc() -> dict[Any, Any]:
    return _workflow(BACKFILL_WORKFLOW)


def _backfill_command_step(job_name: str) -> dict[str, Any]:
    command = BACKFILL_COMMANDS[job_name]
    steps = [
        step
        for step in _jobs(_backfill_doc())[job_name]["steps"]
        if f"wetland-change {command}" in str(step.get("run", ""))
    ]
    assert len(steps) == 1, job_name
    return steps[0]


def _uses_pin(doc: dict[Any, Any]) -> dict[str, set[str]]:
    pins: dict[str, set[str]] = {}
    for job in _jobs(doc).values():
        for step in job["steps"]:
            if "uses" in step:
                name, _, sha = str(step["uses"]).partition("@")
                pins.setdefault(name, set()).add(sha)
    return pins


def test_backfill_is_dispatch_only_with_a_boolean_dry_run_defaulting_to_true() -> None:
    triggers = _backfill_doc().get("on", _backfill_doc().get(True))
    assert set(triggers) == {"workflow_dispatch"}
    dry_run = triggers["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry_run["type"] == "boolean"
    assert dry_run["default"] is True
    assert "--dry-run" in dry_run["description"]
    assert "build-catalogue" in dry_run["description"]


def test_backfill_jobs_run_footers_dea_copernicus_dbca_catalogue_in_order() -> None:
    jobs = _jobs(_backfill_doc())
    assert list(jobs) == ["footers", "dea", "copernicus", "dbca", "catalogue"]
    assert "needs" not in jobs["footers"]
    assert jobs["dea"]["needs"] == "footers"
    assert jobs["copernicus"]["needs"] == "dea"
    assert jobs["dbca"]["needs"] == "copernicus"
    assert jobs["catalogue"]["needs"] == "dbca"
    for name in jobs:
        assert jobs[name]["runs-on"] == "ubuntu-24.04"
        _backfill_command_step(name)


def test_backfill_catalogue_is_skipped_on_a_dry_run() -> None:
    jobs = _jobs(_backfill_doc())
    assert _normalised_condition(jobs["catalogue"]) == "!inputs.dry_run"
    for name in BACKFILL_ADD_JOBS:
        assert "if" not in jobs[name]


def test_backfill_permissions_are_least_privilege() -> None:
    doc = _backfill_doc()
    assert doc["permissions"] == {"contents": "read"}
    for name, job in _jobs(doc).items():
        assert job["permissions"] == {"contents": "read", "id-token": "write"}, name


def test_backfill_shares_the_pipeline_concurrency_group() -> None:
    concurrency = _backfill_doc()["concurrency"]
    assert concurrency["group"] == _workflow()["concurrency"]["group"] == "pipeline"
    assert concurrency["cancel-in-progress"] is False


def test_backfill_actions_are_pinned_to_the_pipeline_shas() -> None:
    pipeline = _uses_pin(_workflow())
    backfill = _uses_pin(_backfill_doc())
    assert set(backfill) == {
        "actions/checkout",
        "astral-sh/setup-uv",
        "aws-actions/configure-aws-credentials",
    }
    for name, shas in backfill.items():
        assert shas == pipeline[name], name
    for job in _jobs(_backfill_doc()).values():
        for step in job["steps"]:
            if "uses" in step:
                assert PINNED_USES.match(step["uses"]), step["uses"]
    pipeline_uv = [
        step["with"]
        for step in _steps(_workflow())
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ][0]
    for job in _jobs(_backfill_doc()).values():
        uv = [
            step["with"]
            for step in job["steps"]
            if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
        ][0]
        assert uv == pipeline_uv
        assert any(step.get("run") == "uv sync --locked" for step in job["steps"])


def test_backfill_credentials_come_from_variables_and_last_three_hours() -> None:
    for name, job in _jobs(_backfill_doc()).items():
        aws = [
            step
            for step in job["steps"]
            if str(step.get("uses", "")).startswith(
                "aws-actions/configure-aws-credentials@"
            )
        ]
        assert len(aws) == 1, name
        assert aws[0]["with"]["role-to-assume"] == "${{ vars.AWS_ROLE_ARN }}"
        assert aws[0]["with"]["aws-region"] == "${{ vars.AWS_REGION }}"
        assert int(aws[0]["with"]["role-duration-seconds"]) == 10800


def test_backfill_command_steps_time_out_inside_the_job_limit() -> None:
    for name, job in _jobs(_backfill_doc()).items():
        job_limit = job["timeout-minutes"]
        step_limit = _backfill_command_step(name)["timeout-minutes"]
        assert isinstance(job_limit, int)
        assert isinstance(step_limit, int)
        assert job_limit < 180, name
        assert step_limit < job_limit, name


def test_backfill_command_steps_log_only_the_summary_line() -> None:
    for name, command in BACKFILL_COMMANDS.items():
        script = str(_backfill_command_step(name)["run"])
        assert f'> "$RUNNER_TEMP/{command}.out"' in script, name
        assert f'2> "$RUNNER_TEMP/{command}.err"' in script, name
        assert f'tail -n 1 "$RUNNER_TEMP/{command}.out"' in script, name
        assert "|| status=$?" in script, name
        assert 'exit "$status"' in script, name
        assert f'cat "$RUNNER_TEMP/{command}.out"' not in script, name
        assert '--output-root "s3://${OUTPUT_BUCKET}/"' in script, name
        has_flag = "--dry-run" in script
        assert has_flag == (name in BACKFILL_ADD_JOBS), name


def test_backfill_command_steps_pass_inputs_through_env() -> None:
    for name in BACKFILL_COMMANDS:
        step = _backfill_command_step(name)
        assert step["env"]["OUTPUT_BUCKET"] == "${{ vars.OUTPUT_BUCKET }}"
        if name in BACKFILL_ADD_JOBS:
            assert step["env"]["DRY_RUN"] == "${{ inputs.dry_run }}"


def test_backfill_run_bodies_contain_no_expressions() -> None:
    for job in _jobs(_backfill_doc()).values():
        for step in job["steps"]:
            assert "${{" not in str(step.get("run", "")), step


def test_backfill_workflow_text_contains_no_secret_literals() -> None:
    text = BACKFILL_WORKFLOW.read_text(encoding="utf-8")
    assert not re.search(r"AKIA[0-9A-Z]{16}", text)
    assert not re.search(r"ASIA[0-9A-Z]{16}", text)
    lowered = text.lower()
    for needle in SECRET_NEEDLES:
        assert needle not in lowered, needle


def _run_backfill_step(
    tmp_path: Path, job_name: str, dry_run: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run a command step against a fake `uv` that lists paths and fails."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required")
    script = str(_backfill_command_step(job_name)["run"])
    assert "${{" not in script
    bindir = tmp_path / "bin"
    bindir.mkdir()
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    log = tmp_path / "uv.log"
    fake = bindir / "uv"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$UV_LOG"\n'
        "printf 'observations/a.parquet\\n'\n"
        "printf 'observations/b.parquet\\n'\n"
        "printf 'observations/c.parquet\\n'\n"
        f"printf '%s\\n' '{BACKFILL_SUMMARY}'\n"
        "printf 'observations/d.parquet\\tboom\\n' >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "UV_LOG": str(log),
        "RUNNER_TEMP": str(runner_temp),
        "OUTPUT_BUCKET": "bucket",
        "DRY_RUN": dry_run,
    }
    result = subprocess.run(
        [bash, "-e", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
    return result, calls


@pytest.mark.parametrize("job_name", BACKFILL_ADD_JOBS)
def test_backfill_step_script_prints_the_summary_not_the_paths(
    tmp_path: Path, job_name: str
) -> None:
    result, calls = _run_backfill_step(tmp_path, job_name, "false")
    assert result.returncode == 1
    assert result.stdout.splitlines() == [BACKFILL_SUMMARY]
    assert "boom" in result.stderr
    assert "observations/a.parquet" not in result.stdout + result.stderr
    assert calls == [
        f"run --no-sync wetland-change {BACKFILL_COMMANDS[job_name]}"
        " --output-root s3://bucket/"
    ]


@pytest.mark.parametrize("job_name", BACKFILL_ADD_JOBS)
def test_backfill_step_script_passes_dry_run_only_when_asked(
    tmp_path: Path, job_name: str
) -> None:
    _, calls = _run_backfill_step(tmp_path, job_name, "true")
    assert calls == [
        f"run --no-sync wetland-change {BACKFILL_COMMANDS[job_name]}"
        " --output-root s3://bucket/ --dry-run"
    ]


def test_backfill_catalogue_script_keeps_the_exit_code(tmp_path: Path) -> None:
    result, calls = _run_backfill_step(tmp_path, "catalogue", "false")
    assert result.returncode == 1
    assert result.stdout.splitlines() == [BACKFILL_SUMMARY]
    assert calls == [
        "run --no-sync wetland-change build-catalogue --output-root s3://bucket/"
    ]


def test_actionlint_accepts_the_backfill_workflow() -> None:
    executable = shutil.which("actionlint")
    if executable is None:
        pytest.skip("actionlint not installed")
    result = subprocess.run(
        [executable, str(BACKFILL_WORKFLOW)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_verify_header_comment_names_adr_0017_and_no_public_read() -> None:
    header: list[str] = []
    for line in VERIFY_WORKFLOW.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            break
        header.append(line)
    text = "\n".join(header).lower()
    assert text
    assert "adr 0017" in text
    assert "no longer an expected failure" in text
    assert "xfail" not in text
    assert "2026-11-17" in text
    for phrase in (
        "publicly readable",
        "anonymously readable",
        "readable anonymously",
        "public read",
        "public-read",
    ):
        assert phrase not in text


def test_catalogue_comment_names_adr_0017_and_credentials() -> None:
    lines = CONFIG.read_text(encoding="utf-8").splitlines()
    in_catalogue = False
    comment: list[str] = []
    for line in lines:
        if line.strip() == "[catalogue]":
            in_catalogue = True
            continue
        if not in_catalogue:
            continue
        if line.startswith("#"):
            comment.append(line)
        elif line.startswith("base_url ="):
            break
        else:
            comment = []
    text = "\n".join(comment).lower()
    assert "adr 0017" in text
    assert "credentials" in text
    for phrase in (
        "publicly readable",
        "anonymously readable",
        "readable anonymously",
        "without credentials",
        "is private",
    ):
        assert phrase not in text


def _is_attr(node: ast.expr, *names: str) -> bool:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts)) == list(names)


def test_anonymous_live_test_is_live_and_has_no_xfail_marker() -> None:
    source = LIVE_ANONYMOUS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    marks: list[ast.expr] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            assert isinstance(node.value, ast.List)
            marks = list(node.value.elts)
    assert marks, "no pytestmark list"
    assert any(_is_attr(m, "pytest", "mark", "live") for m in marks)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            assert not _is_attr(node.func, "pytest", "mark", "xfail")
        elif isinstance(node, ast.Attribute):
            assert not _is_attr(node, "pytest", "mark", "xfail")
    assert "xfail" not in source.lower()
    assert source.count("== 403") >= 2
    assert "stac/catalog.json" in source
    assert "prefix=observations/" in source
    assert ".read(" not in source
