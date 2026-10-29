---
id: st-8228
title: Add month-of-year baseline and robust z scoring
type: feature
epic: st-70d1
priority: P1
complexity: hard
depends_on: []
touches: [src/wetland_change/change.py, tests/test_change.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

New pure module `src/wetland_change/change.py` (design, Change detection): a baseline per polygon and month of year holding the median and MAD of `water_ha_index` and `ndvi_median`, robust z scoring, and a flag when absolute z is above 3 and `valid_fraction` is above 0.8 (`[water] min_valid_fraction` in `config/pipeline.toml`). Every scored row carries the baseline values it was scored against. Use the 1.4826 MAD scale constant.

Seams (design, Observation row schema): a polygon straddling a tile seam has one row per scene with `scene_coverage` below 1, and "a daily aggregate per polygon weights by valid pixels". Partial-coverage rows are not comparable to full rows, so score one aggregate per polygon per acquisition date, weighted by `n_clear`, and document the combining rule in the docstring.

Inputs follow the observation schema (`ObservationRow` in `src/wetland_change/stats.py`). A zero MAD or too few baseline samples must not raise or produce an infinite z: such rows come back unflagged with a reason. No I/O here; writing change files is a separate story.

## Acceptance Criteria

- [ ] `tests/test_change.py` passes and covers every criterion below with synthetic frames.
- [ ] The baseline for a polygon-month equals the numpy median and 1.4826 times the median absolute deviation of that polygon-month's values (assert_allclose at 1e-9).
- [ ] Rows with `valid_fraction` at or below 0.8 are excluded from the baseline and never flagged.
- [ ] A value 4 robust standard deviations below the baseline median is flagged with z below -3; a value 2 robust standard deviations away is not flagged.
- [ ] A baseline with MAD 0, or with fewer samples than the module's minimum, yields an unflagged row with a non-null reason and a finite or null z.
- [ ] Two same-day rows of one polygon with `scene_coverage` 0.4 and 0.6 produce exactly one scored row for that polygon and date.
- [ ] Each scored row carries the baseline median, MAD and sample count used.

## Implementation Plan

## st-8228 plan: month-of-year baseline and robust z scoring

Worktree: `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-8228` (branch `story/st-8228`, clean, based on `e4e53c2`).

### Pointers checked against the worktree
- `ObservationRow` is in `src/wetland_change/stats.py`. It has `polygon_id, item_id, datetime, tile, scene_coverage, n_pixels, n_clear, valid_fraction, water_ha_index, ndvi_median`, plus columns this story does not use. `valid_fraction = n_clear / n_pixels` (0.0 when n_pixels is 0).
- `OBSERVATION_COLUMNS` and `rows_to_frame` are in `src/wetland_change/outputs/geoparquet.py`. They define the frame shape that the downstream story st-c8ca reads back from the store.
- `[water] min_valid_fraction = 0.8` is set in `config/pipeline.toml` and read as `WaterConfig.min_valid_fraction` in `src/wetland_change/config.py`.
- `src/wetland_change/change.py` and `tests/test_change.py` do not exist yet, and no prerequisite is missing. pandas 3.1.0 and numpy 2.5.4 are already locked; pandas resolves to `Any` under the mypy override. The baseline suite is green (`uv run pytest -q`) and `uv run mypy src scripts` is clean.
- Seam facts (LEARNINGS.md S1): Forrestdale (`ramsar-56`) has coverage 1.000 in 50HLK and 0.363 in 50HMK, and the two overlap. Real seam rows can therefore overlap as well as split, and the combining rule has to handle both.

### Design (new file `src/wetland_change/change.py`, pure, no I/O)
1. **Inputs.** Takes pandas frames that follow the observation schema. Required columns are listed in `REQUIRED_COLUMNS`; if any is missing it raises `ObservationFrameError(ValueError)`.
2. **`daily_aggregate(observations)`** returns one row per `polygon_id` and UTC acquisition date. The combining rule is documented in the docstring:
   - `n_pixels` and `n_clear` are summed.
   - `scene_coverage = min(1, Σcoverage)`.
   - `valid_fraction = Σn_clear/Σn_pixels × scene_coverage`. A lone partial row therefore drops below the valid gate.
   - `water_ha_index = Σwater / max(1, Σcoverage)`. This equals the n_clear-pooled clear-water fraction times the polygon's clear area. Disjoint pieces add up, and the area counted twice where tiles overlap is divided back out.
   - `ndvi_median` is the n_clear-weighted mean of the row medians (NaN when nothing is clear).
   - `item_id`, `tile` and `datetime` come from the row with the most clear pixels. `item_ids` is the sorted, comma-joined list of all items, and `n_scenes` is their count.
   - A single full-coverage row passes through unchanged.
3. **`build_baseline(history, *, min_valid_fraction)`** works per polygon × month × metric (`water_ha_index`, `ndvi_median`):
   - `baseline_median = np.median`
   - `baseline_mad = 1.4826 × median|x − median|` (`MAD_SCALE`)
   - `baseline_n` = number of values
   - Aggregates with `valid_fraction <= min_valid_fraction`, and non-finite values, are excluded.
   - The caller chooses which history to pass in; st-c8ca makes that choice and records it in decision 0004.
4. **`score_observations(observations, baseline, *, min_valid_fraction, min_samples=MIN_BASELINE_SAMPLES (5), z_threshold=Z_THRESHOLD (3.0))`**:
   - Output is long format, one row per polygon × date × metric, with columns `SCORE_COLUMNS`. These include `value, baseline_median, baseline_mad, baseline_n, z, flagged, reason`, plus the `item_id, item_ids, tile, datetime` that st-c8ca needs.
   - `z = (value − median)/mad`.
   - A row is flagged only when `|z| > 3` and `valid_fraction > min_valid_fraction`.
   - `reason` (`UnscoredReason` StrEnum, stored as a string) takes the first match in this order: `low_valid_fraction` (z is still reported), `missing_value`, `too_few_samples` (this includes no baseline at all, with `baseline_n` 0), `zero_mad`. The last three leave z null (NaN). z is never infinite and nothing raises.
5. `min_valid_fraction` is a required keyword argument, so the caller passes `config.water.min_valid_fraction` rather than relying on a duplicated default.

### Tests (`tests/test_change.py`, synthetic frames built with `OBSERVATION_COLUMNS`)
| Test | What it proves (AC) |
|---|---|
| `test_build_baseline_matches_numpy_median_and_scaled_mad[water,ndvi]` | The baseline equals the numpy median and 1.4826 × MAD within `assert_allclose` rtol 1e-9. Other months and other polygons do not leak in. |
| `test_build_baseline_excludes_rows_at_or_below_min_valid_fraction` | Rows at 0.8 and 0.5 with extreme values are left out of the baseline values and of `baseline_n`. |
| `test_score_flags_only_rows_above_min_valid_fraction[at-gate,below-gate,just-above-gate]` | An extreme value at valid 0.8 or 0.5 is never flagged (reason `low_valid_fraction`). At 0.801 it is flagged, so the gate is the only thing stopping it. |
| `test_score_flags_four_robust_sd_low_and_not_two_robust_sd_high` | median − 4σ gives z ≈ −4 (< −3) and is flagged. median + 2σ gives z ≈ 2 and is not flagged. |
| `test_score_zero_mad_gives_unflagged_row_with_reason` | MAD 0 gives an unflagged row with reason `zero_mad` and z null or finite. |
| `test_score_too_few_samples_gives_unflagged_row_with_reason` | `MIN_BASELINE_SAMPLES − 1` samples give reason `too_few_samples`, z null or finite, and `baseline_n` reported. |
| `test_score_without_any_baseline_gives_too_few_samples` | An empty baseline gives `baseline_n` 0, null median and MAD, reason `too_few_samples`, and null z. |
| `test_score_seam_rows_same_day_give_one_scored_row` | Same-day rows at coverage 0.4 and 0.6 give exactly one scored row per metric for that polygon and date. |
| `test_daily_aggregate_combining_rule_for_disjoint_seam_pieces` | Pins the documented rule: counts summed, pooled valid fraction, water summed, n_clear-weighted NDVI, primary item and `item_ids`. |
| `test_daily_aggregate_divides_out_overlapping_tile_coverage` | For the Forrestdale-style overlap (1.0 + 0.363), water = Σ/1.363. |
| `test_daily_aggregate_lone_partial_row_falls_below_valid_gate` | A 0.363-coverage row on its own gets valid_fraction 0.363, so it is never flagged or used in the baseline. |
| `test_daily_aggregate_keeps_single_full_row_values` | A single full row passes through unchanged, so the baseline is computed over the raw values. |
| `test_score_rows_carry_the_baseline_they_were_scored_against[metric]` | Each scored row carries the exact baseline median, MAD and n, and the columns equal `SCORE_COLUMNS`. |
| `test_daily_aggregate_rejects_frame_without_required_columns` | A missing column raises `ObservationFrameError` that names the column. |

The module and tests were prototyped against the worktree venv (pandas 3.1.0, numpy 2.5.4). All 18 tests pass with `-W error`, and ruff check, ruff format and mypy strict are clean.

### Verification (from AGENTS.md, in order)
```
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src scripts
uv run pytest -q
```

### Out of scope
Writing change files, the CLI, the pipeline, decision 0004 and the manifest all belong to st-c8ca. No other file changes and no dependency changes.

## Implementation Notes

- 2026-10-29T19:32:49.732Z: touches-expansion: overlaps st-1990 (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.734Z: touches-expansion: overlaps st-ae6e (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.735Z: touches-expansion: overlaps st-afcf (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.736Z: touches-expansion: overlaps st-d4a8 (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.737Z: touches-expansion: overlaps st-f4d3 (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split

## Questions
