---
id: st-ec32
title: Add the daily pipeline workflow
type: feature
epic: st-f849
priority: P2
depends_on: [st-a868]
touches: [.github/workflows/pipeline.yml, tests/test_workflows.py]
exclusive: false
created: 2026-10-29
updated: 2026-11-01
---
## Description

Add `.github/workflows/pipeline.yml` (design, Components): a daily cron at 10:00 UTC plus `workflow_dispatch`.

- Assume the AWS role through OIDC with aws-actions/configure-aws-credentials, using repository variables `AWS_ROLE_ARN` and `AWS_REGION`.
- Fetch the AOI with `scripts/fetch_aoi.py`, because `data/external/` is gitignored.
- Run `wetland-change run --output-root s3://${{ vars.OUTPUT_BUCKET }}/…`, then `build-catalogue`, then `verify`.
- Commit the verification report when the run processed scenes. This keeps the repository active under GitHub's 60-day scheduled-workflow rule (design, Challenges). A failing verify must not block that commit.
- pyarrow's S3FileSystem reads credentials from the environment the AWS action sets.

Follow the conventions of `.github/workflows/test.yml`. No GitHub repository exists yet, so validate offline: add `tests/test_workflows.py`, which loads the YAML and asserts its structure. Add a YAML parser as a dev dependency if none is locked.

## Acceptance Criteria

- [ ] `actionlint .github/workflows/pipeline.yml` exits 0.
- [ ] `tests/test_workflows.py` asserts: cron `0 10 * * *`; `workflow_dispatch` present; every `uses:` pinned to a 40-character commit SHA; job permissions exactly `contents: write` and `id-token: write`.
- [ ] The test asserts the step order: fetch AOI, `wetland-change run --output-root s3://…`, `wetland-change build-catalogue`, `wetland-change verify`, then the commit step.
- [ ] The commit step's `if:` makes it run only when the run manifest reports more than 0 processed scenes, and still run when verify exits non-zero; the test asserts this.
- [ ] No AWS key or secret literal appears in the workflow, and `role-to-assume` is `${{ vars.AWS_ROLE_ARN }}`.

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-ec32)

- `.github/workflows/test.yml` exists. Conventions: SHA-pinned actions with a `# actions/checkout v7.0.1` style comment line above each `uses:` (checkout 3d3c42e5aac5ba805825da76410c181273ba90b1, setup-uv c771a70e6277c0a99b617c7a806ffedaca235ff9 with uv 0.9.29, python 3.12, enable-cache false), `ubuntu-24.04`, `timeout-minutes`, `uv sync --locked`, then `uv run --no-sync ...`.
- `scripts/fetch_aoi.py` exists (writes data/external/*.geojson, needs only `requests`). `data/external/` is gitignored, so the workflow must run `uv run --no-sync python scripts/fetch_aoi.py`.
- CLI (src/wetland_change/cli.py) already has `run`, `build-catalogue` (st-a868 has merged) and `verify`, all with `--output-root`. `run` echoes the manifest JSON on stdout (logging goes to stderr) and exits 2 if any scene failed. The manifest JSON has an integer `processed` field. `verify` with no `--run-id` takes the latest run with processed > 0, writes the Markdown report to `docs/research/verification-<run_id>.md` (tracked in git, e.g. verification-20261029T131944Z.md) plus JSON beside the outputs, and exits 3 (a check failed), 4 (nothing scored), or 2 (no run found).
- `OutputStore` uses pyarrow `FileSystem.from_uri`, so `s3://` works and credentials come from the environment variables `aws-actions/configure-aws-credentials` exports (no extra code).
- infra/README.md: repo variables `AWS_ROLE_ARN`, `OUTPUT_BUCKET` (bare bucket name, no scheme), `AWS_REGION`. The role trusts only `ref:refs/heads/main`.
- PyYAML 6.0.3 is already locked in uv.lock (transitive via pytest-regressions) and imports under `uv run`. So per the story no new dependency is added. Tests are not under mypy (`files = ["src","scripts"]`), so no stubs are needed.
- `actionlint` 1.7.12 is installed at /opt/homebrew/bin/actionlint.
- `aws-actions/configure-aws-credentials` v6.3.0 resolves to e1253824e5c10ff9df46874f81ed3ec929e19cfd (checked with git ls-remote).

No contradiction with the code; the story is implementable as written.

## Design decisions

- Output root is `s3://${{ vars.OUTPUT_BUCKET }}/` (bucket root, no prefix; infra README and st-e766 use the bare bucket).
- `run` stdout (the manifest JSON) is redirected to `$RUNNER_TEMP/run-manifest.json` (a redirect, not a pipe, so its exit code is kept). A step with `id: manifest` reads `.processed` with `jq` and writes `processed=<n>` to `$GITHUB_OUTPUT`. The order stays fetch AOI, run, (manifest read), build-catalogue, verify, commit; the manifest-read step is bookkeeping between run and build-catalogue and the test checks relative order, not adjacency.
- `verify` is gated with `if: ${{ steps.manifest.outputs.processed > 0 }}`. Without that gate, a no-op day would re-verify an old run, or fail with exit 2 when the output root holds no processed run yet.
- The commit step uses `if: ${{ !cancelled() && steps.manifest.outputs.processed > 0 }}`. A status-check function in the condition drops the implicit `success()`, so the step runs after a failed verify. The job still ends red because verify is not `continue-on-error`. If `run` itself fails, the manifest step is skipped, `processed` is empty, and the commit is skipped.
- The commit step does `git add docs/research/verification-*.md`, then `git diff --cached --quiet || git commit ...`, then `git push`. This is idempotent if verify wrote nothing.
- Job `permissions` are exactly `contents: write` and `id-token: write`. Top-level is `contents: read`, as in test.yml. A `concurrency` group with `cancel-in-progress: false` prevents overlapping runs racing on the push.

## Steps

1. Write `tests/test_workflows.py` first (red, since the workflow does not exist yet). It loads `.github/workflows/pipeline.yml` with `yaml.safe_load`. PyYAML parses the key `on` as boolean `True`, so read triggers with `doc.get("on", doc.get(True))`. Tests:
   - `test_cron_and_dispatch`: `schedule == [{"cron": "0 10 * * *"}]`, `"workflow_dispatch"` in triggers.
   - `test_every_uses_pinned_to_40_char_sha`: collect every step `uses:` across all jobs; assert at least 3 (checkout, setup-uv, configure-aws-credentials) and each matches `^[\w.-]+/[\w./-]+@[0-9a-f]{40}$`.
   - `test_job_permissions_exact`: the single job's `permissions == {"contents": "write", "id-token": "write"}`.
   - `test_step_order`: find step indexes by substring in `run` or `uses`: `scripts/fetch_aoi.py`; a regex for `wetland-change run --output-root s3://`; `wetland-change build-catalogue`; `wetland-change verify`; the commit step (`run` contains `git commit`). All must exist and be strictly increasing. Also assert the OUTPUT_BUCKET expression `s3://${{ vars.OUTPUT_BUCKET }}` appears in the run step and that the verify and build-catalogue steps pass `--output-root` too.
   - `test_commit_step_conditions`: the commit step `if` contains `steps.manifest.outputs.processed > 0` (or a normalised equivalent) and `!cancelled()` or `always()`; it must not contain a bare `success()`. The verify step has no `continue-on-error` (a failing verify must keep the job red). The step with `id: manifest` exists and precedes the verify step, and its `run` mentions `GITHUB_OUTPUT` and `processed`.
   - `test_aws_credentials_step`: the configure-aws-credentials step has `with["role-to-assume"] == "${{ vars.AWS_ROLE_ARN }}"` and `with["aws-region"] == "${{ vars.AWS_REGION }}"`.
   - `test_no_aws_secret_literals`: raw file text has no match for `AKIA[0-9A-Z]{16}`, `ASIA[0-9A-Z]{16}`, `aws-secret-access-key`, `aws-access-key-id`, `AWS_SECRET_ACCESS_KEY`, `secrets.AWS`, or `[0-9a-zA-Z/+]{40}` adjacent to "secret" (keep the checks simple and specific; the SHAs must not trip them).
   - Optional: `test_actionlint_clean` that runs `actionlint` via `shutil.which` and `pytest.skip`s if absent.
   What this proves: the structural acceptance criteria hold offline, with no GitHub repository available.
2. Write `.github/workflows/pipeline.yml` (full content is in the task prompt). Confirm the new tests pass.
3. Run `actionlint .github/workflows/pipeline.yml` (exit 0), then the full verification in order: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. Fix lint or format issues in the test file.
4. Add a short note to `infra/README.md` under "Repository variables" or Notes only if it needs one (for example, that `pipeline.yml` commits `docs/research/verification-*.md` and so needs `contents: write`). This is optional; do not touch other files.
5. Commit on the story branch: `git add .github/workflows/pipeline.yml tests/test_workflows.py` (plus infra/README.md if edited). The message ends with the Co-Authored-By line from the session attribution.

## Implementation Notes

## Questions
