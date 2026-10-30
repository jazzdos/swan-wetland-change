---
id: st-2048
title: Apply per-polygon water thresholds in observations and the DEA WO check
type: feature
epic: st-1d45
priority: P1
complexity: hard
depends_on: [st-afcf]
touches: [config/**, src/wetland_change/config.py, src/wetland_change/stats.py, src/wetland_change/pipeline.py, src/wetland_change/verify/wo.py, docs/decisions/**, LEARNINGS.md, tests/test_config.py, tests/test_stats.py, tests/test_verify.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-30
parked_complexity: hard
---
## Description

Apply the per-polygon values recorded by the calibration spike (LEARNINGS.md, "Per-polygon water calibration"). Today `[water]` in `config/pipeline.toml` holds one global method and threshold (`src/wetland_change/config.py`).

- Add per-polygon overrides keyed by polygon id: method, threshold and agreement_min, validated by the config loader.
- `water_ha_index` for an overridden polygon uses its override (`summarise` in `src/wetland_change/stats.py`, called from `src/wetland_change/pipeline.py`).
- `src/wetland_change/verify/wo.py` scores each polygon against its own threshold and agreement_min.
- Polygons without an override keep the global setting.
- Record the change as `docs/decisions/0005-*.md`, noting how it amends decision 0002.

## Acceptance Criteria

- [ ] `config/pipeline.toml` holds overrides for ramsar-15, ramsar-28 and ramsar-56 whose values match LEARNINGS.md "Per-polygon water calibration".
- [ ] Offline test: the config loader rejects an override with an unknown method name or a threshold outside [-1, 1].
- [ ] Offline test: on the fixture, a polygon with an override gets `water_ha_index` from its own method and threshold, and a polygon without one is unchanged.
- [ ] Offline test: `water_vs_dea_s2_wo` uses the polygon's override agreement_min for pass or fail and reports it as the reference.
- [ ] `docs/decisions/0005-*.md` exists and names the three overridden polygons.

## Implementation Plan

## Implementation Notes

- 2026-10-29T15:47:31.556Z: From st-afcf (2026-10-29): ramsar-15's best setting is SCL class 6 (pooled agreement 0.9682). WaterConfig accepts only ndwi and mndwi, so applying it means adding an scl6 method for that polygon. The best index setting for ramsar-15 is ndwi -0.45 at 0.7814 (agreement_min 0.76). Choosing between them is a product decision: confirm with Jarrod before implementing, or park.
- 2026-10-30T00:54:49.297Z: Human decision 2026-10-30 (Jarrod): option (a). ramsar-15 uses SCL class 6 (method scl6, no threshold, agreement_min 0.94); ramsar-28 ndwi -0.15 (agreement_min 0.92) and ramsar-56 mndwi 0.05 (agreement_min 0.95) as in LEARNINGS.md. Basis: no agreed literature or industry method for choosing a water index threshold (optimal thresholds vary by site and water type; Ji et al. 2009, Fisher et al. 2016), so the per-polygon choice stands. An independent check on 2026-10-30 reproduced every LEARNINGS figure from docs/research/2026-10-29-polygon-calibration.csv and a live re-run of ramsar-15 on 2026-10-12 (0.5162, 0.6145, 0.9705); leave-one-date-out agreement 0.9682 / 0.9434 / 0.9788 with unchanged winners. Correct the LEARNINGS.md mechanism for ramsar-15 (append a dated correction; do not rewrite the original): it is not near-threshold water. On the live pass green BOA reflectance is <= 0 on 74 percent of WO-wet pixels (median -0.0006) and missed water has MNDWI median -1.2, so no index threshold recovers it. decision 0005 must also record: (1) for ramsar-15 water_ha_index equals water_ha_scl, so decision 0002's index-vs-SCL flag does not apply there; (2) the calibration covers August to October only (12 dates or fewer per polygon; two-tile dates were pooled twice) and DEA S2 WO is itself unvalidated, so agreement is consistency with DEA, not accuracy. Before the first new pass is scored, pre-register in LEARNINGS.md the expected out-of-sample result for passes after 2026-10-29 (ramsar-15 scl6 at agreement_min 0.94), per the AGENTS.md rule. The spike script is untracked at scratch/spikes/polygon_calibrate.py (sha256 99f2cab0...).

## Questions

- 2026-10-29T19:33:50.400Z: Which water method should ramsar-15 use? (a) SCL class 6: best agreement with DEA WO (pooled 0.9682, min 0.94) but WaterConfig accepts only ndwi and mndwi, so this adds a third method, scl6, used only by this override. (b) ndwi at -0.45: no new method, but agreement drops to 0.7814 (min 0.76), so its agreement_min would be about 0.76. (c) Leave ramsar-15 on the global mndwi -0.1 and override only ramsar-28 (ndwi -0.15) and ramsar-56 (mndwi 0.05). The ramsar-28 and ramsar-56 values are not in question.
