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
updated: 2026-11-14
parked_complexity: hard
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

- 2026-11-14T12:05:42.130Z: st-dd0d cannot start: its sample holds 0 scheduled runs on 0 acquisition dates, so it parks under its own rule. Facts checked on 2026-11-14 at 12:00 UTC. No advisory summary from the sample was read.

- st-a32a reached local main at 02:14 UTC (08ec2ec) and GitHub main at 04:11 UTC (2db25a1). The last scheduled pipeline run, 43475454140, started at 2026-11-13 17:42 UTC on 37af4e4, before st-a32a. No pipeline run has started since.
- Today's run should score no waterbody rows. Earth Search has no AOI acquisition on 11-14. The 11-13 T50HMK footprint (18.6 percent cloud) touches none of the 1,404 waterbody polygons, and 11-13 T50HMJ is at 74.5 percent cloud. The first run that can score waterbody rows is on 2026-11-16.
- The minimum of 8 runs on 6 acquisition dates probably cannot be reached by 2026-12-05. Earth Search shows full AOI passes every 5 days (11-01, 11-06, 11-11) and T50HMJ edge passes 2 days after each one (11-03, 11-08, 11-13). The edge footprint touches 32 waterbody polygons. Projected acquisition dates in the window are 11-16, 11-18, 11-21, 11-23, 11-26, 11-28, 12-01 and 12-03, which is at most 8, and 4 of them cover only about 32 polygons. One daily run normally processes one date, so 8 runs needs every pass under the 20 percent cloud limit. The same window in earlier years had 6 usable dates in 2025 (11-16, 11-21, 11-26, 11-28, 11-30, 12-01) and 6 in 2024 (11-16, 11-18, 11-23, 11-26, 11-28, 12-01), each likely about 6 runs. In the first trial week, 1 of 8 runs processed scenes.
- The story does not say whether weekly verify.yml runs count. They re-verify the latest daily run's scenes, so counting them would count the same rows twice. It also sets no minimum of scored rows per run, and an edge-pass run of at most 32 polygons could set the floor on its own.

Which do you want?

(a) Commit the LEARNINGS.md pre-registration now, before the 11-16 run, exactly as the story states (end 2026-12-05, minimum 8 runs on 6 dates). Then park until 2026-12-06. If the minimum is not met, the layer stays advisory and the ADR records the count.
(b) Commit the pre-registration now with a later fixed end date and the same minimum. The sample closes at the 8th eligible run, and no later than a date you name, such as 2027-01-31. Then park until it closes.
(c) Commit the pre-registration now with a minimum the window can meet, such as 6 runs on 6 dates, end 2026-12-05. Then park until 2026-12-06.
(d) Park with nothing committed and re-plan after 2026-12-05. This option has a cost: the daily workflow commits each run's verification report, with its ## Advisory table, to main, so later pre-registration would not be blind.

With (a), (b) or (c), the pre-registration would also exclude weekly verify.yml runs and count a run only if it scores at least 30 waterbody rows, unless you say otherwise.
