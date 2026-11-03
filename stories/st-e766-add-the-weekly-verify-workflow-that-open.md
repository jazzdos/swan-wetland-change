---
id: st-e766
title: Add the weekly verify workflow that opens an issue on failure
type: feature
epic: st-f849
priority: P2
depends_on: [st-2b8a]
touches: [.github/workflows/verify.yml, tests/test_workflows.py]
exclusive: false
created: 2026-10-29
updated: 2026-11-03
---
## Description

Add `.github/workflows/verify.yml` (design, Components): a weekly run of the live contract tests (`pytest -m live`), `wetland-change verify` over the latest run in the S3 root, and `wetland-change freshness`. Any failure opens a GitHub issue (design: "a failing freshness test opens a GitHub issue").

Use the same conventions as `test.yml` and `pipeline.yml`, with an OIDC role for read access. Validate offline only by extending `tests/test_workflows.py`.

## Acceptance Criteria

- [ ] `actionlint .github/workflows/verify.yml` exits 0.
- [ ] `tests/test_workflows.py` asserts a weekly `schedule` cron, `workflow_dispatch`, SHA-pinned `uses:`, and permissions exactly `contents: read`, `id-token: write` and `issues: write`.
- [ ] The job runs `pytest -m live`, `wetland-change verify` and `wetland-change freshness` against `s3://${{ vars.OUTPUT_BUCKET }}`.
- [ ] A step with `if: failure()` runs `gh issue create` with the workflow run URL in the body.

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-e766)

- Dependency st-2b8a is merged: `wetland-change freshness` exists (src/wetland_change/cli.py, exit 3 on a failed check, exit 4 when a check could not run). `wetland-change verify` exists (exit 3 on a failed check, exit 4 when nothing was scored; defaults to the latest run, `--run-id` optional).
- Both commands take `--output-root` and both need the AOI polygons (`_load` raises "run scripts/fetch_aoi.py" otherwise), so the job needs the same `python scripts/fetch_aoi.py` step as pipeline.yml.
- Live tests exist (tests/test_live_verify.py, tests/test_live_waterbodies.py, plus marked tests in test_verify_ndvi.py and test_backfill.py). pyproject has `addopts = "-q -m 'not live'"`; a later `-m live` on the command line overrides it (verify with `--collect-only`).
- `.github/workflows/test.yml` and `pipeline.yml` give the conventions: ubuntu-24.04, SHA-pinned actions with a version comment (checkout 3d3c42e5aac5ba805825da76410c181273ba90b1, setup-uv c771a70e6277c0a99b617c7a806ffedaca235ff9 with uv 0.9.29 / python 3.12 / enable-cache false, configure-aws-credentials e1253824e5c10ff9df46874f81ed3ec929e19cfd with `vars.AWS_ROLE_ARN` / `vars.AWS_REGION`), `uv sync --locked`, `uv run --no-sync`, bucket from `vars.OUTPUT_BUCKET`.
- tests/test_workflows.py currently targets only pipeline.yml via the `WORKFLOW` constant; helpers `_workflow`, `_jobs`, `_job`, `_steps`, `_index`, `_normalised_condition` are hard-wired to it. `actionlint` and `gh` are installed locally (/opt/homebrew/bin).
- Constraints: do not touch .worktrees/st-b983 or /Users/jarrodbaker/Documents/swan-wetland-change-data, never use pkill/pgrep patterns matching wetland-change or the driver, and do not run `-m live` tests locally (validation is offline only).

## Steps

1. Extend tests/test_workflows.py (RED first). Add a `VERIFY_WORKFLOW` constant for `.github/workflows/verify.yml` and make the existing helpers take an optional path argument (default pipeline.yml) so the existing pipeline tests are unchanged. Add tests:
   - `test_verify_schedule_is_weekly_with_manual_dispatch`: exactly one schedule entry, a 5-field cron whose day-of-month and month are `*` and day-of-week is a single digit 0-6 (weekly), and `workflow_dispatch` present. Proves the weekly trigger and manual dispatch.
   - `test_verify_every_action_is_pinned_to_a_full_commit_sha`: every `uses:` matches `PINNED_USES`; checkout, setup-uv and configure-aws-credentials are present. Proves SHA pinning.
   - `test_verify_job_permissions_are_exactly_contents_read_id_token_write_issues_write`: job `permissions == {"contents": "read", "id-token": "write", "issues": "write"}`, and workflow-level `permissions == {"contents": "read"}`. Proves least privilege.
   - `test_verify_job_runs_live_tests_verify_and_freshness_against_the_bucket`: steps contain `pytest ... -m live`, `wetland-change verify` and `wetland-change freshness`; the verify and freshness commands contain `--output-root` and `s3://${{ vars.OUTPUT_BUCKET }}`; the AWS credentials step precedes them and reads role and region from `vars.AWS_ROLE_ARN` / `vars.AWS_REGION`; the fetch_aoi step precedes verify. Proves the three checks run on the S3 root.
   - `test_verify_checks_all_run_even_after_an_earlier_one_fails`: the verify and freshness steps have `if` equal to `!cancelled()` (after normalising `${{ }}`), and none of the three check steps has `continue-on-error`. Proves one failing check does not hide the others and the job still ends red.
   - `test_verify_failure_step_opens_an_issue_with_the_run_url`: the last step has `if` normalising to `failure()`, its `run` contains `gh issue create`, the body references the run URL (via an env var built from `github.server_url`, `github.repository` and `github.run_id`, or inline), and `GH_TOKEN` is set from `github.token`. Proves the failure issue carries the run link.
   - `test_verify_workflow_text_contains_no_secret_literals`: same needles as the pipeline test (`secrets.` is banned, so use `github.token`, not a secret).
   - `test_actionlint_accepts_the_verify_workflow`: same as the pipeline actionlint test but for verify.yml, skipping when actionlint is missing.
   Run `uv run pytest -q tests/test_workflows.py` and confirm the new tests fail only because verify.yml is missing.
2. Create .github/workflows/verify.yml (GREEN). Header comment explaining: weekly live contract run plus verification of the latest run plus freshness; a failure opens an issue; OIDC trust is limited to refs/heads/main so dispatch only works from main; the issue step is the alert path that complements the daily commit keeping the schedule alive. Content:
   - `name: verify`
   - `on: schedule: - cron: "0 22 * * 0"` (Sunday 22:00 UTC, clear of the 10:00 UTC daily pipeline which can run up to 120 minutes) and `workflow_dispatch:`
   - top-level `permissions: contents: read`; `concurrency: {group: verify, cancel-in-progress: false}`
   - one job `verify`, name `live contract, verify, freshness`, `runs-on: ubuntu-24.04`, `timeout-minutes: 60`, job `permissions: {contents: read, id-token: write, issues: write}`.
   - Steps in order: checkout (pinned, with version comment); setup-uv (pinned, same `with` as pipeline.yml); `uv sync --locked`; assume AWS role through OIDC (pinned, `id: aws`, role-to-assume `${{ vars.AWS_ROLE_ARN }}`, aws-region `${{ vars.AWS_REGION }}`); `uv run --no-sync python scripts/fetch_aoi.py`; `Live contract tests` running `uv run --no-sync pytest -m live -rs`; `Verify the latest run` with `if: ${{ !cancelled() }}` running `uv run --no-sync wetland-change verify --output-root s3://${{ vars.OUTPUT_BUCKET }}/` (YAML folded `>-` like pipeline.yml); `Check freshness` with `if: ${{ !cancelled() }}` running `uv run --no-sync wetland-change freshness --output-root s3://${{ vars.OUTPUT_BUCKET }}/`; final step `Open an issue on failure` with `if: failure()`, `env: {GH_TOKEN: ${{ github.token }}, GH_REPO: ${{ github.repository }}, RUN_URL: "${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"}` and `run: gh issue create --title "Weekly verify failed (run ${GITHUB_RUN_ID})" --body "The weekly verify workflow failed. Run: ${RUN_URL}"` (no `--label`, since a missing label makes `gh issue create` fail).
   Run `uv run pytest -q tests/test_workflows.py` (all green) and `actionlint .github/workflows/verify.yml` (exit 0).
3. Offline verification battery in order, one command per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. Also `uv run pytest --collect-only -q -m live | tail -3` to confirm `-m live` overrides the `not live` addopts (collects the live tests, not zero). Do not run the live tests.
4. Commit on the story branch with message `st-e766: add the weekly verify workflow that opens an issue on failure`, ending with the Co-Authored-By trailer given by the harness.

## Implementation Notes

- 2026-11-03T14:52:13.050Z: touches-expansion: overlaps st-56b8 (LEARNINGS.md, data/SOURCES.md, docs/research/2026-11-02-backfill-analysis.py, docs/research/2026-11-02-backfill-driver-test.sh, docs/research/2026-11-02-backfill-driver.sh, docs/research/2026-11-02-backfill-fake-cli, docs/research/2026-11-03-backfill-changes.csv, docs/research/2026-11-03-backfill-evidence.json, docs/research/2026-11-03-backfill-hypotheses.md, docs/research/2026-11-03-backfill-scores.csv, scripts/fetch_aoi.py, src/wetland_change/cli.py, src/wetland_change/verify/waterbodies.py, stories/st-1d45-milestone-2-remaining-verification-matri.md, stories/st-56b8-make-the-dea-waterbodies-checksum-stable.md, stories/st-779a-align-the-now-help-text-with-how-a-value.md, stories/st-b983-run-the-collection-1-backfill-and-score.md, stories/st-e2ae-deduplicate-dea-waterbodies-pairing-rows.md, stories/st-e766-add-the-weekly-verify-workflow-that-open.md, tests/test_cli.py, tests/test_fetch_aoi.py, tests/test_verify_waterbodies.py) — coordinate or split
- 2026-11-03T14:52:13.052Z: touches-expansion: overlaps st-779a (LEARNINGS.md, data/SOURCES.md, docs/research/2026-11-02-backfill-analysis.py, docs/research/2026-11-02-backfill-driver-test.sh, docs/research/2026-11-02-backfill-driver.sh, docs/research/2026-11-02-backfill-fake-cli, docs/research/2026-11-03-backfill-changes.csv, docs/research/2026-11-03-backfill-evidence.json, docs/research/2026-11-03-backfill-hypotheses.md, docs/research/2026-11-03-backfill-scores.csv, scripts/fetch_aoi.py, src/wetland_change/cli.py, src/wetland_change/verify/waterbodies.py, stories/st-1d45-milestone-2-remaining-verification-matri.md, stories/st-56b8-make-the-dea-waterbodies-checksum-stable.md, stories/st-779a-align-the-now-help-text-with-how-a-value.md, stories/st-b983-run-the-collection-1-backfill-and-score.md, stories/st-e2ae-deduplicate-dea-waterbodies-pairing-rows.md, stories/st-e766-add-the-weekly-verify-workflow-that-open.md, tests/test_cli.py, tests/test_fetch_aoi.py, tests/test_verify_waterbodies.py) — coordinate or split
- 2026-11-03T14:52:13.054Z: touches-expansion: overlaps st-b983 (LEARNINGS.md, data/SOURCES.md, docs/research/2026-11-02-backfill-analysis.py, docs/research/2026-11-02-backfill-driver-test.sh, docs/research/2026-11-02-backfill-driver.sh, docs/research/2026-11-02-backfill-fake-cli, docs/research/2026-11-03-backfill-changes.csv, docs/research/2026-11-03-backfill-evidence.json, docs/research/2026-11-03-backfill-hypotheses.md, docs/research/2026-11-03-backfill-scores.csv, scripts/fetch_aoi.py, src/wetland_change/cli.py, src/wetland_change/verify/waterbodies.py, stories/st-1d45-milestone-2-remaining-verification-matri.md, stories/st-56b8-make-the-dea-waterbodies-checksum-stable.md, stories/st-779a-align-the-now-help-text-with-how-a-value.md, stories/st-b983-run-the-collection-1-backfill-and-score.md, stories/st-e2ae-deduplicate-dea-waterbodies-pairing-rows.md, stories/st-e766-add-the-weekly-verify-workflow-that-open.md, tests/test_cli.py, tests/test_fetch_aoi.py, tests/test_verify_waterbodies.py) — coordinate or split
- 2026-11-03T14:52:13.055Z: touches-expansion: overlaps st-e2ae (LEARNINGS.md, data/SOURCES.md, docs/research/2026-11-02-backfill-analysis.py, docs/research/2026-11-02-backfill-driver-test.sh, docs/research/2026-11-02-backfill-driver.sh, docs/research/2026-11-02-backfill-fake-cli, docs/research/2026-11-03-backfill-changes.csv, docs/research/2026-11-03-backfill-evidence.json, docs/research/2026-11-03-backfill-hypotheses.md, docs/research/2026-11-03-backfill-scores.csv, scripts/fetch_aoi.py, src/wetland_change/cli.py, src/wetland_change/verify/waterbodies.py, stories/st-1d45-milestone-2-remaining-verification-matri.md, stories/st-56b8-make-the-dea-waterbodies-checksum-stable.md, stories/st-779a-align-the-now-help-text-with-how-a-value.md, stories/st-b983-run-the-collection-1-backfill-and-score.md, stories/st-e2ae-deduplicate-dea-waterbodies-pairing-rows.md, stories/st-e766-add-the-weekly-verify-workflow-that-open.md, tests/test_cli.py, tests/test_fetch_aoi.py, tests/test_verify_waterbodies.py) — coordinate or split

## Questions
