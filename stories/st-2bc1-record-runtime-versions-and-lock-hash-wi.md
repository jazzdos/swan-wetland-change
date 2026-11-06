---
id: st-2bc1
title: Record runtime versions and lock hash with each run
type: task
priority: P2
depends_on: []
discovered_from: st-ff89
touches: [src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/verify/run.py, tests/test_manifest.py, tests/test_pipeline.py, tests/test_verify.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

The run manifest records package_version (a constant 0.1.0) and config_sha256 (src/wetland_change/manifest.py:38-39, src/wetland_change/pipeline.py:163-164). It records no Python, GDAL, PROJ, geopandas, rasterio or pyarrow version, no uv.lock hash and no git commit, and the verification report records none either. A result cannot be tied to the environment that produced it. Found by the st-ff89 reproducibility audit, which fixes nothing.

## Acceptance Criteria

- [ ] The run manifest JSON has a runtime object with the Python
- [ ] GDAL
- [ ] PROJ
- [ ] geopandas
- [ ] rasterio
- [ ] pyarrow and numpy versions.
- [ ] The run manifest JSON has the sha256 of uv.lock and the git commit when the code runs inside a git checkout
- [ ] and null otherwise.
- [ ] The verification JSON report and the Markdown report carry the same runtime object.
- [ ] A recovered manifest leaves the new fields empty
- [ ] like package_version and config_sha256.
- [ ] Tests in tests/test_manifest.py and tests/test_verify.py assert the fields.
- [ ] The four verification gates pass.

## Implementation Plan

## Implementation Notes

## Questions
