---
id: st-2b8a
title: Add a freshness check for the scheduled job
type: feature
epic: st-f849
priority: P2
depends_on: [st-d4a8]
touches: [src/wetland_change/verify/freshness.py, src/wetland_change/cli.py, tests/test_freshness.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Verification matrix row "Scheduled job alive" (design): the ledger matches Earth Search and Copernicus counts per tile over 30 days, and the newest processed item is under 7 days old.

Add `src/wetland_change/verify/freshness.py` and a `wetland-change freshness` command that exits non-zero when any freshness check fails, so the weekly workflow can open an issue. Reuse the Copernicus listing from `src/wetland_change/verify/copernicus.py` (the discovery-check story). Allow 24 hours of latency: items under 24 hours old may be missing from either side.

## Acceptance Criteria

- [ ] Offline test with fake clients: when the newest processed item is 8 days old, `freshness_newest_item` fails; at 6 days it passes.
- [ ] Offline test: a tile whose 30-day ledger count differs from the Earth Search count, ignoring items under 24 hours old, fails `freshness_count_vs_earth_search`. The same holds for `freshness_count_vs_copernicus`.
- [ ] `uv run wetland-change freshness --help` exits 0, and an offline CLI test shows the command exits non-zero when any freshness check fails.
- [ ] Live test marked `live`: 30-day per-tile counts for the six tiles come back from both catalogues without error.

## Implementation Plan

## Implementation Notes

## Questions
