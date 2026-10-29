---
id: st-afcf
title: "Calibrate water thresholds for ramsar-15, ramsar-28 and ramsar-56"
type: spike
epic: st-1d45
priority: P1
depends_on: []
touches: [docs/research/**, LEARNINGS.md]
exclusive: false
gates: [test]
created: 2026-10-29
updated: 2026-10-29
---
## Description

Spike. Decision at board approval: calibrate ramsar-15, ramsar-28 and ramsar-56 separately instead of excluding them. The DEA S2 Water Observations check (`src/wetland_change/verify/wo.py`, check `water_vs_dea_s2_wo`, agreement_min 0.91) fails on these polygons on the 2026-10-27 and 2026-10-29 passes (`docs/handoffs/2026-10-29-milestone-1.md`, State):

| Polygon | Measured agreement |
|---|---|
| ramsar-15 | 0.576 and 0.902 |
| ramsar-28 | 0.907 to 0.909 |
| ramsar-56 (Forrestdale, on the 50HLK/50HMK seam) | 0.854 to 0.868 |

The global method, MNDWI at -0.1, came from spike S2 over four lakes (LEARNINGS.md, "S2 water calibration"; `docs/research/2026-10-29-water-calibration.csv`). The S2 scripts are untracked and exist only at `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/feature/wetland-change-pipeline/scratch/spikes/` (`s2_calibrate.py`, `wo_spike.py`). Copy them into this worktree's gitignored `scratch/spikes/` and adapt them.

DEA `ga_s2_wo_provisional_3` keeps about three months, so sweep the passes available now. For each polygon, sweep NDWI and MNDWI thresholds and SCL class 6 and record pixel-weighted agreement. Recommend a method, threshold and agreement_min per polygon, and say whether one estuary-and-creek class setting would serve all three. Compare ramsar-56's scores on 50HLK and 50HMK to see whether the seam explains its lower agreement.

## Acceptance Criteria

- [ ] `docs/research/<date>-polygon-calibration.csv` has one row per polygon, method, threshold and pass, with n_mutually_clear and agreement.
- [ ] LEARNINGS.md gains a dated "Per-polygon water calibration" section giving, for each of ramsar-15, ramsar-28 and ramsar-56, the chosen method, threshold, pixel-weighted agreement and proposed agreement_min.
- [ ] That section states whether ramsar-56 agreement differs between tiles 50HLK and 50HMK, and by how much.
- [ ] No file under `src/` or `config/` changes in this story.

## Implementation Plan

## Implementation Notes

## Questions
