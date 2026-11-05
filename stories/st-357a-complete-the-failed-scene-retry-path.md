---
id: st-357a
title: Complete the failed-scene retry path
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [src/wetland_change/ledger.py, src/wetland_change/pipeline.py, src/wetland_change/cli.py, src/wetland_change/verify/freshness.py, tests/test_ledger.py, tests/test_pipeline.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

After three failed attempts exhausted_keys (src/wetland_change/ledger.py:238) drops a scene and the daily run reports nothing, with no requeue command. One DNS failure failed 25 scenes in a single backfill pass, so the trigger is real. Separately run_once rescores only dates written in that run, so a retried scene on an earlier date leaves later change files stale against a full rescore. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 6.

## Acceptance Criteria

- [ ] An exhausted item can be requeued by a CLI command without editing the ledger
- [ ] Exhausted items are counted in the run manifest and fail the freshness check while unresolved
- [ ] Storing a scene with an earlier acquisition date rescores later stored dates of the same polygon and month
- [ ] A test retries a failed scene and shows the stored change files equal a full rescore

## Implementation Plan

## Implementation Notes

## Questions
