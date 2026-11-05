---
id: st-fbe8
title: Refuse a reused run id in the daily run
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [src/wetland_change/pipeline.py, tests/test_pipeline.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

Two run calls with the same --now overwrite the earlier ledger file and manifest. Only a manual dispatch with a repeated --now reaches this. backfill_once already refuses the same case. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md L9.

## Acceptance Criteria

- [ ] run_once raises when the run id already has a manifest or ledger file in the output root

## Implementation Plan

## Implementation Notes

## Questions
