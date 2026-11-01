---
id: st-c6d5
title: Add the DEA Waterbodies history check
type: feature
epic: st-1d45
priority: P2
depends_on: [st-2522]
touches: [config/pipeline.toml, data/SOURCES.md, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/verify/run.py, src/wetland_change/verify/waterbodies.py, tests/fixtures/waterbodies/qd635epws_v3_excerpt.csv, tests/test_cli.py, tests/test_config.py, tests/test_live_waterbodies.py, tests/test_verify.py, tests/test_verify_waterbodies.py]
exclusive: false
created: 2026-10-29
updated: 2026-11-01
---
## Description

Verification matrix row "Water extent, history" (design). Per lake, compare the pipeline wet fraction over the DEA waterbody polygon with DEA Waterbodies v3 wet fraction on passes 1 to 3 days apart, within the tolerance recorded in LEARNINGS.md "S9 historical tolerance". Also check that Spearman correlation over all paired passes is at least 0.9; hypothesis 4 uses the same pairing.

- Pipeline side: observation rows with `aoi_layer == "dea_waterbody"` (loaded by `src/wetland_change/aoi.py` from `waterbodies_path`). Wet fraction is `water_ha_index` over the polygon area in hectares.
- Lakes and uids: Thomsons qd635epws_v3, Forrestdale qd63n1ww5_v3, Lake Clifton qd4m2n3rj_v3, Lake Preston qd4k2967m_v3. Peel Inlet and Harvey Estuary have none. The CSV URL pattern is in the design's Verified facts.
- New `src/wetland_change/verify/waterbodies.py`. Emit per-pass checks plus one Spearman check per lake when there are at least 10 pairs; with fewer, emit a skipped check with a reason.
- Callable over a date range (the backfill spike uses it) and from `verify_run` for a run's scenes.
- The tolerance lives in `config/pipeline.toml`.

## Acceptance Criteria

- [ ] Offline test with a saved CSV excerpt fixture: a pass 2 days from a Waterbodies observation passes `water_vs_dea_waterbodies` when the wet-fraction difference is inside the tolerance, and fails when it is outside.
- [ ] Offline test: a pipeline row with no Waterbodies observation within 3 days produces no paired check.
- [ ] Offline test: Spearman is computed per lake over at least 10 synthetic pairs and compared with 0.9, and fewer than 10 pairs gives a skipped check with a reason.
- [ ] The tolerance in `config/pipeline.toml` equals the value in LEARNINGS.md "S9 historical tolerance".
- [ ] Live test marked `live`: the Thomsons CSV downloads and parses.

## Implementation Plan

## Findings from the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-c6d5)

- `src/wetland_change/verify/waterbodies.py` does not exist. `verify/` holds checks.py (Check dataclass: name, passed: bool|None, measured, threshold, reference, detail), run.py (verify_run), ndvi.py (a correlation check to copy the skip pattern from), wo.py, scl.py, pixels.py, copernicus.py, scaling.py.
- `config/pipeline.toml` has no verify section. `PipelineConfig` (src/wetland_change/config.py) has stac, aoi, water, output, catalogue.
- LEARNINGS.md "### S9 historical tolerance (2026-10-30)" states `Chosen tolerance: 10 percentage points.` (one line). LEARNINGS is append only, so do not edit it.
- Design Verified facts: CSV at `https://data.dea.ga.gov.au/derivative/dea_waterbodies/3-0-0/timeseries/<uid[:4]>/<uid>.csv`. The live file has header `date,pc_wet,px_wet`. Dates look like `2026-10-10T02:05:30Z`. `pc_wet` is a PERCENT (90.41 means 0.9041) and is blank on unusable passes. Live rows seen: `1986-08-16T01:33:15Z,76.29,1638.0`, `1986-08-25T01:26:44Z,75.27,1616.0`, `1987-05-24T01:29:30Z,,`, `1987-05-31T01:35:52Z,,`, `2026-10-09T02:11:46Z,,`, `2026-10-10T02:05:30Z,90.41,1941.0`, `2026-10-17T02:11:40Z,,`. Also `2022-12-17` is 0.9008 as a fraction (docs/research/2026-10-30-waterbodies-tolerance.csv).
- Observation parquet files are `observations/year=YYYY/tile=T/obs_<item_id>.parquet` (src/wetland_change/outputs/geoparquet.py, `observation_path`). Columns include polygon_id (`dea-<uid>`), aoi_layer (`dea_waterbody`), item_id, datetime (UTC), valid_fraction, water_ha_index. Their `water_ha_index` counts clear pixels only.
- `AoiPolygon.geometry` is in EPSG:32750, so area in hectares is `geometry.area / 1e4`. `load_waterbodies` is in aoi.py. The CLI `_load` only loads Ramsar polygons, so dea_waterbody observation rows only exist if a caller adds those polygons. Do NOT change the CLI or the pipeline (it would change golden-run outputs).
- `data/SOURCES.md` needs a row for the Waterbodies CSV timeseries in this commit (repo rule).
- scipy is not a dependency. Compute Spearman with pandas average ranks plus `np.corrcoef`.

## Design decisions

- Check names: per pass `water_vs_dea_waterbodies`; per lake `water_spearman_vs_dea_waterbodies`.
- Wet fraction for the pipeline = `water_ha_index / polygon_area_ha`. For DEA = `pc_wet / 100`. The difference is `abs(pipeline - dea) * 100` percentage points, passed when `<= tolerance_pp`.
- Pairing: each pipeline row (aoi_layer dea_waterbody, uid in the lake table) pairs with the DEA row (non-blank pc_wet) whose UTC calendar date is nearest, within `max_day_gap` (3) days. Same-day is allowed. A tie goes to the earlier DEA date. No DEA row within the gap means no pass check at all (the count goes into the lake Spearman detail as `n_unpaired`).
- A pipeline row with `valid_fraction < cfg.water.min_valid_fraction` gives a skipped per-pass check with a reason, and is excluded from Spearman.
- Spearman per lake (lakes limited to uids that have a polygon in the input): at least `spearman_min_pairs` (10) scored pairs gives `passed = rho >= spearman_min` (0.9), `measured = rho`, `threshold = 0.9`. Fewer pairs gives a skipped check (passed None) with `detail["reason"]` and `n_pairs`. A constant series gives a skipped check with a reason.
- Config: new `[verify.waterbodies]` table with `tolerance_pp = 10.0`, `max_day_gap = 3`, `spearman_min = 0.9`, `spearman_min_pairs = 10`.
- A per-lake CSV load failure gives a skipped check carrying the error (do not raise).
- `verify_run` runs the history check only when the run's scenes have dea_waterbody observation rows and a waterbody polygon is supplied. Otherwise it adds no check (so existing tests are unchanged) and logs at info.

## Steps

1. Config (tests/test_config.py, src/wetland_change/config.py, config/pipeline.toml).
   - Test: `config/pipeline.toml` loads with `cfg.verify.waterbodies.tolerance_pp == 10.0`.
   - Test: parse LEARNINGS.md, take the text after `### S9 historical tolerance`, regex `Chosen tolerance: (\d+(?:\.\d+)?) percentage points`, and assert it equals the config value (AC 4).
   - Test: a config without a `[verify]` table takes the defaults.
   - Test: `tolerance_pp <= 0` is rejected.
2. Module `src/wetland_change/verify/waterbodies.py` with offline tests in `tests/test_verify_waterbodies.py` and fixture `tests/fixtures/waterbodies/qd635epws_v3_excerpt.csv`.
   - Tests for AC 1: a pass 2 days from the 2026-10-10 DEA row (pipeline wet fraction within 10 pp of 0.9041) passes. A pass outside the tolerance fails.
   - Test for AC 2: a pipeline row on 2026-10-14 or later yields no pass check, and the row with only blank DEA rows within 3 days yields no pass check.
   - Tests for AC 3: Spearman over 12 synthetic pairs gives measured rho compared with 0.9, both a passing monotonic case and a failing shuffled case, and 9 pairs gives a skipped check with a reason.
   - Further tests: parse_timeseries drops blank rows and scales percent to fraction; low valid_fraction is skipped; date range filtering; loader exception gives a skipped check.
3. Wire into `verify_run` (src/wetland_change/verify/run.py), with a test in tests/test_verify.py. Add the SOURCES.md row and the live test.
   - The integration test writes a dea_waterbody observation file for the fixture scene and injects a loader. It asserts the check is present and scored, and that no check appears when there are no waterbody rows.
   - Live test (AC 5): `tests/test_live_waterbodies.py`, marked `live`, downloads the Thomsons CSV, parses it, and asserts the 2022-12-17 row is 0.9008.

Verification order (each as its own command): ruff check, ruff format --check, mypy, pytest.

## Implementation Notes

## Questions
