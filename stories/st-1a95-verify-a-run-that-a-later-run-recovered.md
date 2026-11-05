---
id: st-1a95
title: Verify a run that a later run recovered
type: bug
priority: P2
depends_on: [st-ca25]
discovered_from: st-ca25
touches: [.github/workflows/pipeline.yml, tests/test_workflows.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

st-ca25 makes the next run finish a crashed daily run and write its manifest with recovered_by set. pipeline.yml keys its verify step on the current run's processed count, and verify defaults to the newest daily run with processed scenes. A recovering run that processed nothing skips verify, and one that processed scenes verifies only itself, so verification/<run_id>.json is never written for the recovered run unless someone runs verify --run-id by hand. Out of scope in st-ca25, whose criteria cover change files and the manifest. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 2 lists the missing verification report as part of the loss.

## Acceptance Criteria

- [ ] When the run's manifest lists recovered_runs
- [ ] the daily job runs verify --run-id for each of them
- [ ] A day with processed 0 and no recovered_runs still skips verify
- [ ] A workflow test shows the step that verifies recovered runs and its condition

## Implementation Plan

## Implementation Notes

## Questions
