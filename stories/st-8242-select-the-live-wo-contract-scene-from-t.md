---
id: st-8242
title: Select the live WO contract scene from the current DEA window
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [tests/test_live_verify.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

remote_scene in tests/test_live_verify.py loads the 2026-10-27 fixture and asserts a matching ga_s2_wo_provisional_3 item, which DEA keeps for a rolling three months. From about late January 2027 the weekly live step would fail and open an issue every Sunday. Verdict PLAUSIBLE: DEA's expiry behaviour was not checked. Evidence: docs/research/2026-11-04-milestone-2-review.md L1.

## Acceptance Criteria

- [ ] The live WO test picks a recent Earth Search scene that has a matching DEA WO item
- [ ] The live WO test still passes when the 2026-10-27 DEA item no longer exists

## Implementation Plan

## Implementation Notes

## Questions
