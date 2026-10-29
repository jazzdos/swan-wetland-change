---
id: st-1d45
title: "Milestone 2: remaining verification matrix rows"
type: epic
priority: P2
depends_on: []
touches: []
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Milestone 2 verification: the remaining rows of the "Known-good verification matrix" in `docs/plans/2026-10-29-swan-wetland-change-design.md`. Milestone 1 already covers reflectance scaling, SCL class shares, Planetary Computer pixels, DEA S2 Water Observations agreement and the GeoParquet validator. Still to build: discovery against Copernicus, water extent history against DEA Waterbodies (after spike S9), NDVI against DEA NBART, the dea-tools index cross-check, and the idempotency golden run.

Decision at board approval on 2026-10-29: calibrate ramsar-15, ramsar-28 and ramsar-56 separately, because they fail the DEA S2 Water Observations check (handoff, State).

Check pattern to follow: `src/wetland_change/verify/` with the `Check` dataclass and `write_report` in `checks.py`, `_guard` in `run.py` turning exceptions into error checks, and one module per matrix row (`wo.py`, `pixels.py`, `scl.py`, `scaling.py`). Reports go to `verification/<run_id>.json` in the store and Markdown under `docs/research/`.

## Implementation Plan

## Implementation Notes

## Questions
