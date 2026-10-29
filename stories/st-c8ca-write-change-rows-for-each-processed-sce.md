---
id: st-c8ca
title: Write change rows for each processed scene
type: feature
epic: st-70d1
priority: P1
depends_on: [st-f4d3, st-8228]
touches: [src/wetland_change/pipeline.py, src/wetland_change/cli.py, src/wetland_change/outputs/**, src/wetland_change/manifest.py, docs/decisions/**, tests/test_pipeline.py, tests/test_change_outputs.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Design stage 7: score each new observation against the seasonal baseline using `src/wetland_change/change.py` from the scoring story, and write flagged rows under `changes/`. Mirror the observation layout (`observation_path` in `src/wetland_change/outputs/geoparquet.py`): `changes/year=YYYY/tile=<MGRS>/chg_<item_id>.parquet` as GeoParquet 1.1, one file per item so a rerun overwrites.

The baseline is read from observation files already in the store (pyarrow dataset or DuckDB over the hive partitions). Decide which stored rows feed it: all of them, or only rows acquired before the scored row so rescoring is reproducible. Record that choice as `docs/decisions/0004-*.md`.

`run_once` scores after writing observations. The backfill does not score (design: backfill runs stages 1 to 6 and 8), so add `wetland-change score --start --end`, honouring the `--output-root` override from the backfill story, to score stored observations after a backfill.

## Acceptance Criteria

- [ ] Offline test: with a store pre-populated with baseline observations, `run_once` on the fixture writes `changes/year=…/tile=…/chg_<item_id>.parquet` for an outlier item, and the file passes geoparquet-validator as in `tests/test_geoparquet.py`.
- [ ] Offline test: each change row carries polygon_id, item_id, datetime, metric, value, z, baseline median, MAD and sample count.
- [ ] Offline test: scoring the same item twice over an unchanged store produces byte-identical change files.
- [ ] `uv run wetland-change score --help` exits 0 and lists `--start`, `--end` and `--output-root`.
- [ ] `docs/decisions/0004-*.md` exists and states which stored observation rows feed the baseline.
- [ ] The run manifest records the number of change rows written.

## Implementation Plan

## Implementation Notes

## Questions
