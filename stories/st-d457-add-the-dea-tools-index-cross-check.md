---
id: st-d457
title: Add the dea-tools index cross-check
type: chore
epic: st-1d45
priority: P3
depends_on: []
touches: [tests/test_indices.py, pyproject.toml, uv.lock]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Verification matrix row "Index arithmetic" (design). The spyndex 0.12.0 cross-check exists in `tests/test_indices.py`; the dea-tools 0.4.10 `calculate_indices` cross-check is missing. Add dea-tools as a dev dependency if it installs under Python 3.12 without breaking the locked stack. `calculate_indices` works on xarray Datasets with DEA band names, so wrap the arrays accordingly. If dea-tools cannot be installed alongside the locked stack, park the story with the resolver error instead of vendoring code.

## Acceptance Criteria

- [ ] Offline test: NDWI, MNDWI and NDVI from `wetland_change.indices` equal dea-tools `calculate_indices` output at assert_allclose 1e-6 on synthetic arrays and on the fixture window.
- [ ] `uv sync --locked` succeeds with the new dev dependency.

## Implementation Plan

## Implementation Notes

## Questions
