---
id: st-d457
title: Record a one-off dea-tools index comparison and keep spyndex as the standing check
type: chore
epic: st-1d45
priority: P3
depends_on: []
touches: [LEARNINGS.md, docs/plans/**, scripts/**, pyproject.toml]
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

- 2026-10-30T00:54:59.352Z: Human decision 2026-10-30 (Jarrod): option (c) plus a one-off comparison. This SUPERSEDES both acceptance criteria above: no dea-tools dependency, no standing dea-tools test, and pyproject.toml dependencies and uv.lock stay unchanged. Scope now: (1) pre-register the expected result in LEARNINGS.md before running (NDWI, MNDWI, NDVI from wetland_change.indices equal dea-tools 0.4.10 calculate_indices at assert_allclose 1e-6); (2) a script under scripts/ downloads the pinned dea_tools-0.4.10-py3-none-any.whl from PyPI, checks its sha256, and loads dea_tools.bandindices from it (the module imports only numpy and warnings, so none of dea-tools' 83 dependencies are needed); calculate_indices needs an xarray Dataset and xarray is not in the project env, so run it with 'uv run --with xarray' (overlay only, no lock change); use collection='ga_s2_3' (nbart_green=B03, nbart_red=B04, nbart_nir_1=B08, nbart_swir_2=B11; DEA swir_2 is S2 B11) on synthetic arrays and the fixture window; (3) record the result, wheel sha256 and command in LEARNINGS.md; (4) amend the design's 'Index arithmetic' matrix row and reference list (docs/plans/2026-10-29-swan-wetland-change-design.md lines 225 and 365) to spyndex as the standing test plus the recorded one-off dea-tools comparison. Watch: mypy strict covers scripts/, so static xarray or dea_tools imports need a [[tool.mypy.overrides]] ignore_missing_imports entry (a pyproject.toml tool-config change only) or importlib loading; ruff must pass on the script. The spyndex test in tests/test_indices.py stays as is.

## Questions

- 2026-10-30T00:04:47.711Z: planner failed: planner returned neither a complete plan+batches nor an unimplementable question. Its exploration found that dea-tools 0.4.10 resolves on Python 3.12 (83 packages added; the only existing locked version that moves is transitive python-dateutil 3.0.0 to 2.9.0.post0), but transitive geomad 1.0.0 (via odc-algo) has no macOS wheel, so on this Mac 'uv sync --locked' and the 'uv run pytest' gate build the sdist and fail with 'omp.h file not found'. Linux CI would use the cp312 wheel. Which way? (a) install libomp with Homebrew on this machine and keep dea-tools in the dev group; (b) put dea-tools in a separate dependency group outside default-groups so the gate never syncs it, and the cross-check test skips where it is not installed; (c) drop the dea-tools cross-check and keep spyndex only. The story is re-planned after the choice.
