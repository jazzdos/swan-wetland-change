---
id: st-f849
title: "Milestone 2: scheduled operation on GitHub Actions and S3"
type: epic
priority: P2
depends_on: []
touches: []
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Milestone 2 scheduled operation: the `infra/`, `pipeline.yml` and `verify.yml` components of `docs/plans/2026-10-29-swan-wetland-change-design.md`, success criterion 1, and the 60-day scheduled-workflow rule (design, Challenges).

Decision at board approval on 2026-10-29: no AWS account, bucket or GitHub repository exists yet (the repo has no git remote). Write and validate everything offline only: `terraform validate` or `tofu validate`, `actionlint`, and YAML-structure tests. Never run `plan` or `apply`, never call AWS, never create a repository or push. Human follow-ups: apply the infra, create the repository and its variables, run spikes 5, 6 and 7, and run the four-week unattended trial.

Conventions come from `.github/workflows/test.yml`: actions pinned to full commit SHAs with a version comment, `ubuntu-24.04`, setup-uv 0.9.29 with Python 3.12 and `enable-cache: false`, `uv sync --locked`, then `uv run --no-sync`.

## Implementation Plan

## Implementation Notes

## Questions
