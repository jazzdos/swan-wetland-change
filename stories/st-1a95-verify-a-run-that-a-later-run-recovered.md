---
id: st-1a95
title: Verify a run that a later run recovered
type: bug
priority: P2
depends_on: [st-ca25]
discovered_from: st-ca25
touches: [.github/workflows/pipeline.yml, tests/test_workflows.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-06
---

## Description

st-ca25 makes the next run finish a crashed daily run and write its manifest with recovered_by set. pipeline.yml keys its verify step on the current run's processed count, and verify defaults to the newest daily run with processed scenes. A recovering run that processed nothing skips verify, and one that processed scenes verifies only itself, so verification/<run_id>.json is never written for the recovered run unless someone runs verify --run-id by hand. Out of scope in st-ca25, whose criteria cover change files and the manifest. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 2 lists the missing verification report as part of the loss.

## Acceptance Criteria

- [ ] When the run's manifest lists recovered_runs
- [ ] the daily job runs verify --run-id for each of them
- [ ] A day with processed 0 and no recovered_runs still skips verify
- [ ] A workflow test shows the step that verifies recovered runs and its condition

## Implementation Plan

## Findings (verified in /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-1a95, base bd31fc2)

- `.github/workflows/pipeline.yml` has one job. Steps: fetch AOI, `run` (id `run`), `Read the processed scene count` (id `manifest`, `if: !cancelled()`, writes only `processed` to GITHUB_OUTPUT), `Verify the run` (`!cancelled() && steps.manifest.outputs.processed > 0`), `Build the catalogue...` (`!cancelled()`), `Commit the verification report` (same processed condition as verify).
- `RunManifest.recovered_runs: list[str]` (src/wetland_change/manifest.py:72) is serialised by `asdict` and set at src/wetland_change/pipeline.py:466 to `sorted(unfinished)`. Run ids are `%Y%m%dT%H%M%SZ`, so they are shell-safe.
- `wetland-change verify --run-id <id>` exists (src/wetland_change/cli.py:294). It exits 0 pass, 3 failed check, 4 nothing scored, 5 manifest unreadable, 6 errored reference check. It writes `verification/<run_id>.json` to the store and `docs/research/verification-<run_id>.md` locally (verify/checks.py:42, :117).
- No source change is needed. The story touches only `.github/workflows/pipeline.yml` and `tests/test_workflows.py`. `actionlint` and `jq` are installed locally, so the existing actionlint test runs.
- Existing tests that constrain the change: `test_commit_step_still_runs_when_verify_fails` and `test_verify_and_commit_run_whenever_scenes_were_processed` assert the commit step condition equals `PROCESSED_CONDITION`. `test_steps_run_fetch_run_verify_catalogue_commit_in_order` uses `_index(..., "wetland-change verify")`, which returns the FIRST matching step, so the existing `Verify the run` step must stay before the new one. `test_catalogue_is_built_after_verify...` forbids "processed" in the catalogue condition, which stays `!cancelled()`.

## Design

1. Extend the `manifest` step to also emit `recovered`, a space-separated list of `.recovered_runs` ids (empty string when none, when the manifest is missing or empty, or when jq fails).
2. Add a step `Verify the runs this run recovered` straight after `Verify the run` and before the catalogue step. Its condition is `${{ !cancelled() && steps.manifest.outputs.recovered != '' }}`. It reads the ids from an env var (not interpolated into the script), loops over them, runs `wetland-change verify --output-root s3://${{ vars.OUTPUT_BUCKET }}/ --run-id "$run_id"` for each, keeps going after a failure, and exits with the highest non-zero exit code seen, so the job ends red but every recovered run is attempted.
3. `Verify the run` keeps its exact condition (`processed > 0`). A day with processed 0 and no recovered runs therefore still skips both verify steps. A recovering run that processed nothing still verifies its recovered runs.
4. The commit step condition becomes `!cancelled() && (steps.manifest.outputs.processed > 0 || steps.manifest.outputs.recovered != '')`. Without this, a zero-processed recovering day would write `docs/research/verification-<recovered id>.md` on the runner and never commit it. The step already no-ops when `git diff --cached` is empty.
5. Update the header comment in pipeline.yml (flat prose, no em dashes) to say recovered runs are verified and committed.

## Tests (tests/test_workflows.py, written first, red before the YAML change)

- `test_manifest_step_emits_the_recovered_run_ids`: the manifest step script writes `recovered=` to GITHUB_OUTPUT and reads `.recovered_runs`.
- `test_recovered_runs_step_verifies_each_recovered_run_by_id` (the story's test): exactly one step other than `Verify the run` runs `wetland-change verify`. It sits after the manifest step and after the `Verify the run` step, and before the catalogue step. Its normalised condition equals `RECOVERED_CONDITION` (`!cancelled() && steps.manifest.outputs.recovered != ''`). Its run text has `--run-id`, `--output-root` and `BUCKET_URI`, and it loops. It has no `continue-on-error` and no `steps.verify`, `success()` or `failure()` in its condition.
- `test_verify_step_still_skips_a_day_with_nothing_processed`: the original `Verify the run` condition is exactly `PROCESSED_CONDITION` and does not mention `recovered`.
- `test_commit_step_runs_for_processed_or_recovered_days`: commit condition equals `COMMIT_CONDITION`. Update `test_commit_step_still_runs_when_verify_fails` and `test_verify_and_commit_run_whenever_scenes_were_processed` accordingly (verify keeps `PROCESSED_CONDITION`, commit uses `COMMIT_CONDITION`, the recovered step uses `RECOVERED_CONDITION`).
- `test_manifest_step_script_reports_recovered_runs` (skips if jq or bash is missing): run the manifest step's script under bash with a temp `RUNNER_TEMP` and `GITHUB_OUTPUT`. Cases: no manifest gives processed=0 and recovered empty; manifest with processed 0 and no recovered_runs gives processed=0 and recovered empty; manifest with processed 0 and `recovered_runs` of two ids gives recovered `idA idB`; a manifest without the key gives recovered empty. This proves that processed 0 and nothing recovered keeps both verify steps off, and that recovered ids alone switch the new step on.
- `test_recovered_step_script_runs_verify_for_every_id_and_keeps_the_worst_exit` (skips if bash is missing): substitute `${{ vars.OUTPUT_BUCKET }}` with a dummy bucket in the step script, put a fake `uv` on PATH that appends its arguments to a log file and exits 3 for one id and 0 for the others, run the script with `RECOVERED_RUNS="a b c"` under `bash -e`, assert verify was invoked three times with `--run-id` for each id in order and the script exit code is 3.
- Existing `test_actionlint_accepts_the_workflow` covers the YAML syntax and expressions.

## Gates (one per line, judged by exit code)

uv run ruff check src tests scripts; uv run ruff format --check src tests scripts; uv run mypy src scripts; uv run pytest -q; GITHUB_ACTIONS=true uv run pytest -q. No live tests, no AWS, nothing committed, stories/** untouched.
## Orchestrator amendments

- Commit nothing; the orchestrator commits the story branch after the review gate.
- Put notes in the summary rather than setting needsHumanInput unless actually blocked.
- Never edit stories/** or .agents/shousper-stories/local/**. Never call AWS and never run terraform. No live tests (-m live).
- Judge pytest by exit code and never clear addopts; use -o addopts="-m 'not live'" only for a count. Also run GITHUB_ACTIONS=true uv run pytest -q.
- Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data.
- Exit 4 from a recovered run is not a failure. `verify` exits 4 when nothing was scored (src/wetland_change/cli.py:351-353). A crashed run can be recovered from ledger rows that are all rejected or failed, so its manifest has processed 0 and verify scores nothing. The daily path already skips verify when processed is 0, so the recovered-runs step must treat exit 4 the same way: log "nothing to verify for recovered run <id>" and leave the step status unchanged. Any other non-zero code (2, 3, 5, 6) still counts, and the step exits with the highest such code. Say this in the step comment. Add a case to the fake-uv script test: one id exits 4 and the others exit 0, and the script exits 0 with all ids attempted. Keep the case where a middle id exits 3 and the script exits 3.
- Prose in docs and comments: flat and factual, no em dashes.

## Implementation Notes

- 2026-11-06T00:38:30.840Z: Committed on story/st-1a95. pipeline.yml: manifest step emits recovered; new step 'Verify the runs this run recovered' (if !cancelled() && recovered != '') runs verify --run-id per id, exits with the highest failing code, treats exit 4 as nothing to verify; commit step condition is processed > 0 || recovered != ''. tests/test_workflows.py covers the conditions and runs the real step scripts under bash with a fake uv. Gates: ruff check, ruff format --check, mypy, pytest -q, GITHUB_ACTIONS=true pytest -q and actionlint all exit 0; 748 passed, 9 deselected.

## Questions
