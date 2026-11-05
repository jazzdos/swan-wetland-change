---
id: st-03c0
title: Surface manifest read errors in verify
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

latest_run_id catches OSError and continues (src/wetland_change/verify/run.py:89), so a permission or credential failure reading a manifest is silent and verify checks an older run or exits 2. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md L5.

## Acceptance Criteria

- [ ] An OSError while reading a run manifest makes verify exit non-zero with the path in the message

## Implementation Plan

## Implementation Notes

## Questions
