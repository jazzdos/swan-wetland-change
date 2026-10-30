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
updated: 2026-10-30
parked_complexity: routine
---
## Description

Verification matrix row "Index arithmetic" (design). The spyndex 0.12.0 cross-check exists in `tests/test_indices.py`; the dea-tools 0.4.10 `calculate_indices` cross-check is missing. Add dea-tools as a dev dependency if it installs under Python 3.12 without breaking the locked stack. `calculate_indices` works on xarray Datasets with DEA band names, so wrap the arrays accordingly. If dea-tools cannot be installed alongside the locked stack, park the story with the resolver error instead of vendoring code.

## Acceptance Criteria

- [ ] Offline test: NDWI, MNDWI and NDVI from `wetland_change.indices` equal dea-tools `calculate_indices` output at assert_allclose 1e-6 on synthetic arrays and on the fixture window.
- [ ] `uv sync --locked` succeeds with the new dev dependency.

## Implementation Plan

## Implementation Notes

## Questions

- 2026-10-30T00:04:47.711Z: planner failed: planner returned neither a complete plan+batches nor an unimplementable question. Its exploration found that dea-tools 0.4.10 resolves on Python 3.12 (83 packages added; the only existing locked version that moves is transitive python-dateutil 3.0.0 to 2.9.0.post0), but transitive geomad 1.0.0 (via odc-algo) has no macOS wheel, so on this Mac 'uv sync --locked' and the 'uv run pytest' gate build the sdist and fail with 'omp.h file not found'. Linux CI would use the cp312 wheel. Which way? (a) install libomp with Homebrew on this machine and keep dea-tools in the dev group; (b) put dea-tools in a separate dependency group outside default-groups so the gate never syncs it, and the cross-check test skips where it is not installed; (c) drop the dea-tools cross-check and keep spyndex only. The story is re-planned after the choice.
