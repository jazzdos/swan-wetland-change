---
id: st-a919
title: Size the OIDC session to the pipeline job
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [infra/main.tf, .github/workflows/pipeline.yml, tests/test_infra.py, tests/test_workflows.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

aws_iam_role.pipeline (infra/main.tf:106) sets no max_session_duration and pipeline.yml sets no role-duration-seconds, so credentials last the 3600 s default against a 120 minute job and are never refreshed. A run reaching S3 past 60 minutes writes no ledger and repeats. This changes infra, so land it before the first apply or apply again afterwards. Verdict PLAUSIBLE: the AWS defaults and expiry behaviour were not exercised against AWS. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 3.

## Acceptance Criteria

- [ ] aws_iam_role.pipeline sets max_session_duration to at least the pipeline job timeout
- [ ] pipeline.yml sets role-duration-seconds equal to the role maximum
- [ ] tests/test_infra.py and tests/test_workflows.py assert both values

## Implementation Plan

## Implementation Notes

## Questions
