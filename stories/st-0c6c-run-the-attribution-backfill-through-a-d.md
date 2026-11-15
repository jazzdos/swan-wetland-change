---
id: st-0c6c
title: Run the attribution backfill through a dispatch-only GitHub workflow
type: chore
priority: P2
depends_on: []
touches: [.github/workflows/backfill.yml, README.md, tests/test_readme.py, tests/test_workflows.py]
exclusive: false
created: 2026-11-15
updated: 2026-11-15
---

## Description

Jarrod, 2026-11-15, approved running the bucket backfill on GitHub Actions through the existing OIDC role (swan-wetland-change-pipeline, trusts runs on refs/heads/main, s3 Get/Put/Delete/List on the bucket, 3 h max session) instead of a local aws login, whose sessions AWS caps at 12 hours. The backfill is the README procedure 'Attribution backfill (operator only)': add-observation-footers, add-dea-attribution, add-copernicus-notice (dry run before each real run), then build-catalogue. Add .github/workflows/backfill.yml so the orchestrator can dispatch it. Its log shows only each command's summary line, because the st-b6bf and st-dd0d blindness rules (LEARNINGS.md lines 439 and 357) bar reading output-store objects; Jarrod's instruction authorises the run and the deviation is noted on both stories. Constraints: build agents write and test the workflow locally only; no agent dispatches it, makes an AWS call or reads an output-store object; build agents do not commit or push.

## Acceptance Criteria

- [ ] backfill.yml is workflow_dispatch only with a boolean dry_run input defaulting to true
- [ ] and runs add-observation-footers
- [ ] add-dea-attribution
- [ ] add-copernicus-notice and (only when dry_run is false) build-catalogue as separate jobs in that order
- [ ] Each job has permissions contents: read and id-token: write
- [ ] shares the pipeline concurrency group with cancel-in-progress false
- [ ] assumes the role from repository variables with role-duration-seconds 10800
- [ ] pins every action to the same full commit SHA as pipeline.yml
- [ ] and has a timeout under the 180 minute role session
- [ ] Each command's stdout goes to a file under RUNNER_TEMP and the log prints only its last (summary) line plus stderr; the step keeps the command's exit code
- [ ] tests/test_workflows.py covers these properties and actionlint accepts the workflow
- [ ] README documents the workflow route in the backfill section and tests/test_readme.py matches
- [ ] uv run pytest -q passes

## Implementation Plan

# st-0c6c plan: dispatch-only backfill workflow

## Facts checked at planning time
- `add-observation-footers`, `add-dea-attribution`, `add-copernicus-notice` and `build-catalogue` (src/wetland_change/cli.py lines 457 to 616) call `load_config` and `_store` only. None loads the AOI, so the workflow has no fetch_aoi step.
- Each add-* command prints rewritten paths on stdout, failures as `path<TAB>message` on stderr, then the summary line `scanned N, rewritten M, skipped K, failed F` (`would rewrite` with --dry-run) as its last stdout line, and exits 1 when any file fails. `build-catalogue` prints paths then `N files written`. Each records `capture_environment().git_commit`, so the checkout must keep `.git` (actions/checkout default).
- The OIDC role trusts `repo:<repo>:ref:refs/heads/main` only and has a 10800 s max session (infra/main.tf). pipeline.yml and verify.yml share concurrency group `pipeline` with cancel-in-progress false. Action pins in pipeline.yml: actions/checkout 3d3c42e5aac5ba805825da76410c181273ba90b1 (v7.0.1), astral-sh/setup-uv c771a70e6277c0a99b617c7a806ffedaca235ff9 (v9.0.0, uv 0.9.29, Python 3.12, enable-cache false), aws-actions/configure-aws-credentials e1253824e5c10ff9df46874f81ed3ec929e19cfd (v6.3.0). Repository variables: AWS_ROLE_ARN, AWS_REGION, OUTPUT_BUCKET.
- README section `### Attribution backfill (operator only)` is asserted by tests/test_readme.py line 228 (`BACKFILL_LINES`).

## Batch 1 (two independent tasks)

### T1: .github/workflows/backfill.yml and its tests
Test first in tests/test_workflows.py (add a `BACKFILL_WORKFLOW` constant beside the others and follow the existing helpers and style). Then write the workflow.
- Header comment in the style of verify.yml: purpose (the README attribution backfill on GitHub Actions through the OIDC role, so no local AWS login is needed), dispatch from main only (the role trusts refs/heads/main), shares the `pipeline` concurrency group so it never overlaps a scheduled or verify run, the log shows only summary lines because the st-b6bf and st-dd0d pre-registrations in LEARNINGS.md bar reading output-store objects, one job per command so each gets a fresh 3 hour role session.
- `on: workflow_dispatch` only, with input `dry_run` (type boolean, default true, description naming that true runs each add-* command with --dry-run and skips build-catalogue). No schedule, no push trigger.
- Top-level `permissions: contents: read`. `concurrency: group: pipeline, cancel-in-progress: false`.
- Jobs, chained with `needs` in this order: `footers` (add-observation-footers), `dea` (add-dea-attribution), `copernicus` (add-copernicus-notice), `catalogue` (build-catalogue, `if: ${{ !inputs.dry_run }}`). runs-on ubuntu-24.04. Each job: `permissions: contents: read, id-token: write`; `timeout-minutes: 170`; steps checkout, setup-uv, `uv sync --locked`, configure-aws-credentials (role-to-assume `${{ vars.AWS_ROLE_ARN }}`, aws-region `${{ vars.AWS_REGION }}`, role-duration-seconds 10800 with the same comment as pipeline.yml), then the command step with `timeout-minutes: 150`, using the same pins and versions as pipeline.yml.
- Command step: pass the dry-run flag and bucket through `env` (for example `DRY_RUN: ${{ inputs.dry_run }}`, `OUTPUT_BUCKET: ${{ vars.OUTPUT_BUCKET }}`), never by interpolating into the script body. Run `uv run --no-sync wetland-change <command> --output-root "s3://${OUTPUT_BUCKET}/"` plus `--dry-run` when DRY_RUN is `true` (not for build-catalogue), with stdout redirected to `$RUNNER_TEMP/<command>.out` and stderr to `$RUNNER_TEMP/<command>.err`. Capture the exit code without tripping `bash -e` (for example `status=0; ... || status=$?`), then print `tail -n 1` of the stdout file, then the stderr file, then `exit "$status"`. The rewritten-path list is never printed. A shared shell fragment is fine if actionlint and the tests stay simple; four explicit steps are also fine.
- Tests (each a separate test function): dispatch-only trigger with the boolean `dry_run` input defaulting to true; the four jobs exist with the `needs` chain footers -> dea -> copernicus -> catalogue; catalogue is skipped on a dry run; each job's permissions are exactly contents read and id-token write and the workflow default is contents read; concurrency group `pipeline` with cancel-in-progress false; every `uses:` is pinned to a 40-hex SHA and equals the pin pipeline.yml uses for that action; the credentials step reads role and region from `vars` and requests 10800 seconds; each job timeout is under 180 and each command step timeout fits inside its job timeout; each command step redirects stdout to a file under RUNNER_TEMP, prints only `tail -n 1` of it, keeps the exit code, and passes `--dry-run` only for the three add-* commands; no `${{` expression appears inside a `run:` body; no secret literals (reuse the existing pattern); actionlint accepts the file (skip when actionlint is absent, as the existing tests do). Behavioural test of the command-step script, in the style of the existing recovered-step script tests: run the step body under bash with a stub `uv` on PATH that prints three path lines then a summary line and exits 1, and assert the output holds the summary line, no path line, and the script exits 1.

### T2: README backfill section
- Rename `### Attribution backfill (operator only)` to `### Attribution backfill` and update tests/test_readme.py (line 228 and any other reference) to match. Keep every existing command line in the section (BACKFILL_LINES stays passing).
- Rewrite the opening paragraph: the backfill runs either from a local checkout of main with AWS credentials, by the operator, or through `.github/workflows/backfill.yml`, dispatched from main (`gh workflow run backfill.yml -f dry_run=true`, then `-f dry_run=false`). The workflow runs the same commands in the same order, one job per command, through the pipeline's OIDC role, shares the `pipeline` concurrency group, and its log shows only each command's summary line and stderr, so a reader bound by the st-b6bf and st-dd0d blindness rules sees counts only. Keep the existing statement that the st-b6bf and st-dd0d pre-registrations bar agents from reading output-store objects, and say an agent dispatches the workflow only on the operator's instruction and reads only those summary lines.
- Add a README test that the section names `.github/workflows/backfill.yml` and both `gh workflow run` lines.
- Flat factual prose, no em dashes, matching the surrounding README style.

## Constraints for every agent
No agent dispatches the workflow, makes an AWS call, runs any wetland-change command against s3, or reads an output-store object. No `-m live` test. No edit to pipeline.yml, verify.yml, alert.yml, infra/ or src/. Build agents do not commit or push.

## Implementation Notes

## Questions
