---
id: st-b983
title: Run the Collection 1 backfill and score hypotheses 1 to 4
type: spike
epic: st-70d1
priority: P1
complexity: hard
depends_on: [st-c8ca, st-2048, st-c6d5]
touches: [docs/research/**, LEARNINGS.md]
exclusive: false
gates: [test]
created: 2026-10-29
updated: 2026-10-29
---
## Description

Spike. Decision at board approval: a worker runs the full Collection 1 backfill locally, then tests the pre-registered hypotheses (LEARNINGS.md, "Pre-registered hypotheses").

- Output root: `/Users/jarrodbaker/Documents/swan-wetland-change-data/outputs` via `--output-root`. Create it; it sits outside every worktree so it survives worktree teardown.
- Range: 2022-12-01 to the day of the run. Collection 1 has no earlier history for five of six tiles (LEARNINGS.md, S4).
- Size: about 996 items, roughly 7 hours at an assumed 25 s per scene (S4; S3 timed one polygon window only).
- Run `uv run python scripts/fetch_aoi.py` first. Run the backfill in chunks, for example one calendar quarter per invocation, in the background. The ledger makes each chunk resumable, so rerun an interrupted one.
- Then run `wetland-change score` over the whole range and the DEA Waterbodies history check over the backfill.

Hypotheses:

1. Forrestdale shows a low-water anomaly in December 2023 or January 2024.
2. February to April 2023 at Forrestdale raise no anomaly. The 2022 half is untestable because Collection 1 has no data; record it so.
3. Winter 2025 (June to August) at Forrestdale and Thomsons shows water at or above the baseline, with no dry-down flag.
4. Spearman correlation between pipeline water hectares and DEA Waterbodies wet fraction, on passes within three days, is at least 0.9.

Polygons: Forrestdale is ramsar-56 and DEA waterbody qd63n1ww5_v3. Thomsons is ramsar-52 and qd635epws_v3. Report each hypothesis as supported, not supported or untestable, with the numbers. Do not tune thresholds or config to make a hypothesis pass; they are pre-registered.

## Acceptance Criteria

- [ ] The ledger under the output root has entries for at least 95 % of the Earth Search Collection 1 items from 2022-12-01 to the run date under the cloud threshold, with the reference count taken from a fresh search and recorded in the report.
- [ ] `docs/research/<date>-backfill-hypotheses.md` records the range, items processed and failed, wall time, and for each of hypotheses 1 to 4 the verdict with measured values (dates, z scores, Spearman rho and n).
- [ ] LEARNINGS.md gains a dated "Backfill hypotheses" section linking that report, with the 2022 half of hypothesis 2 marked untestable.
- [ ] `docs/research/<date>-backfill-changes.csv` lists every change row produced for ramsar-56 and ramsar-52.
- [ ] No file under `config/` or `src/` changes in this story.

## Implementation Plan

## Implementation Notes

## Questions
