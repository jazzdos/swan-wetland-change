---
id: st-5acd
title: Add missing data/SOURCES.md rows for references and fixtures
type: chore
priority: P3
depends_on: []
discovered_from: st-ff89
touches: [data/SOURCES.md, tests/test_repo_hygiene.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

AGENTS.md requires a data/SOURCES.md row for every dataset in the commit that first uses it. The code reads Planetary Computer sentinel-2-l2a (src/wetland_change/verify/pixels.py:18) and Copernicus Data Space STAC sentinel-2-l2a (src/wetland_change/verify/copernicus.py:45), and README.md lists both, but data/SOURCES.md has no row for either. The committed fixtures under tests/fixtures/thomsons_20261027/ and tests/fixtures/aoi/ also have no row. Found by the st-ff89 reproducibility audit, which fixes nothing.

## Acceptance Criteria

- [ ] data/SOURCES.md has a row for Planetary Computer sentinel-2-l2a with URL
- [ ] licence
- [ ] fetch date
- [ ] checksum or n/a reason
- [ ] CRS and redistribute_public.
- [ ] data/SOURCES.md has the same row for Copernicus Data Space STAC sentinel-2-l2a.
- [ ] data/SOURCES.md has rows for tests/fixtures/thomsons_20261027/ and tests/fixtures/aoi/ with the sha256 of each file.
- [ ] A test in tests/ asserts that every host named in src and scripts appears in data/SOURCES.md.
- [ ] The four verification gates pass.

## Implementation Plan

## Implementation Notes

## Questions
