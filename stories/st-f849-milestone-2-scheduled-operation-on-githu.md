---
id: st-f849
title: "Milestone 2: scheduled operation on GitHub Actions and S3"
type: epic
priority: P2
depends_on: []
touches: []
exclusive: false
created: 2026-10-29
updated: 2026-11-16
---
## Description

Milestone 2 scheduled operation: the `infra/`, `pipeline.yml` and `verify.yml` components of `docs/plans/2026-10-29-swan-wetland-change-design.md`, success criterion 1, and the 60-day scheduled-workflow rule (design, Challenges).

Decision at board approval on 2026-10-29: no AWS account, bucket or GitHub repository exists yet (the repo has no git remote). Write and validate everything offline only: `terraform validate` or `tofu validate`, `actionlint`, and YAML-structure tests. Never run `plan` or `apply`, never call AWS, never create a repository or push. Human follow-ups: apply the infra, create the repository and its variables, run spikes 5, 6 and 7, and run the four-week unattended trial.

Conventions come from `.github/workflows/test.yml`: actions pinned to full commit SHAs with a version comment, `ubuntu-24.04`, setup-uv 0.9.29 with Python 3.12 and `enable-cache: false`, `uv sync --locked`, then `uv run --no-sync`.

## Implementation Plan

## Implementation Notes

- 2026-11-06T07:57:23.769Z: Epic closed under the loop with no code of its own: all 24 child stories are done and merged to local main. Human follow-ups, none run by the agent: (1) apply infra/ with tofu or terraform plan and apply against the real AWS account; (2) set the GitHub repository variables the pipeline and verify workflows read; (3) run spikes 5, 6 and 7; (4) run the four-week unattended trial for success criterion 1 and the 60-day scheduled-workflow rule. The description's statement that no GitHub repository exists is out of date: the public repo jazzdos/swan-wetland-change exists with origin/main at 0e551f1. Local main is ahead of origin and has not been pushed. Open question carried from st-58e9: whether public s3:ListBucket on observations/ is wanted. ADR 0010 (ramsar-12 keeps the global threshold) was decided under delegation and awaits Jarrod's review.
- 2026-11-16T11:36:28.625Z: 2026-11-16: Jarrod approved the epic review ('approve all', in reply to a list of open items that named the epic review). This closes the review that ADR 0008 and ADR 0009 waited on; both ADRs were already marked approved in f501dac. The DBCA-010 licence confirmation (st-4c87) stays open: Jarrod resolves it separately.

## Questions
