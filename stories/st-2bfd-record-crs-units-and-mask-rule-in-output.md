---
id: st-2bfd
title: "Record CRS, units and mask rule in output metadata"
type: bug
priority: P2
depends_on: []
discovered_from: st-ff89
touches: [src/wetland_change/outputs/geoparquet.py, src/wetland_change/outputs/changes.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, tests/test_geoparquet.py, tests/test_manifest.py, tests/test_golden_run.py, README.md]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

AGENTS.md requires the source CRS, operation CRS (EPSG:32750) and units to be recorded with every output. The observation and change GeoParquet files (src/wetland_change/outputs/geoparquet.py:57-62) carry only the geometry CRS EPSG:4326, and RunManifest (src/wetland_change/manifest.py) has no operation_epsg field. The SCL classes dropped by the clear-pixel rule (src/wetland_change/mask.py:26) and the per-polygon water method and threshold behind water_ha_index are written to no output; only config_sha256 in the manifest points at the config. Found by the st-ff89 reproducibility audit, which fixes nothing.

## Acceptance Criteria

- [ ] Every observation and change Parquet file written by the pipeline has footer key-value metadata naming source_epsg 32750
- [ ] operation_epsg 32750 and geometry_epsg 4326.
- [ ] The footer metadata gives the unit of every non-geometry numeric column (hectares for water_ha_index and water_ha_scl
- [ ] unitless for indices
- [ ] fractions and z).
- [ ] The footer metadata names the SCL classes dropped by the clear-pixel mask and the water method and threshold used for the polygon rows in that file.
- [ ] RunManifest has an operation_epsg field that is written to runs/<run_id>.json.
- [ ] A test in tests/test_geoparquet.py reads the footer metadata back and asserts these keys
- [ ] and the byte-identical rerun test in tests/test_golden_run.py still passes.
- [ ] The four verification gates pass.

## Implementation Plan

## Implementation Notes

## Questions
