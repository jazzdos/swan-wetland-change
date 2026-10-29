---
id: st-c6d5
title: Add the DEA Waterbodies history check
type: feature
epic: st-1d45
priority: P2
depends_on: [st-2522]
touches: [src/wetland_change/verify/waterbodies.py, src/wetland_change/verify/run.py, src/wetland_change/config.py, config/**, tests/test_verify_waterbodies.py, tests/fixtures/**]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Verification matrix row "Water extent, history" (design). Per lake, compare the pipeline wet fraction over the DEA waterbody polygon with DEA Waterbodies v3 wet fraction on passes 1 to 3 days apart, within the tolerance recorded in LEARNINGS.md "S9 historical tolerance". Also check that Spearman correlation over all paired passes is at least 0.9; hypothesis 4 uses the same pairing.

- Pipeline side: observation rows with `aoi_layer == "dea_waterbody"` (loaded by `src/wetland_change/aoi.py` from `waterbodies_path`). Wet fraction is `water_ha_index` over the polygon area in hectares.
- Lakes and uids: Thomsons qd635epws_v3, Forrestdale qd63n1ww5_v3, Lake Clifton qd4m2n3rj_v3, Lake Preston qd4k2967m_v3. Peel Inlet and Harvey Estuary have none. The CSV URL pattern is in the design's Verified facts.
- New `src/wetland_change/verify/waterbodies.py`. Emit per-pass checks plus one Spearman check per lake when there are at least 10 pairs; with fewer, emit a skipped check with a reason.
- Callable over a date range (the backfill spike uses it) and from `verify_run` for a run's scenes.
- The tolerance lives in `config/pipeline.toml`.

## Acceptance Criteria

- [ ] Offline test with a saved CSV excerpt fixture: a pass 2 days from a Waterbodies observation passes `water_vs_dea_waterbodies` when the wet-fraction difference is inside the tolerance, and fails when it is outside.
- [ ] Offline test: a pipeline row with no Waterbodies observation within 3 days produces no paired check.
- [ ] Offline test: Spearman is computed per lake over at least 10 synthetic pairs and compared with 0.9, and fewer than 10 pairs gives a skipped check with a reason.
- [ ] The tolerance in `config/pipeline.toml` equals the value in LEARNINGS.md "S9 historical tolerance".
- [ ] Live test marked `live`: the Thomsons CSV downloads and parses.

## Implementation Plan

## Implementation Notes

## Questions
