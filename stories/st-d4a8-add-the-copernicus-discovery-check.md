---
id: st-d4a8
title: Add the Copernicus discovery check
type: feature
epic: st-1d45
priority: P2
depends_on: []
touches: [src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_verify_copernicus.py, tests/test_verify.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Verification matrix row "Discovery finds every scene" (design): list CDSE STAC `https://stac.dataspace.copernicus.eu/v1`, collection `sentinel-2-l2a` (listing is free; no asset access needed). Per tile per month, item counts and ESA product names must match Earth Search Collection 1 under the same cloud threshold and AOI, allowing 24 hours of latency.

- Earth Search items map to ESA product names through `s2:product_uri`; CDSE item ids are product names.
- Compare on the datatake. Strip the processing baseline and generation time, because Collection 1 and CDSE products of one datatake differ there. Deduplicate CDSE datatakes that appear more than once.
- The check covers the window of the run being verified, not history. CDSE holds 2022 items that Collection 1 lacks (LEARNINGS.md, S4).
- Implement as `src/wetland_change/verify/copernicus.py`, wired into `verify_run` through `_guard` in `src/wetland_change/verify/run.py`.
- Spike S4's working CDSE queries are in the untracked `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/feature/wetland-change-pipeline/scratch/spikes/s4_backfill_count.py`.

## Acceptance Criteria

- [ ] Offline test with fake clients: matching listings pass `discovery_vs_copernicus`, and a product in CDSE but missing from Earth Search, older than 24 hours, fails with the product named in the detail.
- [ ] Offline test: a product newer than 24 hours that is missing from Earth Search does not fail the check.
- [ ] Offline test: two products that differ only in processing baseline or generation time count as the same product.
- [ ] Offline test: `verify_run` emits `discovery_vs_copernicus` checks per tile.
- [ ] Live test marked `live`: tile 50HLK for 2026-10 is listed from both catalogues and scored.

## Implementation Plan

## Implementation Notes

## Questions
