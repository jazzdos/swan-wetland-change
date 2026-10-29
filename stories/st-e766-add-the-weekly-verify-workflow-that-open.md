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
updated: 2026-10-29
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

## Implementation Notes

## Questions
