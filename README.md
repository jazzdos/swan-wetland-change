# swan-wetland-change

Scheduled, incremental water and vegetation change detection for the Ramsar
wetlands of the Swan Coastal Plain, Western Australia, from Sentinel-2
Collection 1 Cloud-Optimized GeoTIFFs on Earth Search. Each run writes one
GeoParquet observation row per wetland polygon per scene, scores new rows
against a month-of-year baseline, publishes a STAC catalogue, and checks the
outputs against independent references. The full design is in
`docs/plans/2026-10-29-swan-wetland-change-design.md`.

## What the pipeline does

- Finds new `sentinel-2-c1-l2a` scenes on Earth Search that intersect the
  Ramsar sites of Forrestdale and Thomsons Lakes, the Peel-Yalgorup System,
  Becher Point Wetlands and Ellen Brook, under 20 percent cloud.
- Reads only the pixel windows that cover each polygon, masks cloud, shadow
  and nodata with the Scene Classification Layer (SCL), and computes NDWI,
  MNDWI and NDVI.
- Writes one row per polygon per scene with two water areas (calibrated
  index and SCL class 6), a column for agreement with DEA Water Observations
  (filled at first processing when DEA holds the item, otherwise null), index
  medians,
  valid and cloud fractions, and the share of the polygon inside the scene.
- Flags rows whose water area or NDVI departs from the same polygon's
  same-month baseline by a robust z above 3.
- Builds a static STAC catalogue over the outputs and writes a verification
  report for each run.

All processing happens in EPSG:32750 (WGS 84 / UTM zone 50S), the source CRS
of all six tiles (50HLJ, 50HLK, 50HMJ, 50HMK, 50JLL, 50JML). Observation
geometries are stored in EPSG:4326. Water areas are in hectares; indices,
fractions and z scores are unitless.

## Design choices

| Choice | Reason | Record |
|---|---|---|
| Sentinel-2 Collection 1 only (`sentinel-2-c1-l2a`) | The older `sentinel-2-l2a` collection mixes items with the -1000 BOA offset already applied and items without it. Collection 1 is raw DN throughout. Landsat on Earth Search is requester-pays. | `docs/decisions/0001-sentinel-2-collection-1-only.md` |
| Reflectance is DN times scale plus offset from the item's `raster:bands` | No hard-coded constant. Scale and offset are checked against `BOA_QUANTIFICATION_VALUE` and `BOA_ADD_OFFSET` in the ESA product XML for every scene before any pixel is read; a mismatch fails the scene, not the run. | `docs/decisions/0001-sentinel-2-collection-1-only.md` |
| Vector-first zonal statistics | One row per polygon per scene is kilobytes per scene and keeps runs short and incremental. | Design, "Purpose and scope decisions" |
| Ramsar sites (DBCA-010) as the reporting unit, DEA Waterbodies polygons as the verification unit | DBCA-010 downloads without login under CC BY-SA 4.0. DEA Waterbodies publishes per-lake wet-fraction history to compare against. | `AGENTS.md`, design |
| Three water columns per row | McFeeters NDWI above 0 found 5,845 water pixels on Thomsons Lake where SCL class 6 found 16,676 and DEA found 16,444. The textbook threshold fails on shallow, vegetated lakes, so the calibrated index, SCL class 6 and the DEA agreement are stored side by side. The agreement is filled at first processing and is null when DEA holds no item then. | `docs/decisions/0002-three-water-columns.md`, `docs/decisions/0009-dea-wo-agreement-populated-at-processing-time.md` |
| Per-polygon water settings | One global setting (MNDWI above -0.1) failed DEA agreement on three polygons. ramsar-15 uses SCL class 6, ramsar-28 NDWI above -0.15, ramsar-56 MNDWI above 0.05, and every other polygon MNDWI above -0.1, each calibrated against DEA Sentinel-2 Water Observations. ramsar-12 stays on the global setting after a confirmatory test on 7 further scene-tiles. | `docs/decisions/0005-per-polygon-water-settings.md`, `docs/decisions/0010-ramsar-12-water-setting.md` |
| Ledger is fixed-schema Parquet | stac-geoparquet infers a schema per batch, so ledger files from different days do not union, and failed items have no STAC item. The ledger keeps the full source item as JSON. | `docs/decisions/0003-fixed-schema-ledger.md` |
| Baseline uses only earlier observations | The score for date D uses only same-polygon, same-month rows from dates before D, so a row never dilutes its own baseline and rescoring is reproducible. | `docs/decisions/0004-baseline-uses-earlier-observations.md` |
| Month-of-year baseline with median and MAD | Seasonal drying is not change. | Design, "Change detection" |
| One file per scene, overwritten on rerun | Parquet is immutable; per-scene files make reruns idempotent. | Design, "Challenges and planned answers" |
| SCL class shares read at full resolution | The Earth Search SCL overviews use mode resampling, which shifted vegetation shares by 2 to 3 percentage points at the 1/16 overview. | `LEARNINGS.md`, "SCL overview resampling" |

## Architecture

One Python package (`src/wetland_change`), one CLI (`wetland-change`) and two
scheduled GitHub Actions workflows. Every run is a function of the ledger and
output store. The guarantee is narrower than "reruns are safe" and has four
parts, each covered by tests on local stores and none yet exercised against
S3:

- The daily `run` writes a ledger part after each scene, so an interrupted run
  keeps its finished scenes and the next run resumes after them.
- A daily run that stops after its ledger rows are written, before scoring or
  its manifest, is finished by the next daily run, which scores the earlier
  run's dates and writes its manifest with `recovered_by` set
  (`tests/test_pipeline.py`, `tests/test_ledger.py`). Backfill rows are never
  recovered this way; `score` covers them.
- `run` and `backfill` refuse a run id that already has a manifest or ledger
  parts in the output root, so a repeated `--now` cannot overwrite an earlier
  run (`tests/test_cli.py`, `tests/test_backfill.py`).
- Rerunning the same inputs into an empty output root gives byte-identical
  files (`tests/test_golden_run.py`).

### Run stages

1. Discover (`catalogue/search.py`). Search Earth Search for items created at
   or after the ledger watermark minus one day, re-check cloud cover and
   polygon intersection client-side, and drop items already in the ledger
   with the same `updated` timestamp.
2. Plan (`windows.py`). Compute a pixel window per polygon, snapped to the
   20 m SCL grid, and the fraction of the polygon inside the scene.
3. Read (`raster/read.py`, `raster/scaling.py`). Windowed reads of green,
   red, NIR, SWIR16 and SCL with retry on transient errors; scale and offset
   from `raster:bands`, checked against the ESA XML.
4. Mask and compute (`mask.py`, `indices.py`). Drop SCL classes 0, 1, 2, 3,
   8, 9 and 10; compute NDWI, MNDWI and NDVI.
5. Summarise (`stats.py`). Rasterise each polygon and write one observation
   row. The daily run also looks up the scene's DEA Water Observations item
   (`verify/wo.py`) and stores the agreement per polygon, or null when DEA
   holds no item, cannot be reached or has no mutually clear pixel.
6. Publish (`outputs/geoparquet.py`, `ledger.py`, `manifest.py`). GeoParquet
   1.1 under `observations/year=YYYY/tile=<MGRS>/obs_<item_id>.parquet`,
   ledger parts under `ledger/year=YYYY/` (merged into `ledger/compacted/`
   once 25 or more accumulate), and a run manifest under `runs/`.
   Each observation and change file carries footer key-value metadata:
   `source_epsg`, `operation_epsg`, `geometry_epsg`, `units`,
   `scl_classes_dropped` and `water_settings` (the method and threshold of the
   polygons in that file). `source_epsg` equals `operation_epsg` because
   `process_scene` refuses any scene whose EPSG differs from the operation
   EPSG. Files written before these keys existed still read.
   A later run finishes any daily run that has ledger rows and no manifest,
   scoring its dates and writing its manifest with `recovered_by` set and its
   skipped tallies, watermarks, `package_version`, `config_sha256`, `runtime`,
   `uv_lock_sha256` and `git_commit` empty.
   The daily job verifies each recovered run by id after it verifies its own.
   The run manifest records `runtime` (python, gdal, proj, geopandas, rasterio,
   pyarrow and numpy versions), the sha256 of `uv.lock` as `uv_lock_sha256`, and
   the `git_commit` of the code (null outside a git checkout).
7. Change (`change.py`, `outputs/changes.py`). Score the daily aggregate per
   polygon against its month-of-year baseline; rows with absolute robust z
   above 3, valid fraction above 0.8 and at least 5 baseline samples go to
   `changes/year=YYYY/tile=<MGRS>/chg_<item_id>.parquet`.
8. Catalogue (`stac/catalogue.py`). One Collection and one Item per processed
   scene, with the observation, change and verification files as assets,
   validated before writing, plus `stac/swan-wetland-change/items.parquet`.
   The build is incremental: `stac/write-index.json` records the sha256 of
   every object last written and the base URL, and only new or changed
   objects are written, so a build with nothing new writes no catalogue file.
9. Verify (`verify/`). Score the verification matrix for a run and write
   `verification/<run_id>.json` and `docs/research/verification-<run_id>.md`.

A failing scene is recorded in the ledger with an attempt count and retried
on later runs; it does not abort the run.

### Scheduled jobs

- `.github/workflows/pipeline.yml`: daily at 10:17 UTC and on manual
  dispatch. Fetches the AOI, runs `wetland-change run --no-catalogue`, then
  `verify` when the run processed scenes, then `verify --run-id` for each run
  it recovered, then `build-catalogue` on every day
  that is not cancelled (so the catalogue links the run's report, and reports
  from `verify.yml` or a CLI backfill, even on a day with no processed
  scenes), and commits the verification reports of a day that processed scenes
  or recovered a run. The commit keeps the
  repository active so GitHub does not disable the schedule after 60 days.
- `.github/workflows/verify.yml`: Sundays at 22:43 UTC and on manual
  dispatch. Runs the live contract tests, `verify` on the latest daily run and
  `freshness`.
- `.github/workflows/alert.yml`: runs after `pipeline` or `verify`
  completes. When a scheduled run did not succeed (failure, cancelled, timed
  out) it opens an issue titled `<workflow> workflow did not succeed` or
  comments on the open one. Manual dispatch runs are not alerted.
- `.github/workflows/test.yml`: ruff, mypy and pytest on every push to
  `main` and every pull request targeting it.

## Data sources and licences

The code in this repository is released under the MIT licence (see
`LICENSE`). That licence covers the source code only. Data and outputs carry
separate terms. Outputs derived from the DBCA-010 Ramsar polygons (the
observation, change and catalogue files, declared as CC-BY-SA-4.0 in the STAC
collection) are CC BY-SA 4.0. The DEA inputs and references (Waterbodies,
Water Observations, ARD) are CC BY 4.0. Sentinel-2 data follow the Copernicus
Sentinel data terms.

| Source | Use | Licence |
|---|---|---|
| Earth Search `sentinel-2-c1-l2a` (Element 84, AWS) | Input scenes | Copernicus Sentinel data terms (free and open) |
| DBCA-010 Ramsar Sites (SLIP ArcGIS REST, layer 9) | Reporting polygons | CC BY-SA 4.0 |
| DEA Waterbodies v3 polygons (Swan subset, WFS) | Verification polygons | CC BY 4.0 |
| DEA Waterbodies v3 per-lake CSV time series | Water history reference | CC BY 4.0 |
| DEA Sentinel-2 Water Observations `ga_s2_wo_provisional_3` | Live water extent reference | CC BY 4.0 |
| DEA Sentinel-2 ARD NBART `ga_s2am_ard_3`, `ga_s2bm_ard_3`, `ga_s2cm_ard_3` | NDVI reference | CC BY 4.0 |
| Microsoft Planetary Computer `sentinel-2-l2a` | Pixel identity reference | Copernicus Sentinel data terms |
| Copernicus Data Space STAC `sentinel-2-l2a` | Discovery and freshness counts | Copernicus Sentinel data terms |

URLs, fetch dates, checksums, CRS and redistribution flags are in
`data/SOURCES.md`. Rows derived from the Ramsar polygons inherit CC BY-SA
4.0.

## Verification matrix

Each row of the design's matrix, the code or test that implements it, and
its status at this commit. "Live" results come from the first verify run
(`docs/research/verification-20261029T131944Z.md`), later live checks
recorded in `LEARNINGS.md`, and the Collection 1 backfill
(`docs/research/2026-11-03-backfill-hypotheses.md`).

| Goal | Reference | Implementation | Status |
|---|---|---|---|
| Discovery finds every scene | Copernicus Data Space STAC, `sentinel-2-l2a` | `src/wetland_change/verify/copernicus.py` (`discovery_vs_copernicus`); `tests/test_verify_copernicus.py`, `tests/test_verify.py` | Implemented. Compares counts and product names per tile per month, allowing 24 h latency. |
| Reads the right bytes | Planetary Computer `sentinel-2-l2a`, same ESA product | `src/wetland_change/verify/pixels.py` (`pixels_vs_planetary_computer`); `tests/test_verify.py`, `tests/test_live_verify.py` | Implemented. First live run: bit-identical on the five 2026-10-27 scenes; failed on three 2026-10-29 scenes because the Planetary Computer copies were faulty (`LEARNINGS.md`, "Planetary Computer copies of the 2026-10-29 pass"). |
| Reflectance scaling | ESA `product_metadata` XML on each item | `src/wetland_change/raster/scaling.py`, `src/wetland_change/verify/scaling.py` (`reflectance_scaling`); `tests/test_scaling.py`, `tests/test_verify.py` | Implemented and asserted for every scene at run time. Passed 8 of 8 on the first live run. |
| SCL read and alignment | ESA SCL class percentages in item properties | `src/wetland_change/verify/scl.py` (`scl_share_*`); `tests/test_verify.py` | Implemented at full resolution, tolerance 1 pp. Passed 32 of 32 checks on the first live run. |
| Index arithmetic | spyndex 0.12; dea-tools 0.4.10 `calculate_indices` | `tests/test_indices.py` (spyndex, standing); `scripts/compare_dea_tools_indices.py` (dea-tools, one-off) | Implemented. The dea-tools comparison passed 6 of 6 at 1e-6 (`LEARNINGS.md`, "dea-tools index comparison"). |
| Water extent, live | DEA `ga_s2_wo_provisional_3`, same pass and grid | `src/wetland_change/verify/wo.py` (`water_vs_dea_s2_wo`); `tests/test_verify.py` | Implemented for pixel agreement on mutually clear pixels, with per-polygon thresholds (0.91 default, which also applies to ramsar-12 under ADR 0010, and 0.94, 0.92 and 0.95 for the three overrides) instead of the design's 0.95, because the best calibrated agreement was 0.9303 (handoff, ADR 0005). The design's "wet area within 5 pp" clause is implemented as the signed gap between the pipeline and WO wet shares of mutually clear pixels, within 5 pp per pass and per polygon (ADR 0006); it was implied by the design's 0.95 floor and binds at the lowered per-polygon floors. 242 of the 251 rows that pass agreement are within 5 pp, and on the 6 fully measured dates, dates with a failing row go from 2 to 6 (LEARNINGS.md, ADR 0006). The exit code follows ADR 0008, not that count: a row that fails only the clause is a warning, and `verify` exits 3 on an agreement failure or when the gap pooled over the run exceeds 5 pp, which is 2 of the 6 measured dates. The check skips a polygon below `[verify] min_clear_pixels` (default 100) mutually clear pixels, and the skip is a reason skip, not an error. |
| Water extent, history | DEA Waterbodies v3 CSV per lake; DEA `ga_ls_wo_3` per scene | `src/wetland_change/verify/waterbodies.py` (`water_vs_dea_waterbodies`, `water_spearman_vs_dea_waterbodies`); `tests/test_verify_waterbodies.py` | Implemented against the Waterbodies CSV with a 10 pp per-pass tolerance (spike S9). The `ga_ls_wo_3` per-scene comparison is not implemented as a standing check: S9 found Waterbodies v3 within 0.2 pp of `ga_ls_wo_3` on all 129 passes, consistent with Waterbodies being derived from it, and used it once to set the tolerance (`LEARNINGS.md`, "S9 historical tolerance"). The per-lake Spearman is scored over every stored observation up to the newest scene of the verified run, so it reaches its 10 pair minimum on a daily run; per-pass checks cover the verified run only. `spearman_min` is 0.83, calibrated on the whole backfill (ADR 0007, `docs/decisions/0007-spearman-threshold-from-whole-history.md`). The backfill rho is 0.855 to 0.893 on four lakes, below the design's 0.9, so H4 is not supported. |
| NDVI | DEA NBART, same acquisition | `src/wetland_change/verify/ndvi.py` (`ndvi_vs_dea_nbart`, `ndvi_correlation_vs_dea_nbart`); `tests/test_verify_ndvi.py` | Implemented. One live check on 2026-10-30 passed with an absolute difference of about 0.003 against a 0.05 tolerance (`LEARNINGS.md`, "DEA NBART scale"). The check skips a polygon below `[verify] min_clear_pixels` (default 100) compared pixels, and the skip is a reason skip, not an error. |
| GeoParquet output | geoparquet-validator; DuckDB and GDAL as readers | `src/wetland_change/outputs/geoparquet.py`; `tests/test_geoparquet.py`, `tests/test_pipeline.py`, `tests/test_readme.py` | Implemented. The validator, DuckDB, pyarrow and geopandas readers run in the default suite and agree on row counts and bounds (`tests/test_geoparquet.py`). Footer keys `source_epsg`, `operation_epsg`, `geometry_epsg`, `units`, `scl_classes_dropped` and `water_settings` record CRSs, units, the SCL classes the clear mask drops and each polygon's water rule. GDAL is not exercised because the pinned pyogrio wheel has no Parquet driver. |
| STAC catalogue | stac-validator (through stac-check 1.14), stac-check, pystac validate, stac-browser | `src/wetland_change/stac/catalogue.py`; `tests/test_catalogue.py`, `tests/test_run_catalogue.py`; CORS in `infra/main.tf`, `tests/test_infra.py` | Implemented offline: pystac `validate_all` and stac-check pass, and all hrefs are absolute https. The live checks (bucket returns `Access-Control-Allow-Origin`, catalogue opens in stac-browser) are not implemented because the infrastructure has not been applied and no bucket exists. |
| Incremental and idempotent | pytest-regressions golden run; watermark replay | `tests/test_golden_run.py`, `tests/test_pipeline.py`, `tests/test_ledger.py`, `tests/test_catalogue.py` | Implemented: byte-identical outputs on rerun, no duplicates after watermark replay, golden observation rows. The ledger-against-Copernicus count is covered per tile over 30 days by the freshness row; the backfill reached coverage 1.0 against a fresh Earth Search reference. |
| Change detection | DEA Waterbodies Forrestdale record | `src/wetland_change/change.py`, `src/wetland_change/outputs/changes.py`; `tests/test_change.py`, `tests/test_change_outputs.py` | Implemented. Backfill 2022-12-01 to 2026-11-02 (1147 items): H1 supported, H2 untestable, H3 not supported, H4 not supported. See below. |
| Scheduled job alive | Earth Search and Copernicus counts per tile per 30 days | `src/wetland_change/verify/freshness.py` (`freshness_*`); `tests/test_verify_freshness.py`; alert workflow `.github/workflows/alert.yml`, `tests/test_workflows.py` | Implemented. Not yet run on a schedule (see Limitations). |
| End to end | `verify` over the latest daily run | `src/wetland_change/verify/run.py`, `src/wetland_change/verify/checks.py`; `tests/test_verify.py`, `tests/test_workflows.py` | Implemented and run locally (first live run: 127 checks, 115 passed, 12 failed, all 12 explained in `docs/handoffs/2026-10-29-milestone-1.md`). A green weekly `verify.yml` run has not happened (see Limitations). |

### Backfill results

From `docs/research/2026-11-03-backfill-hypotheses.md`. Hypotheses were
pre-registered in `LEARNINGS.md` before the run, and no threshold changed
after it. Forrestdale is ramsar-56, Thomsons is ramsar-52.

| Hypothesis | Verdict | Basis |
|---|---|---|
| H1, Forrestdale low water, December 2023 to January 2024 | Supported | 2 low flags in 3 scored dates; lowest z -8.87 on 2023-12-17 |
| H2, Forrestdale no anomaly, February to April 2023 | Untestable | 0 of 12 dates scored, all with too few baseline samples. The 2022 half is untestable: Collection 1 has no items over Forrestdale under 20 percent cloud for that period |
| H3, winter 2025 water at or above baseline | Not supported | ramsar-56 median delta -14.38 ha with a low flag on 2025-08-23 (z -3.39); ramsar-52 had no scored date |
| H4, Spearman rho at least 0.9 against DEA Waterbodies | Not supported | rho 0.870 (Forrestdale), 0.897 (Thomsons), 0.858 (Lake Clifton), 0.861 (Lake Preston) on the 2026-11-03 report; 0.861, 0.893, 0.855 and 0.857 over the whole stored history with the current pairing (`LEARNINGS.md`, "Spearman threshold calibration") |

Coverage was 1.0 (1147 of 1147 items in the reference search) with 0 items
failed in their final state. Earth Search Collection 1 has no history before
2022-12 for five of the six tiles (2022-03 for 50JLL), so the backfill starts
on 2022-12-01.

## Running locally

Requires uv and Python 3.12. Keep `PROJ_LIB` unset: an exported `PROJ_LIB`
breaks the rasterio wheels (`LEARNINGS.md`, S8).

```sh
uv sync --locked
uv run python scripts/fetch_aoi.py
uv run wetland-change discover
uv run wetland-change run
uv run wetland-change run --no-catalogue
uv run wetland-change backfill --start 2022-12-01 --end 2026-11-02
uv run wetland-change score --start 2022-12-01 --end 2026-11-02
uv run wetland-change requeue --all
uv run wetland-change verify
uv run wetland-change build-catalogue
uv run wetland-change compact-ledger
uv run wetland-change freshness
```

- `scripts/fetch_aoi.py` downloads the Ramsar and DEA Waterbodies polygons
  into `data/external/` and prints their `data/SOURCES.md` rows. It is a
  script, not a `wetland-change` subcommand. It exits non-zero when a
  response is not a GeoJSON FeatureCollection, or when an id used by
  `[water.overrides.*]` is absent from the fetched layers or no longer matches
  its pinned site name and bounding box.
- `discover` lists the scenes the next run would process without reading
  pixels.
- `run` is one incremental run: stages 1 to 8. It exits 2 when any scene
  failed. It reads the ledger once, and merges the ledger parts at the end
  when 25 or more exist. `--no-catalogue` skips stage 8 (the daily workflow
  builds the catalogue in its own step); the default builds it.
- `backfill` runs stages 1 to 6 over an acquisition date range and skips
  items already in the ledger. It does not score changes.
- `score` scores stored observations in a date range and writes change files.
  Run it after a backfill.
- `requeue` brings items that failed three times (exhausted) back: it appends
  a ledger row per item with attempts reset to 0, so the next `run` retries
  them with fresh attempts. Give item ids, or `--all` for every exhausted
  item. It exits 2 for an id that is not exhausted, or when nothing is
  exhausted. It does not edit existing ledger files and does not build the
  catalogue.
- `verify` scores the verification matrix for the latest daily run, or the run
  given with `--run-id`, and writes the JSON and Markdown reports. A backfill
  chunk is verified only by naming it with `--run-id`. It exits 3 when a check
  failed (a live water check that passes agreement and fails only the 5 pp wet
  area clause is reported as a warning with its gap and does not change the exit
  code; the pooled check `water_vs_dea_s2_wo_pooled_wet_area` covers the whole
  run, so a backfill run pools across all its dates, and exits 3 when its pooled
  gap exceeds 5 pp; `docs/decisions/0008-exit-code-for-live-water-check-failures.md`),
  4 when nothing was scored, 5 (naming the manifest path) when a run
  manifest cannot be read, rather than checking an older run, and 6 when a
  reference check could not run because its source raised an error. A skip
  that carries only a reason, such as a reference that is not published yet,
  does not change the exit code. The report carries a `matrix` section with
  pass, fail, warn or not-run for all 14 rows of the verification matrix.
  The per-lake Spearman of the water history row is scored over every stored
  observation up to the newest scene of the verified run, against
  `spearman_min` 0.83 (`docs/decisions/0007-spearman-threshold-from-whole-history.md`);
  per-pass checks cover the verified run only.
- `build-catalogue` builds the STAC catalogue from the ledger, writing only
  objects that are new or changed (`0 files written` is the correct output
  when nothing changed). Run it after `verify` so the catalogue links the
  verification report.
- `compact-ledger` merges every ledger part into one file,
  `ledger/compacted/ledger_compact_<run_id>.parquet`, and prints its path and
  `N parts merged` (or `nothing to compact` when there are fewer than two
  parts). The merged file is read back before any part is deleted. `run` and
  `backfill` already do this automatically at 25 parts; use the command to do
  it by hand, preferably when no workflow is running.
- `freshness` checks that the newest processed item is under 7 days old and
  that ledger counts match Earth Search and Copernicus per tile over 30 days.
  It also fails (`freshness_exhausted_items`) while any item has exhausted its
  attempts and has not been requeued or succeeded.

Every command reads `config/pipeline.toml` by default (`--config` to
change) and writes under `outputs/` (`--output-root` to change, including an
`s3://` root). Run any command with `--help` for its options.

Tests:

```sh
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src scripts
uv run pytest -q
```

Live tests (`uv run pytest -m live`) reach Earth Search, Planetary Computer
and DEA and are excluded from the default suite.

## Querying with DuckDB

The observation files are hive-partitioned by `year` and `tile`, so one glob
reads them all. From the repository root, after a run:

```sql
SELECT year, tile, site, polygon_id, datetime, water_ha_index, water_ha_scl, ndvi_median
FROM read_parquet('outputs/observations/*/*/*.parquet', hive_partitioning = true)
WHERE valid_fraction > 0.8
ORDER BY polygon_id, datetime
```

The public S3 bucket serves the same files to an anonymous reader. No
credentials are needed: the secret below names the region and nothing else.
The bucket policy allows anonymous listing only under `observations/`, so a
glob rooted anywhere else, including `changes/`, is denied.

```sql
INSTALL httpfs;
LOAD httpfs;
CREATE OR REPLACE SECRET public_outputs (TYPE s3, PROVIDER config, REGION '<aws_region>');

SELECT year, tile, site, polygon_id, datetime, water_ha_index, water_ha_scl, ndvi_median
FROM read_parquet('s3://<bucket>/observations/*/*/*.parquet', hive_partitioning = true)
WHERE valid_fraction > 0.8
ORDER BY polygon_id, datetime
```

Change rows use the same layout under `changes/`. They are readable by exact
object key but not by glob.

## Deployment

The AWS resources (a public-read S3 bucket with CORS for stac-browser, the
GitHub OIDC provider and a pipeline role) are an OpenTofu/Terraform module in
`infra/`. `infra/README.md` gives the apply steps and the role's trust
conditions.

After applying, set these repository variables (Settings, Secrets and
variables, Actions, Variables). `.github/workflows/pipeline.yml` and
`.github/workflows/verify.yml` read them; no secrets are stored.

| Variable | Value |
|---|---|
| `AWS_ROLE_ARN` | ARN of the pipeline role (module output `role_arn`) |
| `AWS_REGION` | Region of the bucket |
| `OUTPUT_BUCKET` | Bucket name, without `s3://` |

The role trusts only runs on `main`, so both workflows work only from `main`.

Two more steps come before the first scheduled run, both in `infra/README.md`.
`catalogue.base_url` in `config/pipeline.toml` still holds the `.invalid`
placeholder and must be set to the `bucket_url` output; `run`, `backfill`,
`score` and `build-catalogue` refuse an `s3://` output root until it is. The
output root should then be seeded from the backfill, because an empty root
leaves the first daily run bounded only by `stac.initial_lookback_days`.

## Limitations

As of this commit:

- The infrastructure in `infra/` has not been applied. No bucket, OIDC role
  or repository variables exist yet.
- The `pipeline` and `verify` workflows are disabled on GitHub until it is.
- The scheduled-job-alive row reads not-run in the verify report because
  freshness is a separate command (`wetland-change freshness`).
- No scheduled run has happened. The freshness and end-to-end rows, and
  success criterion 1 (four weeks of unattended daily runs), are untested.
- Whether GitHub-hosted runners can reach the DEA hosts has not been tested.
  The workflows' "Fetch the AOI" step downloads the DEA Waterbodies polygons
  from the DEA WFS, so an unreachable host fails that step.
- The live STAC checks (bucket CORS header, stac-browser) wait on the bucket.
- The anonymous S3 query in "Querying with DuckDB" has not been run against the
  project bucket because none is applied yet. It needs an apply of the
  `s3:ListBucket` list statement first.
- Water thresholds are calibrated against DEA Sentinel-2 Water Observations
  over August to October 2026 only, and DEA's product is itself unvalidated,
  so agreement measures consistency with DEA, not accuracy (ADR 0005).
- The live water check fails on ramsar-15, ramsar-28 and ramsar-56 at the
  global setting; the per-polygon overrides in ADR 0005 address this, and
  rows written before the change used the global setting.
- Hypotheses H2 to H4 are untestable or not supported on the current
  backfill; H4's rho of 0.855 to 0.893 sits below the 0.9 target, and
  `spearman_min` is calibrated to 0.83 instead (ADR 0007).
- Each `verify` reads every stored observation file (1147 files and about
  236 MB today, growing with each pass) for the Spearman check. S3 read time
  is unmeasured (ADR 0007).
- The `dea_wo_agreement` observation column is the agreement at first
  processing (`docs/decisions/0009-dea-wo-agreement-populated-at-processing-time.md`).
  It is null for rows written before that change, for backfill rows, when
  DEA holds no Water Observations item at first processing, and when fewer than
  `verify.min_clear_pixels` pixels are mutually clear (the report's floor). A row whose item
  arrives later stays null. In the measured sample every one of 44 scene-tiles
  had the item before the first run, with a smallest margin of 21 minutes, so
  a late run or a DEA backlog would raise the null share. DEA Sentinel-2 Water
  Observations keeps three months, so the verification report
  (`water_vs_dea_s2_wo`) can still score only recent passes.
- Peel Inlet and Harvey Estuary have no DEA Waterbodies polygon and no water
  history check.
- Earth Search Collection 1 has no items before 2022-12 for five of six
  tiles, which limits the baselines. Spike S4 counted Copernicus Data Space
  items from 2022-01-01 (1194, `LEARNINGS.md`, "S4 backfill count"), but it is
  not a backfill source, and reading its products to fill the 2022 gap would
  need a Copernicus account.
- `catalogue.base_url` is the `.invalid` placeholder and the output root has
  not been seeded from the backfill (st-30ad, st-5241; `infra/README.md`).
  Neither step can run before the bucket exists.
- Nothing has run against S3. The OIDC session length (st-a919), the bucket
  lifecycle rule and content types (st-4fa1), the anonymous list statement
  (st-58e9) and ledger compaction, which deletes ledger parts from an
  unversioned public bucket (st-b101), are tested on local stores and stub
  servers only. The three runner and bucket spikes of the design (5, runner
  dry run; 6, catalogue in stac-browser; 7, DuckDB over S3) have not been run,
  so seconds per scene on a GitHub runner and per-request S3 latency are
  unmeasured. The local figure is 139 to 152 s per scene
  (`docs/research/2026-11-03-backfill-hypotheses.md`) against a 120 minute job
  timeout.
- Deleting an object from S3 re-creates its parent directory marker, because
  pyarrow's `delete_file` does (st-c667, open). Ledger compaction and
  `pipeline.py` call it. Writes no longer create markers (st-2cc2).
- ramsar-12 (Peel-Yalgorup, 100.7 ha) reads wetter than DEA Water
  Observations on every sampled row at the global MNDWI -0.1 setting, and it
  accounts for 5 of the 9 rows that fail only the 5 pp clause. Which source is
  right is unknown. A confirmatory test on 7 further scene-tiles on 4 dates
  (2026-08-23 to 2026-09-07) did not support an override, so ramsar-12 keeps
  the global setting; on those rows the pipeline is drier than WO, not wetter.
  The decision was made under delegation and is pending Jarrod's review
  (ADR 0010; `LEARNINGS.md`, "ramsar-12 setting confirmation").
- Observation and change files carry the geometry CRS only. The operation CRS
  (EPSG:32750), units and the clear-pixel and water rules are in this README
  and `config/pipeline.toml`, not in the files (st-2bfd, open). The run
  manifest records no Python, GDAL, PROJ or package versions and no
  `uv.lock` hash (st-2bc1, open).
- The calibration and tolerance scripts behind the thresholds are untracked,
  and two committed research scripts no longer reproduce their committed
  outputs at the branch head (st-e6f1, open). Smaller reproducibility items
  are st-73ad (pixel area and vector engine), st-5acd (missing
  `data/SOURCES.md` rows) and st-eb5a (the DEA Waterbodies checksum covers
  fields that DEA refreshes).

The review that found most of the items above is
`docs/research/2026-11-04-milestone-2-review.md`. The state after fixing it,
and the audit of 2026-11-06, are in
`docs/handoffs/2026-11-06-milestone-2.md`.
