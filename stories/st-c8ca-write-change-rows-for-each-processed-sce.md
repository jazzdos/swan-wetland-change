---
id: st-c8ca
title: Write change rows for each processed scene
type: feature
epic: st-70d1
priority: P1
depends_on: [st-f4d3, st-8228]
touches: [README.md, docs/decisions/0004-baseline-uses-earlier-observations.md, src/wetland_change/cli.py, src/wetland_change/manifest.py, src/wetland_change/outputs/changes.py, src/wetland_change/outputs/geoparquet.py, src/wetland_change/pipeline.py, src/wetland_change/store.py, tests/test_change_manifest.py, tests/test_change_outputs.py, tests/test_cli.py, tests/test_pipeline.py]
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

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-c8ca)

Prerequisites st-8228 (change.py) and st-f4d3 (backfill, --output-root) are merged. Facts that shape the plan:
- `src/wetland_change/change.py` already has `daily_aggregate`, `build_baseline(history, min_valid_fraction=)`, `score_observations(observations, baseline, min_valid_fraction=)` returning `SCORE_COLUMNS` (polygon_id, acquisition_date, month, datetime, item_id, item_ids, tile, n_scenes, scene_coverage, n_clear, valid_fraction, metric, value, baseline_median, baseline_mad, baseline_n, z, flagged, reason). Pure, no I/O. Baseline is NOT time-aware, so the caller picks the history.
- `src/wetland_change/outputs/geoparquet.py` has `observation_path`, `rows_to_frame`, `to_geoparquet_bytes` (deterministic GeoParquet 1.1 with bbox covering), `write_observations`. `OutputStore` (src/wetland_change/store.py) has write_bytes/read_bytes/exists/list_files but no delete.
- `RunManifest` (src/wetland_change/manifest.py) has observation_files but no change fields. `latest_run_id` in verify/run.py skips manifests whose `processed` is 0, so a score-only manifest in `runs/` is safe.
- `run_once` / `backfill_once` live in src/wetland_change/pipeline.py; the CLI `_load` in cli.py needs AOI files, so `score` must use `load_config` directly.
- duckdb, geopandas, pyarrow, geoparquet-validator are already dependencies. `uv run pytest` works in the worktree.

## Design decisions

1. Baseline history rule (recorded in ADR 0004): the baseline for a scored UTC acquisition date D, polygon P, month M is built only from stored observation rows with the same polygon, the same calendar month and an acquisition UTC date strictly before D. Reasons: the scored row (and same-day partner-tile rows, which belong to the same daily aggregate) never dilute their own baseline, and rescoring is reproducible because later-arriving data cannot change an older item's flags. Consequence: an out-of-order backfill changes later items' baselines, so `score` is rerun after a backfill; the earliest dates have too few samples and are never flagged.
2. Scoring unit is the daily aggregate (so seam polygons use all same-date rows). Flagged aggregate rows are grouped by the aggregate's primary `item_id` and written to `changes/year=YYYY/tile=<tile>/chg_<item_id>.parquet`. Only flagged rows are written (design: flagged rows become `changes/` rows). If a candidate item on a rescored date now has no flagged rows, a stale `chg_` file is deleted so a rescore reflects the store.
3. Change file columns: polygon_id, item_id, item_ids, datetime, tile, month, n_scenes, scene_coverage, valid_fraction, metric, value, z, baseline_median, baseline_mad, baseline_n, plus polygon geometry (EPSG:4326, taken from the stored observation row). No run_id column, so reruns are byte-identical. Rows sorted by (polygon_id, metric).
4. `run_once` scores after the ledger is written, for the UTC dates of the observation files it just wrote. `backfill_once` is unchanged. New `score` command scores stored observations whose acquisition date is in [--start, --end] (inclusive days, like backfill) and writes a manifest with kind "score".
5. Manifest gets `change_rows: int = 0` and `change_files: list[str]`.

## Steps

1. `src/wetland_change/store.py`: add `OutputStore.delete(relpath) -> bool` (delete if present). Test in tests/test_change_outputs.py.
2. `src/wetland_change/outputs/geoparquet.py`: add `read_observations(store) -> gpd.GeoDataFrame` (list_files("observations"), obs_*.parquet only, read each via BytesIO like `read_ledger`, concat, sort by item_id, polygon_id; empty store returns an empty frame with OBSERVATION_COLUMNS). Test: round trip with write_observations, empty store.
3. New `src/wetland_change/outputs/changes.py`: `CHANGE_COLUMNS`, `change_path(year, tile, item_id)`, `changes_to_frame(scores, geometries)`, `write_changes(scores, geometries, store) -> str`. Tests: path string; column order, dtypes, sort; geo metadata version 1.1.0 and covering bbox; geoparquet-validator accepts the file (skip if not on PATH, same as tests/test_geoparquet.py); rewrite byte-identical.
4. `src/wetland_change/manifest.py` fields (step 5 of design) and `docs/decisions/0004-baseline-uses-earlier-observations.md` (format of 0003: Status/Context/Decision/Consequences; states which stored rows feed the baseline). Test in tests/test_change_outputs.py: new fields default 0 / [] and appear in `to_json`; test that globs `docs/decisions/0004-*.md` and asserts it mentions "strictly before" (proves the AC file exists and states the rule).
5. `src/wetland_change/pipeline.py`: `ScoreResult` dataclass (files, rows, removed) and `score_changes(store, *, min_valid_fraction, dates=None, date_range=None) -> ScoreResult` implementing decisions 1 to 3 (restrict history to the day's polygon ids and month before `build_baseline` so a long range stays fast). Tests (tests/test_change_outputs.py, using ObservationRow rows written with write_observations): an outlier is written with the expected z (recomputed independently with numpy from the prior-year values), a normal value writes nothing, a low-valid-fraction outlier writes nothing, rows dated after or on the scored date (extreme values) do not change z, a stale file is deleted when the item stops being flagged, two calls give byte-identical files, every required field (polygon_id, item_id, datetime, metric, value, z, baseline_median, baseline_mad, baseline_n) is present and non-null.
6. `src/wetland_change/pipeline.py`: `run_once` collects UTC dates of entries that wrote an observation file, and after `write_ledger` and the watermark update calls `score_changes(store, min_valid_fraction=cfg.water.min_valid_fraction, dates=...)`, sets `manifest.change_rows` and `manifest.change_files`, then writes the manifest. Add `score_once(cfg, *, start, end, store, now, config_path, output_root_override=None) -> RunManifest` (kind "score", datetime_start/end set, refuses a reused run id via `store.exists(manifest_path(run_id))`, writes the manifest). Tests in tests/test_pipeline.py (AC 1 to 3 and 6): probe run in a scratch root to learn the fixture's water_ha_index and ndvi_median, prepopulate the real store with six prior Octobers of ramsar-52 baseline rows far from those values with a nonzero spread, run `run_once`, assert `manifest.change_rows == 2`, the `changes/year=2026/tile=<tile>/chg_<item_id>.parquet` file exists, passes geoparquet-validator, carries the required columns; second `score_changes` over the same date leaves the file bytes unchanged; the manifest JSON on disk records `change_rows`; a later `run_once` with no new items records 0; `backfill_once` writes no `changes/` files.
7. `src/wetland_change/cli.py`: `score` command with `--start`, `--end` (formats %Y-%m-%d, required), `--config`, `--output-root`, `--now`. Validates end >= start before loading config (BadParameter, exit 2), uses `load_config` (not `_load`), calls `score_once`, echoes the manifest JSON. Add "score" to the parametrized `test_output_root_listed_on_every_command` in tests/test_cli.py. Tests in tests/test_change_outputs.py: `score --help` exits 0 and lists `--start`, `--end`, `--output-root` (AC 4); `score` against a prepopulated override root writes changes and a manifest with kind "score" and change_rows; end before start exits 2 without loading config.
8. README.md: one line under Setup showing `uv run wetland-change score --start ... --end ...` after a backfill.
9. Close-out gates in order: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.

## Implementation Notes

## Questions
