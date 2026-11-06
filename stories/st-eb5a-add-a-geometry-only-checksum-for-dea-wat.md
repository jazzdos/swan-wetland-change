---
id: st-eb5a
title: Add a geometry-only checksum for DEA Waterbodies
type: chore
priority: P3
depends_on: []
discovered_from: st-ff89
touches: [scripts/fetch_aoi.py, tests/test_fetch_aoi.py, data/SOURCES.md]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

A fetch on 2026-11-06 gave checksum 5e83c045 against the recorded 7d993aa8 (data/SOURCES.md:7). A comparison with the 2026-11-02 backfill copy found 1404 features with the same uids and identical geometry; only dt_wetobs, dt_satpass, dt_updated and wet_sa_m2 differ. The stable_geojson_checksum in scripts/fetch_aoi.py:93-115 covers those refreshable properties, so a DEA refresh changes it and a fresh clone cannot confirm it holds the same polygons. Found by the st-ff89 reproducibility audit, which fixes nothing.

## Acceptance Criteria

- [ ] scripts/fetch_aoi.py prints a second checksum over the sorted uid and geometry of every feature.
- [ ] Two payloads that differ only in dt_updated or wet_sa_m2 give the same geometry checksum
- [ ] shown by a test in tests/test_fetch_aoi.py.
- [ ] Two payloads that differ in one feature's geometry give different geometry checksums
- [ ] shown by a test.
- [ ] The DEA Waterbodies row in data/SOURCES.md records both checksums and says what each covers.
- [ ] The four verification gates pass.

## Implementation Plan

## Implementation Notes

## Questions
