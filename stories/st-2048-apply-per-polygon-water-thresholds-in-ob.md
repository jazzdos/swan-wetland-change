---
id: st-2048
title: Apply per-polygon water thresholds in observations and the DEA WO check
type: feature
epic: st-1d45
priority: P1
complexity: hard
depends_on: [st-afcf]
touches: [LEARNINGS.md, config/pipeline.toml, docs/decisions/0005-per-polygon-water-settings.md, src/wetland_change/config.py, src/wetland_change/stats.py, src/wetland_change/verify/run.py, src/wetland_change/verify/wo.py, tests/test_config.py, tests/test_stats.py, tests/test_verify.py]
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

# st-2048 plan: per-polygon water settings in observations and the DEA WO check

Worktree: `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-2048` (branch `story/st-2048`, at 40b3c50; baseline `tests/test_config.py tests/test_stats.py tests/test_verify.py` green).

## Checked against the code

- `src/wetland_change/config.py`: `WaterConfig` has `method: Literal["ndwi","mndwi"]`, `threshold`, `min_valid_fraction`, and no agreement_min and no overrides. Pydantic 2.14, mypy strict.
- `src/wetland_change/stats.py::summarise(polygon, scene, stack, planned, *, water: WaterConfig, run_id)` already receives the `AoiPolygon`, so it can resolve the polygon's setting itself.
- `src/wetland_change/pipeline.py::process_scene` passes `cfg.water` to `summarise`. **pipeline.py needs no change.** A `process_scene` test proves the wiring.
- `src/wetland_change/verify/wo.py::wo_check(..., water, wo_href, reader, scene_grid=None, agreement_min=0.91)` does not know the polygon id. `src/wetland_change/verify/run.py::_verify_scene._wo` calls it without agreement_min and then sets `detail["polygon_id"]` afterwards. **verify/run.py is not in the story's touches list, but a one-line change there is needed**: pass `polygon_id=polygon.polygon_id` to `wo_check`. Without it the verify flow never sees overrides.
- Polygon ids come from `aoi.py`: `ramsar-<objectid>` and `dea-<uid>`.
- Calibration values re-derived from `docs/research/2026-10-29-polygon-calibration.csv` match LEARNINGS:
  - ramsar-15: scl6 0.9682 (10 passes, worst 0.9384)
  - ramsar-28: ndwi -0.15 0.9438 (22 passes on 12 dates)
  - ramsar-56: mndwi 0.05 0.9795 (19 passes on 12 dates)
  - The 2026-10-12 ramsar-15 rows are 0.5162, 0.6145 and 0.9705.
- Fixture facts used by the tests. The Thomsons fixture polygon covers 44x44 = 1936 pixels, all clear and all SCL class 6:
  - `water_ha_index`: mndwi > -0.1 gives 1936 px (19.36 ha), ndwi > 0.0 gives 1125 px (11.25 ha), SCL 6 gives 1936 px.
  - `wo_check` against an all-wet WO gives agreement 1.0 at mndwi -0.1, 1125/1936 = 0.58110 at ndwi 0.0, and 1.0 at scl6.
- No golden or other test reads the repo `config/pipeline.toml` except `test_config.py` and the live tests. The live `test_water_agrees_with_dea_wo` calls `wo_check` without a polygon id, so it keeps the global setting at 0.91.
- st-b983 (the backfill) depends on this story, so the backfilled history will use the overrides.

## Interpretation

AC "reports it as the reference": the check reports the polygon's agreement_min as `Check.threshold` (the report's threshold column) and in `detail["agreement_min"]`. `Check.reference` stays the DEA WO href, as for every other check.

## Steps

1. **Config model and file** (`src/wetland_change/config.py`, `config/pipeline.toml`, `tests/test_config.py`).
   - Add a `WaterSetting` model:
     - fields: `method` in {ndwi, mndwi, scl6}, `threshold: float | None` in [-1, 1], and a required `agreement_min` in [0, 1]
     - `extra="forbid"` and frozen
     - an after-validator: scl6 takes no threshold, and an index method needs one
   - Change `WaterConfig`:
     - the global `method` stays ndwi or mndwi
     - the global `threshold` is bounded to [-1, 1]
     - new `agreement_min` field, default 0.91
     - new `overrides: dict[str, WaterSetting]`, with keys validated against `(ramsar|dea)-[A-Za-z0-9_]+`
     - new `for_polygon(polygon_id: str | None) -> WaterSetting` that returns the override if there is one, else the global setting
   - In the TOML:
     - add `agreement_min = 0.91` to `[water]`
     - add `[water.overrides.ramsar-15]` (scl6, 0.94), `[water.overrides.ramsar-28]` (ndwi, -0.15, 0.92) and `[water.overrides.ramsar-56]` (mndwi, 0.05, 0.95)
   - Tests prove:
     - the repo config holds exactly these three overrides with the LEARNINGS values, plus global agreement_min 0.91 (AC 1)
     - `load_config` rejects an override with an unknown method or a threshold outside [-1, 1] (AC 2), along with scl6 plus threshold, an index method without a threshold, agreement_min > 1, an unknown key and a malformed polygon id
     - the bounds -1.0 and 1.0 are accepted
     - `for_polygon` falls back to the global setting
     - a global threshold of 1.5 is rejected
2. **Docs** (`docs/decisions/0005-per-polygon-water-settings.md`, `LEARNINGS.md`). This step runs in parallel with step 1.
   - Write ADR 0005. It must:
     - name ramsar-15, ramsar-28 and ramsar-56 (AC 5)
     - include the settings table
     - include an "Amendment to 0002" section: `water_ha_index` is now the polygon's setting, and for ramsar-15 it equals `water_ha_scl`, so 0002's index-vs-SCL flag does not apply there
     - include a Limits section: August to October only, 12 dates or fewer per polygon, two-tile dates pooled twice, DEA S2 WO itself unvalidated, so agreement means consistency with DEA, not accuracy
     - record the consequence that pre-change rows used the global setting
     - cite the evidence hashes
   - In LEARNINGS.md (append-only), add two pieces of text:
     - a dated 2026-10-30 correction to the ramsar-15 mechanism, inserted before `### S9`
     - pre-registered hypothesis 5, the out-of-sample expectation for passes after 2026-10-29, inserted before `## Spike results`
3. **Observations** (`src/wetland_change/stats.py`, `tests/test_stats.py`).
   - Add `water_pixels(setting, stack, clear)`. For scl6 it returns clear & SCL 6; otherwise clear & index > threshold.
   - `summarise` uses `water_pixels(water.for_polygon(polygon.polygon_id), stack, clear)`.
   - Tests prove the following on the fixture (AC 3):
     - an overridden polygon gets `water_ha_index` from its own method and threshold (11.25 ha against a global of 19.36)
     - a polygon without an override is unchanged
     - an scl6 override gives `water_ha_index == water_ha_scl`
     - `process_scene` (pipeline.py) applies overrides per polygon within one scene
     - a synthetic unit test for `water_pixels`
4. **DEA WO check** (`src/wetland_change/verify/wo.py`, `src/wetland_change/verify/run.py`, `tests/test_verify.py`).
   - `wo_check` drops the `agreement_min` argument and takes `polygon_id: str | None = None`.
   - It resolves the setting with `water.for_polygon(polygon_id)`, scores with `water_pixels`, and passes or fails against the setting's agreement_min.
   - It reports that agreement_min as `Check.threshold` and records `method`, `threshold`, `agreement_min`, `override` and `polygon_id` in `detail`, in both the scored branch and the grid-differs branch.
   - `run.py` passes `polygon_id=polygon.polygon_id` and drops the post-hoc detail assignment.
   - Tests prove (AC 4):
     - the override's method and threshold are used (0.5811 for the overridden polygon against 1.0 without one)
     - agreement_min alone flips the result: 0.55 passes and 0.60 fails at the same measured value
     - the reported threshold is the override's agreement_min
     - an scl6 override's measured agreement equals `scl_agreement`
     - the grid-differs branch reports the override's agreement_min
     - `verify_run` passes the polygon id through: scl6 at 0.97 is reported for ramsar-52
   - `test_wo_check_branches` is updated to `WaterConfig(agreement_min=0.5)`.

## Batches

- Batch 1: t1-config and t2-docs, which touch disjoint files.
- Batch 2: t3-summarise, which needs `WaterSetting` and `for_polygon`.
- Batch 3: t4-wo-check, which needs `water_pixels` from stats.py.

## Out of scope / discovered work for the orchestrator

- st-ced9 (WO values other than 0 and 128) is not touched.
- Observation rows do not record the water setting. Rows for ramsar-15, ramsar-28 and ramsar-56 written before this change used the global setting, and no command recomputes items already in the ledger (backfill skips seen keys). ADR 0005 records this. Consider a follow-up story if production rows exist.
- Override ids are not checked against the loaded AOI polygon set, so a typo silently falls back to the global setting. A CLI-level warning in `cli._load` would catch it; it is outside this story's touches.
- The design doc matrix row still says WO agreement 0.95 (docs/plans is outside touches).
- Hypothesis 5's evaluation rule (assessed at ten scored passes after 2026-10-29, at most one failing pass in ten) was specified by the planner. Jarrod may want to adjust it before the first new pass is scored.

## Implementation Notes

- 2026-10-29T15:47:31.556Z: From st-afcf (2026-10-29): ramsar-15's best setting is SCL class 6 (pooled agreement 0.9682). WaterConfig accepts only ndwi and mndwi, so applying it means adding an scl6 method for that polygon. The best index setting for ramsar-15 is ndwi -0.45 at 0.7814 (agreement_min 0.76). Choosing between them is a product decision: confirm with Jarrod before implementing, or park.
- 2026-10-30T00:54:49.297Z: Human decision 2026-10-30 (Jarrod): option (a). ramsar-15 uses SCL class 6 (method scl6, no threshold, agreement_min 0.94); ramsar-28 ndwi -0.15 (agreement_min 0.92) and ramsar-56 mndwi 0.05 (agreement_min 0.95) as in LEARNINGS.md. Basis: no agreed literature or industry method for choosing a water index threshold (optimal thresholds vary by site and water type; Ji et al. 2009, Fisher et al. 2016), so the per-polygon choice stands. An independent check on 2026-10-30 reproduced every LEARNINGS figure from docs/research/2026-10-29-polygon-calibration.csv and a live re-run of ramsar-15 on 2026-10-12 (0.5162, 0.6145, 0.9705); leave-one-date-out agreement 0.9682 / 0.9434 / 0.9788 with unchanged winners. Correct the LEARNINGS.md mechanism for ramsar-15 (append a dated correction; do not rewrite the original): it is not near-threshold water. On the live pass green BOA reflectance is <= 0 on 74 percent of WO-wet pixels (median -0.0006) and missed water has MNDWI median -1.2, so no index threshold recovers it. decision 0005 must also record: (1) for ramsar-15 water_ha_index equals water_ha_scl, so decision 0002's index-vs-SCL flag does not apply there; (2) the calibration covers August to October only (12 dates or fewer per polygon; two-tile dates were pooled twice) and DEA S2 WO is itself unvalidated, so agreement is consistency with DEA, not accuracy. Before the first new pass is scored, pre-register in LEARNINGS.md the expected out-of-sample result for passes after 2026-10-29 (ramsar-15 scl6 at agreement_min 0.94), per the AGENTS.md rule. The spike script is untracked at scratch/spikes/polygon_calibrate.py (sha256 99f2cab0...).

## Questions

- 2026-10-29T19:33:50.400Z: Which water method should ramsar-15 use? (a) SCL class 6: best agreement with DEA WO (pooled 0.9682, min 0.94) but WaterConfig accepts only ndwi and mndwi, so this adds a third method, scl6, used only by this override. (b) ndwi at -0.45: no new method, but agreement drops to 0.7814 (min 0.76), so its agreement_min would be about 0.76. (c) Leave ramsar-15 on the global mndwi -0.1 and override only ramsar-28 (ndwi -0.15) and ramsar-56 (mndwi 0.05). The ramsar-28 and ramsar-56 values are not in question.
