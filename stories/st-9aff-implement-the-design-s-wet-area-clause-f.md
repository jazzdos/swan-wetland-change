---
id: st-9aff
title: Implement the design's wet area clause for live water or record why it was dropped
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [src/wetland_change/verify/wo.py, docs/decisions/**, tests/test_verify.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

The design's Water extent live row (line 226) requires pixel agreement and wet area within 5 pp. src/wetland_change/verify/wo.py checks only pixel agreement, and no decision or handoff records why. README.md lists this as not implemented. Found while checking the st-06a8 README, not by the review.

## Acceptance Criteria

- [ ] The live water check scores wet area within 5 pp or an ADR records why the clause was dropped
- [ ] The README verification matrix row matches the outcome

## Implementation Plan

## Implementation Notes

## Questions
