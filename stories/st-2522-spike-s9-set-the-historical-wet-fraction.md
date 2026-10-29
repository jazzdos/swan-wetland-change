---
id: st-2522
title: "Spike S9: set the historical wet-fraction tolerance"
type: spike
epic: st-1d45
priority: P2
depends_on: []
touches: [docs/research/**, LEARNINGS.md]
exclusive: false
gates: [test]
created: 2026-10-29
updated: 2026-10-29
---
## Description

Spike S9 from the design's pre-start list: compare DEA Waterbodies v3 wet fraction, from the per-lake CSV whose URL pattern is in the design's Verified facts, with DEA Landsat Water Observations `ga_ls_wo_3` per scene over one lake. Use Thomsons, uid qd635epws_v3, 193.2 ha. The result sets the 10 to 15 pp tolerance band that the history check uses.

Both products are CC BY 4.0 and unsigned (DEA STAC `https://explorer.dea.ga.gov.au/stac`, bucket `dea-public-data`). The waterbody polygons are in `data/external/dea_waterbodies_v3_swan.geojson` after `uv run python scripts/fetch_aoi.py`. Use passes from 2022-12 onward. Work in the gitignored `scratch/spikes/`.

## Acceptance Criteria

- [ ] `docs/research/<date>-waterbodies-tolerance.csv` has one row per pass with date, Waterbodies wet fraction, `ga_ls_wo_3` wet fraction and difference.
- [ ] LEARNINGS.md gains a dated "S9 historical tolerance" section with the pass count, median, 90th percentile and maximum absolute difference, and the chosen tolerance in percentage points.
- [ ] No file under `src/` or `config/` changes in this story.

## Implementation Plan

## Implementation Notes

## Questions
