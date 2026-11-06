---
id: st-73ad
title: Derive pixel area from the transform and pin the vector engine
type: chore
priority: P3
depends_on: []
discovered_from: st-ff89
touches: [src/wetland_change/stats.py, src/wetland_change/aoi.py, tests/test_stats.py, tests/test_aoi.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

src/wetland_change/stats.py:22 hard-codes PIXEL_AREA_HA = 0.01 and multiplies it into water_ha_index and water_ha_scl (stats.py:130-131); nothing checks the window transform against 10 m or the CRS for metric units. The value is right for today's 10 m EPSG:32750 inputs. src/wetland_change/aoi.py:42 calls gpd.read_file without an engine, so the reader follows whatever packages are installed. Found by the st-ff89 reproducibility audit, which fixes nothing.

## Acceptance Criteria

- [ ] Pixel area in hectares is computed from the window transform of the BandStack and the code raises when the CRS is not projected in metres or the pixel step is not 10 m.
- [ ] A test feeds a 20 m transform and asserts the error.
- [ ] stats.PIXEL_AREA_HA is removed or derived
- [ ] and tests/test_stats.py passes with the derived value.
- [ ] gpd.read_file in src/wetland_change/aoi.py passes engine="pyogrio".
- [ ] The four verification gates pass.

## Implementation Plan

## Implementation Notes

## Questions
