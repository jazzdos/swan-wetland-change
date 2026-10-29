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

## Implementation Notes

## Questions
