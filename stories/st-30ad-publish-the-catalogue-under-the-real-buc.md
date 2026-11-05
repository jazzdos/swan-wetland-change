---
id: st-30ad
title: Publish the catalogue under the real bucket URL
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [.github/workflows/pipeline.yml, README.md, config/pipeline.toml, infra/README.md, src/wetland_change/cli.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, tests/test_catalogue.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_pipeline.py, tests/test_workflows.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

config/pipeline.toml:46 sets catalogue.base_url to https://example.invalid/swan-wetland-change and nothing overrides it, so every link and asset href in the first published catalogue points at a reserved TLD. infra/README.md never says to set it from the bucket_url output. tests/test_config.py pins the placeholder. Separately the catalogue is built before verify writes its report, so each report is linked one run late. Fix before enabling the workflows. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 4.

## Acceptance Criteria

- [ ] Every link and asset href in the published catalogue starts with the bucket_url output of infra
- [ ] infra/README.md lists setting catalogue.base_url from the bucket_url output as a deploy step
- [ ] tests/test_config.py no longer pins the example.invalid placeholder
- [ ] A run's verification asset is linked in the catalogue written by the same workflow run

## Implementation Plan

# st-30ad: Publish the catalogue under the real bucket URL

Verified in the worktree `.worktrees/st-30ad` (clean, at 5cb5cad). All pointers in the story are accurate. The bucket does not exist yet, so the real `bucket_url` value is unknown. The repo config therefore keeps a placeholder until an operator deploys. The fix makes the deploy step explicit and enforced.

Findings that shape the plan:
- `config/pipeline.toml:46` sets `catalogue.base_url` to the `example.invalid` placeholder. `run_once` (`src/wetland_change/pipeline.py:362`) and `build-catalogue` (`src/wetland_change/cli.py:328`) both pass it to `build_and_write` (`src/wetland_change/stac/catalogue.py:275`). Every href is built from it.
- `infra/outputs.tf` `bucket_url` is `https://<bucket>.s3.<region>.amazonaws.com`. `infra/README.md` never says to put it in the config.
- `tests/test_config.py:51-53` pins the placeholder.
- `.github/workflows/pipeline.yml` runs `run` (which builds the catalogue internally), then `build-catalogue`, then `verify`. `verify_run` writes `verification/<run_id>.json` (`write_report`, `src/wetland_change/verify/run.py:433`). The catalogue adds the `verification` asset only if that file exists (`catalogue.py` `_item`). The asset is therefore linked one run late.
- The `verify` and commit steps use `if: !cancelled() && processed > 0` without `success()`. They still run after a failed earlier step, so a failing verify does not block a later catalogue rebuild.
- `tests/test_workflows.py::test_steps_run_fetch_run_catalogue_verify_commit_in_order` pins the old order `run < build-catalogue < verify < commit`.

## Steps

1. Guard (TDD, `src/wetland_change/stac/catalogue.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/cli.py`, `tests/test_catalogue.py`, `tests/test_cli.py`).
   - Add `ensure_publishable_base_url(base_url: str, store: OutputStore) -> None` to `stac/catalogue.py` and export it from `wetland_change/stac/__init__.py`. It raises `ValueError` when the store is not local (`store.uri` does not start with `file://`) and the base_url host is `invalid` or ends in `.invalid`. The message names `catalogue.base_url`, `config/pipeline.toml` and the `bucket_url` output. Local stores are unaffected, so all existing tests (which use example.invalid with tmp_path roots) stay green.
   - Call it at the start of `run_once` (before any scene work) and in `build_and_write`.
   - In `cli.run`, catch `ValueError` and re-raise as `typer.BadParameter`, as `score` already does. `build-catalogue` gets the same wrapping.
   - Tests prove: the placeholder is rejected for an `s3://` root (check the pure function with a stub store whose `.uri` is `s3://bucket/`, no network); a real `https://bucket.s3.ap-southeast-2.amazonaws.com` base_url is accepted for `s3://`; the placeholder is accepted for a local root; the CLI `build-catalogue` and `run` exit non-zero with a message mentioning `base_url` when `--output-root s3://x/` is combined with the placeholder config (patch `build_and_write`'s store or `_store` so nothing touches S3).
2. Config test and file (`tests/test_config.py`, `config/pipeline.toml`).
   - Replace `test_repo_config_catalogue_placeholder` with `test_repo_config_catalogue_base_url_is_https_without_trailing_slash`, which loads the repo config and asserts it starts with `https://` and does not end with `/`. It must not name `example.invalid`.
   - In `config/pipeline.toml` keep the placeholder value but add a comment above it. The comment says to replace it with the `bucket_url` output of infra at deploy, and that `run` and `build-catalogue` refuse an `s3://` output root while it is a `.invalid` host.
3. Docs (`infra/README.md`, `tests/test_infra.py`).
   - Add a "Set the catalogue base URL" subsection after the repository variables section, and add it to the deploy sequence. The step is: after apply, take `terraform -chdir=infra output -raw bucket_url`, set `[catalogue] base_url` in `config/pipeline.toml` to that value with no trailing slash, and commit it to `main` before the first scheduled run. Explain that every catalogue link and asset href starts with it, and that the pipeline refuses to publish to S3 while the placeholder remains. Also state that the `run` and `build-catalogue` seeding commands in the seeding section require this step first.
   - Add `test_readme_documents_catalogue_base_url_step`: the infra README mentions `catalogue.base_url`, `bucket_url` and `config/pipeline.toml`.
4. Report linked in the same run (`.github/workflows/pipeline.yml`, `tests/test_workflows.py`, `README.md`).
   - Reorder the steps to run, manifest, Verify the run, Rebuild the catalogue, Commit. Rename the catalogue step to "Rebuild the catalogue so it links the verification report". Keep the same `if: ${{ !cancelled() && steps.manifest.outputs.processed > 0 }}` on all of them, so a red verify still lets the catalogue rebuild and commit run. Update the header comment to say why the order matters.
   - `tests/test_workflows.py`: change the order test to `fetch < run < verify < catalogue < commit`, and add an assertion that the catalogue step has no `steps.verify` or `success()` reference in its condition and no `continue-on-error`.
   - `README.md` "Scheduled jobs": say the workflow runs `verify` and then `build-catalogue`.
   - Add a functional test in `tests/test_run_catalogue.py`, modelled on its existing report tests: run `run_once`, call `write_report`, then `build_and_write`, and assert the item has a `verification` asset whose href is `<base>/verification/<run_id>.json`. If a test like this already exists, add the assertion that the first build, before `write_report`, has no such asset, to document the late-link behaviour.
5. Run the verification commands in AGENTS.md order, each as its own command: ruff check, ruff format --check, mypy, pytest -q. Fix anything red.

## Acceptance mapping
- AC1: every href derives from `cfg.catalogue.base_url`. The deploy step sets it to `bucket_url`, and the guard makes publishing to S3 with the placeholder impossible (step 1).
- AC2: step 3.
- AC3: step 2.
- AC4: step 4.

## Implementation Notes

- 2026-11-05T10:07:11.382Z: Gates on the story branch at 030ae5c: ruff check, ruff format --check and mypy pass; pytest passes in default mode and with GITHUB_ACTIONS=true. The repo config keeps the example.invalid placeholder because the bucket does not exist yet, so AC1 is met by the refusal in run and build-catalogue plus the deploy step in infra/README.md. Files beyond the planned touches: src/wetland_change/cli.py, pipeline.py, stac/__init__.py, README.md and tests. A deploy still needs an operator to commit the real base_url.

## Questions
