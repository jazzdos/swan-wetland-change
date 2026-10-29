# 0002 Store three water signals per observation

Status: accepted, 2026-10-29.

## Context

On the 2026-10-27 pass over Thomsons Lake, NDWI > 0 found 5,845 water
pixels, SCL class 6 found 16,676 and DEA Sentinel-2 Water Observations
found 16,444. The textbook threshold is wrong for shallow, vegetated,
seasonal lakes, and the right threshold is an empirical question
(spike S2).

## Decision

Every observation row carries `water_ha_index` (configured index and
threshold), `water_ha_scl` (SCL class 6) and `dea_wo_agreement` (share of
mutually clear pixels where the pipeline and DEA agree, filled by the
verify step while the provisional product retains the pass). The index
medians (`ndwi_median`, `mndwi_median`, `ndvi_median`) are stored so a
different threshold can be evaluated without re-reading pixels.

## Consequences

Rows are wider but the method is auditable per row. Change detection
in Milestone 2 reads `water_ha_index` and reports `water_ha_scl` beside
it; disagreement between the two is itself a quality flag.
