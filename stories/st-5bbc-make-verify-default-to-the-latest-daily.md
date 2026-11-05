---
id: st-5bbc
title: Make verify default to the latest daily run
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [src/wetland_change/verify/run.py, tests/test_verify.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

latest_run_id (src/wetland_change/verify/run.py:83-93) never reads kind, so on a backfill-seeded bucket the weekly verify can target a backfill chunk of tens of scenes and reach its 20 minute step timeout. Verdict PLAUSIBLE: time per scene on a runner is unknown. Evidence: docs/research/2026-11-04-milestone-2-review.md L4.

## Acceptance Criteria

- [ ] verify without --run-id selects the newest manifest of kind run with processed above zero
- [ ] A test with a newer backfill manifest shows the daily run is selected

## Implementation Plan

## Implementation Notes

## Questions
