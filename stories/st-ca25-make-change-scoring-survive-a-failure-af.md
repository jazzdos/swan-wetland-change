---
id: st-ca25
title: Make change scoring survive a failure after the ledger write
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [src/wetland_change/pipeline.py, tests/test_pipeline.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

write_ledger (src/wetland_change/pipeline.py:319) marks scenes succeeded before score_changes, write_manifest and build_and_write run. If one raises, the next run skips those scenes through seen_keys, so their change files and manifest are never written and later days stay green. Recovery needs a manual score. This contradicts the design statement that reruns are safe. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 2.

## Acceptance Criteria

- [ ] A failure in score_changes or write_manifest leaves the run's scenes eligible for scoring on the next run
- [ ] The next run writes the change files and a manifest that the crashed run left unwritten
- [ ] A test forces score_changes to raise once and shows the change file exists after the following run

## Implementation Plan

## Implementation Notes

## Questions
