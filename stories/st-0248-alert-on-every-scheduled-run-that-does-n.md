---
id: st-0248
title: Alert on every scheduled run that does not succeed
type: chore
epic: st-f849
priority: P3
depends_on: []
touches: [.github/workflows/alert.yml, .github/workflows/pipeline.yml, .github/workflows/verify.yml, README.md, tests/test_workflows.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

The verify issue step uses if failure(), which does not fire on a job timeout, a cancelled pending run or a lost runner. The daily pipeline has no issue step. Each failing week opens a new issue, and both crons fire at minute 0. Verdict PLAUSIBLE: GitHub's classification of timeouts and cancellations was not checked. Evidence: docs/research/2026-11-04-milestone-2-review.md L7.

## Acceptance Criteria

- [ ] A cancelled or timed-out scheduled run of either workflow produces an alert
- [ ] A repeated failure comments on the open failure issue instead of opening a new one
- [ ] Both cron schedules use a minute other than zero

## Implementation Plan

# st-0248 plan: alert on every scheduled run that does not succeed

Verified in the worktree `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-0248` (HEAD a365acb). Pointers are accurate: `verify.yml` has the only issue step (last step, `if: failure()`, `gh issue create`, title "Weekly verify failed (run ${GITHUB_RUN_ID})", job permission `issues: write`); `pipeline.yml` has no issue step; crons are `"0 10 * * *"` (pipeline.yml:29) and `"0 22 * * 0"` (verify.yml:36). `tests/test_workflows.py` pins the daily cron literally (`test_schedule_is_daily_with_manual_dispatch`) and asserts the verify issue step (`test_verify_last_step_opens_an_issue_with_the_run_url_on_failure`, `test_verify_permissions_are_least_privilege`). `actionlint` and `jq` are installed locally. The README mentions the times at README.md:92 and :99-101 and :144.

## Design

An in-job issue step cannot satisfy the criteria: `failure()` does not fire on job timeout or cancellation, and a pending run cancelled by the shared `pipeline` concurrency group never starts a job, so nothing inside the workflow can report it. The alert therefore moves to a separate workflow, `.github/workflows/alert.yml`, triggered by `workflow_run` (types `completed`, workflows `pipeline` and `verify`). That event fires for any conclusion (failure, cancelled, timed_out, startup_failure). The alert job runs only when `workflow_run.event == 'schedule'` and `conclusion != 'success'`. It lists open issues, finds one with the exact title `<workflow name> workflow did not succeed`, and comments on it; if none exists it creates it. The verify issue step and the `issues: write` permission on the verify job are removed so there is a single alert path and no duplicate issues. Manual `workflow_dispatch` failures no longer open an issue (the person who dispatched sees them).

Residual uncertainty (stated in the workflow header): whether GitHub emits `workflow_run` for a concurrency-cancelled pending run is not verifiable offline.

Issue lookup uses `gh issue list --state open --json number,title` piped to `jq`, not `--search`, because search indexing lags and would let a quick repeat open a duplicate. The alert workflow has its own concurrency group `alert` (cancel-in-progress false) so two alerts for the same title cannot race.

Only `workflow_run` fields that GitHub controls (`name`, `conclusion`, `html_url`, `id`) are used, passed through `env:`, never interpolated into the script.

## Steps

1. Batch 1 (cron minutes). Edit `.github/workflows/pipeline.yml` cron to `"17 10 * * *"` and `.github/workflows/verify.yml` cron to `"43 22 * * 0"`; update the header comments ("10:17 UTC", "22:43 UTC every Sunday", still clear of the pipeline). Update README.md lines 92 and 99 to 10:17 and 22:43 UTC. In `tests/test_workflows.py` change the pipeline schedule assertion to `[{"cron": "17 10 * * *"}]` and add `test_both_crons_avoid_minute_zero` that reads both workflows and asserts the minute field is a digit string other than `"0"`. Proves: AC 3.
2. Batch 2 (alert workflow). Create `.github/workflows/alert.yml` as described; remove the issue step and `issues: write` from `verify.yml` and reword its timeout header comment (step timeouts stay; the job-level-timeout caveat now points at alert.yml); add a note in `pipeline.yml` header that alert.yml reports its failures. Update `tests/test_workflows.py`: replace the verify issue-step test with `test_verify_has_no_issue_step`, change `test_verify_permissions_are_least_privilege` to job permissions `{contents: read, id-token: write}`, add alert workflow structural tests (below) and `actionlint` on alert.yml. Update README "Scheduled jobs" (verify.yml no longer "opens a GitHub issue"; add an `alert.yml` bullet) and the table cell at README.md:144 ("issue step in verify.yml" becomes "alert in `.github/workflows/alert.yml`").

## Tests and what they prove

- `test_schedule_is_daily_with_manual_dispatch` (updated) and `test_both_crons_avoid_minute_zero`: AC 3.
- `test_alert_triggers_on_completed_runs_of_both_workflows`: `on.workflow_run.types == ["completed"]` and `workflows == ["pipeline", "verify"]`, matching the `name:` of each workflow file (read from the YAML so a rename breaks the test).
- `test_alert_job_fires_on_schedule_runs_that_did_not_succeed`: the job `if` contains `github.event.workflow_run.event == 'schedule'` and `github.event.workflow_run.conclusion != 'success'` and does not use `failure()`. Proves cancelled and timed-out runs are alerted (AC 1).
- `test_alert_permissions_and_pins`: workflow `permissions` is `{}` or read-only, job permissions exactly `{contents: read, issues: write}`, any `uses` pinned to a full SHA, no secret literals, no `workflow_run.head_branch`/`head_commit`/`display_title` interpolation in `run` text.
- `test_alert_script_opens_an_issue_when_none_is_open` and `test_alert_script_comments_when_an_issue_is_open`: extract the `run` script from alert.yml, execute it with `bash` and a fake `gh` on PATH (a shell stub that logs its argv to a file and prints canned JSON for `issue list`), with env WORKFLOW_NAME, CONCLUSION, RUN_URL. Case A (empty list or non-matching title): exactly one `issue create` with the expected title containing the workflow name, no `issue comment`. Case B (open issue with matching title, number 7, plus an unrelated open issue): one `issue comment 7` whose body contains the run URL and conclusion, no `issue create`. Case C: a matching title on a different workflow name does not suppress creation. Proves AC 2 (skip when `jq` missing).
- `test_verify_has_no_issue_step`: no step in verify.yml mentions `gh issue`.
- `test_actionlint_accepts_the_alert_workflow`: actionlint exit 0 (skips if not installed).
- Existing tests for verify step order/timeouts/conditions stay green unchanged.

## Verification

Run in order: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. Also `actionlint .github/workflows/*.yml`. If the README claims are covered by `tests/test_readme.py`, keep it green.

## Orchestrator amendments

Batches are sequential, `[[b1-cron],[b2-alert]]`, because both edit the same files and b2 assumes b1 is done.

GitHub's docs, read 2026-11-05: `workflow_run` "is triggered regardless of the conclusion of the previous workflow" and "will only trigger a workflow run if the workflow file exists on the default branch". `failure()` is "true when any previous step of a job fails", and the page does not mention job timeouts. The start of every hour is a documented high load time for `schedule`. So the design does not rest on how `failure()` treats a job timeout, and comments must not state that as fact.

Consequences to report:

- Manual dispatch failures no longer open an issue, a change from today's verify step.
- alert.yml cannot fire until it is on the default branch, so nothing alerts until a push Jarrod asks for.
- Whether GitHub emits `workflow_run` for a concurrency-cancelled pending run is not documented and needs a live check after the push.
- If alert.yml itself fails there is no alert.
- `conclusion != 'success'` stays: neither workflow has a job-level `if`, so a skipped conclusion does not arise normally.

No pipeline or verify run exists on GitHub yet and the repo has no issues, so no existing issue title needs migrating.

## Implementation Notes

- 2026-11-05T14:57:05.317Z: Build-flow done, batches reviewed clean. Gates exit 0 at the branch head: ruff check, ruff format, mypy, pytest, pytest with GITHUB_ACTIONS=true, actionlint. Reported to Jarrod: manual dispatch failures no longer open an issue. alert.yml cannot fire until it is on the default branch, so nothing alerts until a push he asks for. Needs a live check after that push: whether GitHub emits workflow_run for a pending run cancelled by concurrency, which its docs do not state. A failure of alert.yml itself raises no alert. Design doc lines 128, 233 and 325 left as dated text. Offline tests run the alert script against a fake gh; the real gh and event payload are unexercised until a scheduled run does not succeed.

## Questions
