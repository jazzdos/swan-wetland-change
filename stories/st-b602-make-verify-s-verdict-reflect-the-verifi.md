---
id: st-b602
title: Make verify's verdict reflect the verification matrix
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/verify/checks.py, src/wetland_change/verify/run.py, src/wetland_change/verify/wo.py, src/wetland_change/verify/ndvi.py, tests/test_verify.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

verify exits 3 only on a False check and 4 only when nothing scored (src/wetland_change/cli.py:254-258), and all_passed uses scored checks alone (verify/checks.py:79), so an unreachable DEA or Planetary Computer gives exit 0 and all_passed true. The Spearman check sees only the run's scenes and always skips in steady state. Seven matrix rows have no check in the JSON. wo_check has no pixel floor (verify/wo.py:119), so one disagreeing pixel on a tiny DEA polygon fails the run. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 5.

## Acceptance Criteria

- [ ] verify exits non-zero when a reference check is skipped because its source raised an error
- [ ] WO and NDVI checks skip a polygon below a configured minimum of mutually clear pixels
- [ ] The Spearman check scores over stored history and not only the run's scenes
- [ ] The weekly report lists every matrix row with a pass or fail or not-run status

## Implementation Plan

## Implementation Notes

## Questions
