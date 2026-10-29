---
id: st-ec32
title: Add the daily pipeline workflow
type: feature
epic: st-f849
priority: P2
depends_on: [st-a868]
touches: [.github/workflows/pipeline.yml, tests/test_workflows.py, pyproject.toml, uv.lock]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
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

## Implementation Notes

## Questions
