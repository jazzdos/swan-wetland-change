---
id: st-5f74
title: Populate dea_wo_agreement or record why the column stays null
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [src/wetland_change/stats.py, src/wetland_change/pipeline.py, docs/decisions/**, AGENTS.md, tests/test_pipeline.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

AGENTS.md (locked decisions), ADR 0002 and design line 179 say each observation stores the DEA Water Observations agreement. src/wetland_change/stats.py:131 writes None on every row and the agreement exists only in the verification report. No decision records the change. README.md lists this as a limitation. Found while checking the st-06a8 README, not by the review. DEA keeps the product for three months, so a backfill could not fill it. Needs a decision between populating recent rows and amending the locked decision.

## Acceptance Criteria

- [ ] Observation rows hold the DEA agreement when a matching WO item exists or an ADR records why the column stays null
- [ ] AGENTS.md and the design match whichever is chosen

## Implementation Plan

## Implementation Notes

## Questions
