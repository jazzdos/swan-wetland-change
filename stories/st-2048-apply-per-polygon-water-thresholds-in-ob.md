---
id: st-2048
title: Apply per-polygon water thresholds in observations and the DEA WO check
type: feature
epic: st-1d45
priority: P1
complexity: hard
depends_on: [st-afcf]
touches: [config/**, src/wetland_change/config.py, src/wetland_change/stats.py, src/wetland_change/pipeline.py, src/wetland_change/verify/wo.py, docs/decisions/**, tests/test_config.py, tests/test_stats.py, tests/test_verify.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
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

## Questions

- 2026-10-29T19:33:50.400Z: Which water method should ramsar-15 use? (a) SCL class 6: best agreement with DEA WO (pooled 0.9682, min 0.94) but WaterConfig accepts only ndwi and mndwi, so this adds a third method, scl6, used only by this override. (b) ndwi at -0.45: no new method, but agreement drops to 0.7814 (min 0.76), so its agreement_min would be about 0.76. (c) Leave ramsar-15 on the global mndwi -0.1 and override only ramsar-28 (ndwi -0.15) and ramsar-56 (mndwi 0.05). The ramsar-28 and ramsar-56 values are not in question.
