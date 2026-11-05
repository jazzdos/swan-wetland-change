---
id: st-1b50
title: Stop re-logging unchanged rejected items
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [src/wetland_change/ledger.py, src/wetland_change/pipeline.py, tests/test_ledger.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

A guard-rejected item stays in the created window while it is the newest item, so each run writes another rejected row and ledger part (src/wetland_change/pipeline.py:309-318). Growth is bounded and adds to the S3 request growth. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md L8.

## Acceptance Criteria

- [ ] An item rejected with the same updated timestamp is not written to the ledger again

## Implementation Plan

## Implementation Notes

## Questions
