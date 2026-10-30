---
id: st-ced9
title: Treat only DEA WO values 0 and 128 as clear
type: bug
epic: st-1d45
priority: P3
depends_on: [st-2048]
discovered_from: st-2048
touches: [src/wetland_change/verify/wo.py, tests/test_verify.py, docs/plans/**]
exclusive: false
created: 2026-10-30
updated: 2026-10-30
---

## Description

src/wetland_change/verify/wo.py sets WO_EXCLUDE = 1 | 2 | 32 | 64, following the design's 'Water extent, live' row, so DEA Water Observations pixels with bit 4 (sea), 8 (terrain shadow or low sun) or 16 (high slope) set count as mutually clear. DEA's WO convention treats only 0 (clear dry) and 128 (clear wet) as clear observations. Found while independently checking the st-2048 calibration on 2026-10-30: the live 2026-10-12 ramsar-15 pass had 0 such pixels, so no current result changes, but a coastal or sloped polygon would be scored on pixels DEA itself does not call clear. Out of scope for st-2048, which applies per-polygon thresholds.

## Acceptance Criteria

- [ ] Offline test: wo_agreement counts a WO pixel as clear only when its value is 0 or 128; values 4
- [ ] 8
- [ ] 16 and 132 are excluded.
- [ ] The design's 'Water extent
- [ ] live' matrix row states that only WO values 0 and 128 are clear.
- [ ] The existing offline tests in tests/test_verify.py pass unchanged.

## Implementation Plan

## Implementation Notes

## Questions
