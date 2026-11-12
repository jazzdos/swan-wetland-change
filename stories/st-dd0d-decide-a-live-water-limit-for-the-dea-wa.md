---
id: st-dd0d
title: Decide a live water limit for the DEA Waterbodies layer from the trial's advisory summaries
type: spike
priority: P3
complexity: hard
depends_on: [st-a32a]
discovered_from: st-a32a
touches: [LEARNINGS.md, docs/decisions/0015-waterbody-layer-live-water-limit.md, docs/research/2026-12-05-waterbody-layer-agreement.py]
exclusive: false
created: 2026-11-12
updated: 2026-11-12
---

## Description

Follow-up to st-a32a and ADR 0012. From st-a32a on, the live water and NDVI measurements on the 1,404 dea_waterbody polygons are advisory: each run stores them and reports one summary per check (rows scored, rows outside the ramsar limit, pooled agreement, pooled wet gap, NDVI median absolute difference). On the two passes measured before that change the pooled agreement with DEA WO on this layer was 0.9237 (2026-10-29) and 0.9054 (2026-11-11) against 0.9878 and 0.9616 on the ramsar layer, and about 45 percent of scored waterbody rows fell under 0.91 on both. No limit has ever been calibrated for this layer.

What this story decides: whether the dea_waterbody layer gets its own blocking run-level limit for the live water check, set from data that had not been seen when the rule was written. The rule is written into LEARNINGS.md first: the sample is the advisory summaries of every scheduled run with scored waterbody rows from the day st-a32a reaches main until the end of the four-week trial (2026-12-05); the two passes above are disclosed as seen and are not part of the sample; a minimum of 8 runs on at least 6 acquisition dates; the candidate limit is the floor to 0.01 of the lowest pooled agreement in the sample minus 0.02 (the ADR 0005 and ADR 0007 convention); it is adopted only if that value is at least 0.85 and the pooled wet gap stays within 5.0 pp on at least 90 percent of the runs; otherwise the layer stays advisory and the measured rates are recorded. The outcome goes in an ADR for Jarrod's approval. Whether a waterbody polygon is ever scored one by one is not part of this story.

This story cannot start before st-a32a is on main and the trial has produced the minimum sample. If it is claimed earlier, park it with the count of runs available.

## Acceptance Criteria

- [ ] LEARNINGS.md holds the pre-registered rule for this story committed before any advisory summary of the sample is read
- [ ] The sample has at least 8 scheduled runs on at least 6 acquisition dates after st-a32a reached main or the story is parked with the count available
- [ ] docs/research holds the script and its CSV and text summary with one row per run giving rows scored and pooled agreement and pooled wet gap for the dea_waterbody layer
- [ ] An ADR records whether a run-level limit is adopted and its value and the measured rates and a status line saying it is not yet approved by Jarrod
- [ ] No limit is added to config or code by this story
- [ ] ruff check and ruff format --check and mypy and pytest all exit 0

## Implementation Plan

## Implementation Notes

## Questions
