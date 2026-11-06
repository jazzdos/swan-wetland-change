---
id: st-2bfd
title: "Record CRS, units and mask rule in output metadata"
type: bug
priority: P2
depends_on: []
discovered_from: st-ff89
touches: [README.md, src/wetland_change/manifest.py, src/wetland_change/mask.py, src/wetland_change/outputs/changes.py, src/wetland_change/outputs/geoparquet.py, src/wetland_change/outputs/provenance.py, src/wetland_change/pipeline.py, src/wetland_change/stats.py, tests/test_change_outputs.py, tests/test_geoparquet.py, tests/test_manifest.py, tests/test_pipeline.py]
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

## Findings from the worktree (.worktrees/st-2bfd, HEAD fb0f4b0)

All story pointers hold. `src/wetland_change/outputs/geoparquet.py` `to_geoparquet_bytes` (line 57) is the only Parquet writer; both `write_observations` (geoparquet.py) and `write_changes` (outputs/changes.py:69) go through it. `mask.py` has `CLEAR_CLASSES=(4,5,6,7,11)` and `EXCLUDED_CLASSES=(0,1,2,3,8,9,10)`. `RunManifest` (manifest.py) has no operation_epsg. `cfg.aoi.operation_epsg` (default 32750) exists, and `pipeline.process_scene` already refuses any scene whose EPSG differs from it, so source CRS == operation CRS for every row ever written. Per-polygon water rule is `cfg.water.for_polygon(polygon_id)` -> `WaterSetting(method, threshold)`; scl6 has threshold None. Callers: `write_observations` is called only at pipeline.py:225 (`_process_one`, which has `cfg`); `write_changes` only from `score_changes` (pipeline.py:294, called at pipeline.py:510 and :750, both with `cfg` in scope). RunManifest is constructed at pipeline.py `_new_manifest` (~159), `_recovered_manifest` (~559), score (~755) and requeue (~803).

Verified by prototype: reading the bytes written by `GeoDataFrame.to_parquet(..., schema_version="1.1.0", write_covering_bbox=True)` with `pq.read_table`, adding keys through `table.replace_schema_metadata({**existing, **extra})` and rewriting with `pq.write_table(..., compression="snappy")` keeps the `geo` key and CRS, shows the new keys in the footer, `gpd.read_parquet` still works, and the output is byte-identical across calls. pyarrow 26.0.0, geopandas 1.2.0.

## Design

- New module `src/wetland_change/outputs/provenance.py` builds a `dict[str, str]` of footer keys. Keys are flat and unprefixed so the test and any reader can use them directly: `source_epsg` ("32750"), `operation_epsg` ("32750"), `geometry_epsg` ("4326"), `units` (JSON object column -> unit string, sorted keys), `scl_classes_dropped` (JSON list, from `mask.CLEAR_CLASSES` complement, i.e. [0,1,2,3,8,9,10]), `scl_classes_clear` (JSON list [4,5,6,7,11]), `clear_pixel_rule` (short text: pixel is clear when SCL is in scl_classes_clear and the bands used are finite), `water_settings` (JSON object polygon_id -> {"method", "threshold"} for the polygons in that file only, threshold null for scl6, sorted keys), `water_units_note` ("threshold is a unitless index value; water_ha_scl always counts SCL class 6").
- `source_epsg` and `operation_epsg` both come from `cfg.aoi.operation_epsg` (justified by the process_scene guard; say so in a comment). `geometry_epsg` is the constant 4326, taken from the frame CRS (`frame.crs.to_epsg()`) so it cannot drift from the geometry.
- Units: observation file: n_pixels and n_clear "count of 10 m pixels"; scene_coverage, valid_fraction, cloud_fraction, dea_wo_agreement "fraction (0 to 1)"; water_ha_index, water_ha_scl "hectares"; ndwi_median, mndwi_median, ndvi_median "unitless index". Change file: month "calendar month 1 to 12"; n_scenes, baseline_n "count"; scene_coverage, valid_fraction "fraction (0 to 1)"; z "unitless (robust z-score)"; value, baseline_median, baseline_mad depend on the `metric` column, so the unit is an object {"water_ha_index": "hectares", "ndvi_median": "unitless index"}.
- `to_geoparquet_bytes(frame, metadata: Mapping[str, str])` gets a required second argument, writes through BytesIO as now, then re-reads the table and rewrites it with the extra footer keys (sorted, so deterministic). `write_observations(rows, store, *, water, operation_epsg)` and `write_changes(scores, geometries, store, *, water, operation_epsg)` take the water config and EPSG as required keyword arguments so no pipeline file can be written without metadata. `score_changes` gains required keyword args `water: WaterConfig` and `operation_epsg: int` and forwards them. Caveat to put in a docstring: change-file water_settings reflect the config at scoring time; `config_sha256` in the manifest pins the config.
- RunManifest gets `operation_epsg: int | None = None` (last field, defaulted so existing constructors and tests keep working). Daily, score and requeue manifests set `cfg.aoi.operation_epsg`; the recovered manifest leaves it None like package_version and config_sha256 (the crashed run's config is not known) and its comment says so.

## Steps

1. (Batch 1) Manifest field. Edit `src/wetland_change/manifest.py` (field plus comment), `src/wetland_change/pipeline.py` (`_new_manifest`, score-run and requeue constructors set it; `_recovered_manifest` leaves None). Tests in `tests/test_manifest.py`: default is None and appears as `null` in `to_json`; a manifest built with `operation_epsg=32750` writes `"operation_epsg": 32750` to `runs/<run_id>.json` via `write_manifest`. Test in `tests/test_pipeline.py`: a fixture daily run's manifest JSON in the store has `operation_epsg == 32750`, and the score and requeue manifests do too (reuse the existing helpers in that file; look at how existing tests call `_run`, `score_once`/`requeue_once`).
2. (Batch 2) Footer metadata. Add `outputs/provenance.py`; change `to_geoparquet_bytes`, `write_observations`, `write_changes`, `score_changes`, `_process_one`, and the two `score_changes` call sites; update every existing call in tests (`tests/test_geoparquet.py`, `tests/test_change_outputs.py`, `tests/test_pipeline.py`) to pass `water=WaterConfig(...)` and `operation_epsg=32750` (add small shared constants in each test file or in `tests/conftest.py`).
3. Tests in `tests/test_geoparquet.py` (read the footer with `pq.read_schema(path).metadata` and `pq.read_metadata(path).metadata`): (a) after `write_observations`, `source_epsg == b"32750"`, `operation_epsg == b"32750"`, `geometry_epsg == b"4326"`; (b) `units` JSON gives "hectares" for water_ha_index and water_ha_scl, "unitless index" for ndwi/mndwi/ndvi medians, "fraction (0 to 1)" for scene_coverage, valid_fraction, cloud_fraction, dea_wo_agreement; (c) completeness guard: every column of `rows_to_frame(ROWS)` with a numeric dtype (excluding geometry) has an entry in `units`, so a new numeric column without a unit fails; (d) `scl_classes_dropped` loads to [0,1,2,3,8,9,10] and equals `sorted(set(range(12)) - set(mask.CLEAR_CLASSES))`, and `scl_classes_clear` equals `list(CLEAR_CLASSES)`; (e) `water_settings` for rows of ramsar-56 and ramsar-52 with a WaterConfig that has an override for ramsar-56 (mndwi, 0.05) and a global of mndwi -0.1 gives the right method and threshold per polygon, includes only polygons in the file, and an scl6 override gives threshold null; (f) the `geo` key is still present with the covering bbox and `gpd.read_parquet` still returns CRS 4326 (existing tests already assert this and must still pass; the geoparquet-validator test must still pass); (g) rewrite stays byte-identical with metadata (existing `test_rewrite_is_byte_identical`, updated for the new signature). Equivalent tests for change files in `tests/test_change_outputs.py`: footer keys, the per-metric `value` unit object, completeness guard over `CHANGE_COLUMNS` numeric dtypes, water_settings limited to polygons in the file; and one `score_changes` end-to-end test that the written change file has the keys.
4. `tests/test_golden_run.py` is not edited. `test_same_now_gives_byte_identical_outputs` already compares every observation byte for two runs and must still pass, which proves the metadata is deterministic. The golden YAML compares row values only and is unaffected.
5. Docs: one sentence in `README.md` near the GeoParquet row (line ~168, and section at ~88) naming the footer keys; keep `tests/test_readme.py` passing. Add a LEARNINGS.md or decision note only if the README test requires it.
6. Run the four gates in order, one per command: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. Do not run `-m live`.
## Orchestrator amendments

These override the text above where they differ.

1. Agents commit nothing; the orchestrator commits after the run. Uncommitted work at the end of a task is expected and is not a defect. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**.
2. Never call AWS for the project's own bucket, never run terraform plan or apply, never run compaction against S3, and never run `-m live` tests. Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data and never point verify_run there. Files already written there keep their bytes; this story changes only files written from now on.
3. Gates, one command each, judged by exit code: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`, `GITHUB_ACTIONS=true uv run pytest -q`. Never clear addopts for a gate; for a count use `-o addopts="-m 'not live'"`.
4. Footer metadata must be a pure function of the rows and the config: no timestamps, run ids, hostnames, library versions or anything else that differs between two runs with the same inputs, so `test_same_now_gives_byte_identical_outputs` in tests/test_golden_run.py keeps passing unedited.
5. Readers must keep working on observation and change files written before this change, which have no new footer keys. Add one test that `read_observations` reads a mix of a file written without the new keys (plain `frame.to_parquet` bytes) and one written with them.
6. In the README and docstrings, say plainly that source_epsg equals operation_epsg because process_scene refuses any scene whose EPSG differs from the operation EPSG. Docs are flat factual prose with no em dashes.

## Implementation Notes

- 2026-11-06T05:54:40.366Z: RunManifest.operation_epsg (None on recovered manifests) is written to runs/<run_id>.json by daily, score and requeue runs. New outputs/provenance.py builds the footer: source_epsg and operation_epsg 32750 (equal because process_scene refuses other EPSGs), geometry_epsg 4326 from the frame, units for every numeric column (completeness guard test), scl_classes_dropped [0,1,2,3,8,9,10], scl_classes_clear, clear_pixel_rule, water_settings for the polygons in the file, water_note. Footers are deterministic; test_golden_run byte-identical test unedited and passing. Old files without the keys still read. Existing backfill files are not rewritten. 896 passed.

## Questions
