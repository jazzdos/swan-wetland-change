---
id: st-0248
title: Alert on every scheduled run that does not succeed
type: chore
epic: st-f849
priority: P3
depends_on: []
touches: [.github/workflows/pipeline.yml, .github/workflows/verify.yml, tests/test_workflows.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

The verify issue step uses if failure(), which does not fire on a job timeout, a cancelled pending run or a lost runner. The daily pipeline has no issue step. Each failing week opens a new issue, and both crons fire at minute 0. Verdict PLAUSIBLE: GitHub's classification of timeouts and cancellations was not checked. Evidence: docs/research/2026-11-04-milestone-2-review.md L7.

## Acceptance Criteria

- [ ] A cancelled or timed-out scheduled run of either workflow produces an alert
- [ ] A repeated failure comments on the open failure issue instead of opening a new one
- [ ] Both cron schedules use a minute other than zero

## Implementation Plan

## Implementation Notes

## Questions
