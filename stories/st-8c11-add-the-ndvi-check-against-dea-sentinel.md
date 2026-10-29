---
id: st-8c11
title: Add the NDVI check against DEA Sentinel-2 NBART
type: feature
epic: st-1d45
priority: P2
complexity: hard
depends_on: []
touches: [src/wetland_change/verify/ndvi.py, src/wetland_change/verify/run.py, LEARNINGS.md, tests/test_verify_ndvi.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Verification matrix row "NDVI" (design): DEA NBART from `ga_s2am_ard_3`, `ga_s2bm_ard_3` and `ga_s2cm_ard_3` (DEA STAC `https://explorer.dea.ga.gov.au/stac`, unsigned `dea-public-data`), for the same acquisition, with nodata -999. The per-polygon NDVI median must be within 0.05 of `ndvi_median`, and correlation across the run's polygon rows must be above 0.95.

- Open research item from the design: the NBART scale factor (1e-4 per the dea-load-and-mask skill, not confirmed in STAC metadata). Confirm the scale and offset from product metadata and record them.
- Choose the clear-pixel mask (DEA fmask on the same pixels, or the pipeline's SCL clear mask) and state the choice in the module docstring.
- DEA ARD is expected in EPSG:32750 for these tiles; assert the CRS before comparing.
- Recent passes may only have provisional ARD; use the newest pass that has a matching final or provisional item.
- New `src/wetland_change/verify/ndvi.py`, wired into `verify_run`.

## Acceptance Criteria

- [ ] Offline test with synthetic arrays: NDVI medians 0.04 apart pass `ndvi_vs_dea_nbart`, medians 0.06 apart fail, and -999 pixels are excluded.
- [ ] Offline test: the correlation check over at least 5 synthetic polygon rows passes above 0.95 and fails below it.
- [ ] LEARNINGS.md gains a dated "DEA NBART scale" note stating the scale and offset found and their source.
- [ ] Live test marked `live`: the check scores the Thomsons polygon on the newest pass with a matching DEA ARD item and reports measured and reference medians.

## Implementation Plan

## Implementation Notes

## Questions
