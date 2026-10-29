# Swan Coastal Plain wetland change pipeline: design

Date: 2026-10-29
Status: approved in brainstorming, not yet planned
Profile: research-code
Branch: feature/wetland-change-pipeline

## Purpose and scope decisions

The project is a portfolio piece that demonstrates cloud-native geospatial
work: STAC search, windowed reads of Cloud-Optimized GeoTIFFs, GeoParquet
outputs, a self-authored STAC catalogue, scheduled incremental processing
and partitioning. Decisions taken during brainstorming:

| Decision | Choice | Reason |
|---|---|---|
| Purpose | Portfolio piece, public repository | The brief lists what the project "shows" to a reviewer |
| Hosting | GitHub Actions cron, outputs on S3 via OIDC, stac-browser on GitHub Pages | Free compute, object storage for outputs, no long-lived keys |
| Sensor | Sentinel-2 L2A only, collection `sentinel-2-c1-l2a` | Free and unsigned; Landsat on Earth Search is requester-pays; the older `sentinel-2-l2a` collection has the radiometric offset baked into some items while still advertising it |
| Area of interest | Ramsar sites on the Swan Coastal Plain from DBCA-010 | CC BY-SA 4.0, no login, about 28 polygons; DBCA-019 has a licence conflict (CC BY-NC on data.wa.gov.au, CC BY-SA on data.gov.au) and needs a SLIP login for bulk download |
| Architecture | Vector-first zonal statistics per wetland per scene | Kilobytes per scene, minutes per run, strongest incremental story |
| Verification | Every goal has an independent known-good reference and a tolerance | Requested explicitly; the first oracle already falsified the textbook water threshold |

Ramsar systems in scope: Forrestdale and Thomsons Lakes, Peel-Yalgorup
System, Becher Point Wetlands, and the draft Ellen Brook addition.

## Verified facts the design relies on

All checked live on 2026-10-29. Scripts are under `scratch/spikes/`.

- Earth Search v1 at `https://earth-search.aws.element84.com/v1` needs no
  auth. It advertises the query and sort extensions and not CQL2; a CQL2
  filter is silently ignored. Filtering on the `created` property works.
- Six MGRS tiles cover the Swan Coastal Plain: 50HLJ, 50HLK, 50HMJ, 50HMK,
  50JLL, 50JML, all EPSG:32750. Tile 50HMJ is revisited every 2 to 3 days,
  the others about every 5 days. Scenes appear in the catalogue about six
  hours after acquisition (02:26 UTC acquisition, 08:40 UTC `created`).
- `sentinel-2-c1-l2a` items carry `raster:bands` with scale 0.0001 and
  offset -0.1 on every reflectance asset, and a `product_metadata` asset
  (ESA MTD_MSIL2A.xml) stating BOA_QUANTIFICATION_VALUE 10000 and
  BOA_ADD_OFFSET -1000 for every band. Reflectance is DN times scale plus
  offset. Item properties carry ESA's SCL class percentages
  (`s2:water_percentage`, `s2:vegetation_percentage`,
  `s2:high_proba_clouds_percentage` and so on) and `eo:cloud_cover` equals
  the share of SCL classes 8, 9 and 10 among non-zero pixels.
- A 3 km window over Forrestdale Lake reads about 40 KB per 10 m band in 1
  to 3 seconds unsigned. Forrestdale Lake sits on the 50HLK and 50HMK seam.
  Thomsons Lake sits wholly inside 50HLK.
- The two tiles of the 27 October pass share the 10 m lattice, but the
  seam is not exact. Over the 68 by 202 pixel overlap in the Forrestdale
  window the reflectance differs between 50HLK and 50HMK: maximum absolute
  difference 0.0027 (green), 0.0029 (red), 0.0049 (nir) and 0.0045
  (swir16), with 3.1, 4.7, 0.8 and 0.0 pc of pixels equal. SCL agreed on
  99.97 pc of pixels and water class 6 on 100 pc. Aggregation across tiles
  must not assume identical pixels in the overlap (spike S1, `LEARNINGS.md`).
- Microsoft Planetary Computer hosts the same ESA products. For the 27
  October 50HLK scene the B03 window had an identical transform and
  bit-identical digital numbers to the Earth Search COG. Planetary Computer
  items carry no `raster:bands`, so their DN are the raw ESA values.
- DEA publishes `ga_s2_wo_provisional_3`, a Sentinel-2 Water Observations
  product at 10 m on the same EPSG:32750 grid, one item per pass, rolling
  three months, unsigned on `dea-public-data` (region ap-southeast-2). For
  the 27 October pass over Thomsons Lake it found 16,444 wet pixels, ESA
  SCL class 6 found 16,676, and McFeeters NDWI above zero found 5,845.
  Pixel agreement between NDWI above zero and DEA was 0.80.
- DEA Waterbodies v3 (Landsat, 1986 to present, CC BY 4.0) has per-lake
  CSV time series at
  `https://data.dea.ga.gov.au/derivative/dea_waterbodies/3-0-0/timeseries/<uid[:4]>/<uid>.csv`.
  Identifiers: Thomsons Lake `qd635epws_v3` (193.2 ha), Forrestdale Lake
  `qd63n1ww5_v3` (178.7 ha), Lake Clifton `qd4m2n3rj_v3`, Lake Preston
  `qd4k2967m_v3`. Peel Inlet and Harvey Estuary have no waterbody polygon.
  Forrestdale wet fraction was 0 from December 2023 to May 2024, against
  47 pc in January 2023 and 56 pc in January 2022.
- Ramsar boundaries (DBCA-010) download without login from the SLIP ArcGIS
  REST service, layer 9 of `SLIP_Public_Services/Environment/MapServer`,
  65 polygons statewide, native GDA2020.
- Packages resolve with uv for Python 3.12 to 3.14 on Apple Silicon:
  rasterio 1.5.2, pystac 1.15.2, pystac-client 0.9.1, odc-stac 0.5.3,
  geopandas 1.2.0, pyarrow 26.0.0, stac-geoparquet 0.8.3, duckdb 2.0.0,
  shapely 2.2.0, pyproj 3.8.0. Python 3.12 is the project pin to match the
  sibling repositories.
- The Earth Search sentinel-2-c1-l2a SCL COGs carry
  OVR_RESAMPLING_ALG=MODE with overviews 2, 4, 8 and 16. Reading the 1/16
  overview shifts the vegetation share by +2.04 pp (50HLJ) and -3.03 pp
  (50JML) on the 2026-10-27 pass, with not-vegetated moving the opposite
  way, while water and cloud stay within 0.05 pp; the full-resolution read
  matches the item percentages to three decimals (verify run,
  `LEARNINGS.md`).

## Architecture

One Python package (`wetland_change`), one CLI, one scheduled job. Every
run is a function of the catalogue state on S3, so reruns are safe.

### Run stages

1. Discover. Query Earth Search for `sentinel-2-c1-l2a` items intersecting
   the AOI union bbox, `created` at or after the ledger watermark minus one
   day, `eo:cloud_cover` under the configured threshold. Re-check cloud
   cover and polygon intersection client-side. Drop items already in the
   ledger with the same `updated` timestamp.
2. Plan. For each new item and each AOI polygon it covers, compute a pixel
   window on the scene grid snapped to the 20 m SCL grid so SCL aligns 2:1
   with the 10 m bands. Record the fraction of the polygon inside the scene
   footprint.
3. Read. Windowed reads of green, red, NIR, swir16 and SCL with the GDAL
   HTTP settings lifted from mine-footprint-seg. Reflectance is DN times
   scale plus offset from the item's `raster:bands`. DN zero is nodata.
4. Mask and compute. Drop SCL classes 0, 1, 2, 3, 8, 9, 10. Compute NDWI,
   MNDWI and NDVI. Rasterise the polygon as a pixel mask.
5. Summarise. One row per polygon per item (schema below).
6. Publish. GeoParquet 1.1 with the bbox covering column, one file per item
   under `observations/year=YYYY/tile=<MGRS>/obs_<item_id>.parquet`. Ledger
   of processed source items as stac-geoparquet under `ledger/year=YYYY/`.
   Run manifest beside the outputs.
7. Change. Score each new row against a per-polygon, per-month-of-year
   baseline (median and MAD of water hectares and NDVI from a backfill of
   2022-01-01 onward). Rows with robust z above 3 and valid fraction above
   0.8 become rows in `changes/`.
8. Catalogue. pystac Catalog, one Collection, one Item per source scene
   with the observations file, change file and optional per-polygon index
   COGs as assets. Absolute https links. Validated before upload.
9. Verify. Fetch the matching DEA, Planetary Computer and Copernicus
   references for the scenes just processed, score every row of the
   verification matrix, write `verification/<run_id>.json` as a catalogue
   asset and a dated Markdown report under `docs/research/`.

The scheduled job is a GitHub Actions cron near 10:00 UTC daily plus manual
dispatch, assuming an AWS role through OIDC. `backfill --start --end` runs
stages 1 to 6 and 8 over a date range. `verify` can run standalone.

### Components

| Path | Responsibility | Source to lift from |
|---|---|---|
| `config/pipeline.toml` | Endpoint, collection id, cloud threshold, water method and threshold, AOI files, bucket, partition scheme | wa-mine-rehab-monitor `config/d3.yaml` digest pattern |
| `src/wetland_change/aoi.py` | Load Ramsar GeoJSON and DEA Waterbodies polygons, filter, reproject to EPSG:32750 behind a CRS check, assign stable ids | geospatial-framework `crs.py`, crs-guard skill |
| `catalogue/search.py` | pystac-client search with retry, client-side re-checks, dedupe | land-clearing-detection `make_stac_retry`, `search_items` |
| `ledger.py` | stac-geoparquet ledger, watermark, failed-item retry count | land-clearing-detection `SceneManifestRow` pattern |
| `windows.py` | Window planning, 20 m snapping, coverage fraction | mine-footprint-seg `plan_windows` |
| `raster/read.py` | Windowed reads, GDAL env, transient retry, scale and offset | mine-footprint-seg `gdal_http_env`, `retry_transient`, `is_transient_error` |
| `indices.py` | NDWI, MNDWI, NDVI with zero-denominator guard | land-clearing-detection `_normalised_difference`, `ndvi` |
| `mask.py` | SCL class handling, nodata | land-clearing-detection `apply_fmask` adapted |
| `stats.py` | Polygon rasterisation and zonal summary | new |
| `outputs/geoparquet.py` | GeoParquet writer, partition paths, manifest | mine-footprint-seg `write_patch_index`, wa-mine-rehab-monitor manifest |
| `stac/catalogue.py` | Catalog, Collection, Item builders, validation, upload | new |
| `change.py` | Seasonal baseline and robust z scoring | new |
| `verify/` | One module per matrix row, report writer | new |
| `cli.py` | `discover`, `process`, `publish`, `backfill`, `run`, `verify`, `build-catalogue` | land-clearing-detection `cli.py` shape |
| `infra/` | OpenTofu: public-read bucket with CORS, OIDC provider and role | new |
| `.github/workflows/test.yml` | ruff, mypy, pytest, SHA-pinned actions | wa-mine-rehab-monitor |
| `.github/workflows/pipeline.yml` | Daily cron, dispatch, OIDC | new |
| `.github/workflows/verify.yml` | Weekly live contract and verification run | new |

Standards scaffolding: AGENTS.md, thin CLAUDE.md (research-code profile),
README.md, docs/handoffs, docs/decisions, docs/plans, docs/research,
data/SOURCES.md, LEARNINGS.md, `.python-version` 3.12, pyproject with uv,
ruff, mypy, pytest. A codename registry row and an inventory row in the
standards repository are follow-ups for Jarrod.

### Observation row schema

| Column | Type | Notes |
|---|---|---|
| `polygon_id` | string | Stable id from the AOI layer |
| `site` | string | Ramsar system name |
| `aoi_layer` | string | `ramsar` or `dea_waterbody` |
| `item_id` | string | Earth Search item id |
| `product_uri` | string | ESA product name for cross-host lookups |
| `datetime` | timestamp | Acquisition |
| `tile` | string | MGRS code |
| `processing_baseline` | string | From `s2:processing_baseline` |
| `scene_coverage` | float | Fraction of polygon inside the scene |
| `valid_fraction` | float | Clear pixels over polygon pixels |
| `cloud_fraction` | float | SCL 8, 9, 10 over polygon pixels |
| `water_ha_index` | float | Calibrated index method |
| `water_ha_scl` | float | SCL class 6 |
| `ndwi_median`, `mndwi_median`, `ndvi_median` | float | Over clear pixels |
| `dea_wo_agreement` | float or null | Pixel agreement with DEA S2 Water Observations when an item exists |
| `geometry` | polygon | Polygon geometry, EPSG:4326 in the file |
| `run_id` | string | Run manifest key |

Partition by `year` and `tile`. One file per item so a rerun overwrites
rather than appends. Rows for a polygon that straddles a seam appear once
per scene with `scene_coverage` below 1; a daily aggregate per polygon
weights by valid pixels.

### Water method

McFeeters NDWI above zero undercounts Thomsons Lake by two thirds against
both DEA and ESA SCL. The pipeline stores three water columns and the
method for `water_ha_index` is chosen by a pre-start spike: for every pass
in the last three months over the four lakes, compute agreement with DEA
S2 Water Observations for NDWI and MNDWI across a threshold sweep, and for
SCL class 6. The best method and threshold go into `config/pipeline.toml`
and the result into LEARNINGS.md as a pre-registered finding. SCL class 6
is always stored as the second signal.

### Change detection

Baseline per polygon and month of year from the backfill: median and MAD
of `water_ha_index` and `ndvi_median`. Score each new observation with a
robust z. Flag when absolute z is above 3 and `valid_fraction` is above
0.8. Store flags with the baseline values used. Seasonal drying is not
change under this design because the baseline is monthly.

Pre-registered hypotheses for LEARNINGS.md, to be tested by the backfill:

1. Forrestdale shows a low-water anomaly in December 2023 or January 2024
   (DEA Waterbodies: 0 wet fraction December 2023 to May 2024).
2. February to April of 2022 and 2023 at Forrestdale raise no anomaly.
3. Winter 2025 (June to August) at Forrestdale and Thomsons shows water at
   or above the baseline, with no dry-down flag.
4. Spearman correlation between pipeline water hectares and DEA
   Waterbodies wet fraction on passes within three days is at least 0.9.

## Known-good verification matrix

| Goal | Independent reference | Test and tolerance |
|---|---|---|
| Discovery finds every scene | Copernicus Data Space STAC `https://stac.dataspace.copernicus.eu/v1`, collection `sentinel-2-l2a`, free listing | Item count and product names per tile per month match Earth Search, allowing 24 h latency |
| Reads the right bytes | Planetary Computer `sentinel-2-l2a`, same ESA product, SAS token via the `planetary-computer` package | Same window: identical transform, bit-identical DN on a 10 m band |
| Reflectance scaling | ESA `product_metadata` XML on each item | `raster:bands` scale equals 1/BOA_QUANTIFICATION_VALUE and offset equals BOA_ADD_OFFSET/BOA_QUANTIFICATION_VALUE, asserted at run time for every item |
| SCL read and alignment | ESA SCL class percentages in item properties | Class shares (water, vegetation, not vegetated, cloud) recomputed from the full-resolution SCL within 1 pp of the item properties. Overviews are not used: the Earth Search SCL COGs build them with mode resampling, which biased vegetation and not-vegetated by 2 to 3 pp at 1/16 on the first live run (LEARNINGS.md, 2026-10-29) |
| Index arithmetic | spyndex 0.12.0 and dea-tools 0.4.10 `calculate_indices` | `assert_allclose` at 1e-6 on synthetic and fixture arrays |
| Water extent, live | DEA `ga_s2_wo_provisional_3`, same pass, same grid, bit 128 wet, bits 1, 2, 32, 64 excluded | Pixel agreement at or above 0.95 on mutually clear pixels; wet area within 5 pp |
| Water extent, history | DEA Waterbodies v3 CSV per lake; DEA `ga_ls_wo_3` per scene | Wet fraction over the DEA polygon within 10 to 15 pp on passes 1 to 3 days apart; Spearman at or above 0.9 over the backfill |
| NDVI | DEA `ga_s2am_ard_3`, `ga_s2bm_ard_3`, `ga_s2cm_ard_3` NBART, same acquisition, nodata -999 | Per-polygon median within 0.05, correlation above 0.95 |
| GeoParquet output | geoparquet-validator 0.2.0; DuckDB 2.0 and GDAL as independent readers | Validator exit 0 including the covering class; row counts and bounds agree across readers |
| STAC catalogue | stac-valid (successor of stac-validator), stac-check 1.14, pystac validate, stac-browser | All pass; bucket returns `Access-Control-Allow-Origin`; catalogue opens in stac-browser |
| Incremental and idempotent | pytest-regressions golden run; watermark replay | Byte-identical outputs on rerun; distinct count equals count after replay; ledger count per month equals the Copernicus count |
| Change detection | DEA Waterbodies Forrestdale record 2022 to 2025 | Hypotheses 1 to 4 above |
| Scheduled job alive | Earth Search and Copernicus counts per tile per 30 days | Ledger matches both; newest processed item under 7 days old; a failing freshness test opens a GitHub issue |
| End to end | `verify` command over the latest run | Report and JSON asset written; weekly `verify.yml` green |

## Error handling

- Transient HTTP and S3 errors retry with backoff. A failing scene is
  recorded in the ledger as failed with a retry count and retried on the
  next three runs. It never aborts the run.
- Watermark overlap of one day plus ledger dedupe on item id and `updated`
  handles late and re-published items.
- A schema guard on every item asserts the required asset keys and the
  scale and offset against the ESA XML, and fails the item if the
  collection id differs from config or an `earthsearch:boa_offset_applied`
  key appears.
- Client-side re-checks of cloud cover and intersection cover the silent
  filter ignore.
- Seam polygons produce one row per scene with a coverage fraction.
- Change flags require `valid_fraction` above 0.8.
- Endpoint, collection id and asset keys are pinned in config; the weekly
  live contract test catches drift.

## Testing strategy

- Unit tests on synthetic arrays for indices, masking, rasterisation,
  zonal statistics, window snapping and change scoring, written first.
- Offline fixtures: one real window over Thomsons Lake saved as a local
  GeoTIFF with its STAC item JSON and product XML, a few kilobytes, so
  read, scale and summarise run end to end without network.
- Live contract tests marked `live`, skipped by default, run weekly.
- Output validation tests using geoparquet-validator, DuckDB, stac-valid
  and stac-check.
- Idempotency test: same items twice, identical bytes.
- End to end on GitHub Actions by manual dispatch over a one-day window,
  then the reproducibility-audit skill as the final gate.
- Deliberate red tests use `xfail(strict=True)`.

## Pre-start spikes

Done in this session (results in the verified facts section): endpoint
and extension support, `created` filtering, offsets in both collections,
windowed read timing, the Forrestdale seam, package resolution, Ramsar
download, SCL percentage oracle, Planetary Computer pixel match, DEA S2
Water Observations comparison, DEA Waterbodies identifiers and history.

To do before the first implementation task, each under thirty minutes
unless noted:

1. Seam agreement: Forrestdale window from the 50HLK and 50HMK items of
   one pass; confirm identical grid alignment and DN in the overlap.
2. Water calibration (about two hours): threshold sweep for NDWI and MNDWI
   and SCL class 6 against DEA S2 Water Observations over three months of
   passes for the four lakes. Output: method, threshold, agreement table.
3. Largest polygon: time the Peel-Yalgorup main polygon window, roughly
   10 by 43 km, and confirm memory stays under 1 GB.
4. Backfill sizing: count c1 items from 2022-01-01 over the AOI under the
   cloud threshold and cross-check with the Copernicus count.
5. Runner dry run in a throwaway public repo: uv sync time, rasterio
   import, OIDC role assumption, minutes per run. Confirm Actions minutes
   are free on standard runners for public repositories.
6. Static catalogue: hand-written catalog.json on a bucket with CORS,
   opened in stac-browser.
7. DuckDB reads hive-partitioned GeoParquet from S3 with one glob.
8. Toolchain isolation: rasterio wheels with MacPorts GDAL on the path and
   `PROJ_LIB` unset.
9. Historical tolerance: DEA Waterbodies against DEA Landsat Water
   Observations on one lake to set the 10 to 15 pp band.

## Research still open

- NDWI versus MNDWI for seasonal, vegetated wetlands in south-west WA;
  DEA Water Observations method as the reference.
- Anomaly method alternatives to median and MAD, recorded in docs/research.
- Licence text for DBCA-010 for data/SOURCES.md; derived outputs inherit
  CC BY-SA 4.0. DEA products are CC BY 4.0.
- Earth Search v2 timeline (`sentinel-2-c1-l2a` becomes `sentinel-2-l2a`
  in v2, CQL2 supported) and the SNS topic
  `arn:aws:sns:us-west-2:608149789419:cirrus-es-prod-publish` as a future
  event-driven trigger.
- Whether reprocessed c1 items change `updated` reliably.
- What GitHub counts as repository activity for the 60-day scheduled
  workflow rule.
- DEA NBART scale factor (1e-4 per the dea-load-and-mask skill, not
  confirmed in STAC metadata).

## Challenges and planned answers

| Challenge | Answer |
|---|---|
| Offset double-correction | c1 collection only, offsets from metadata, run-time guard against the ESA XML |
| Textbook NDWI threshold fails on shallow vegetated lakes | Calibrate against DEA, store SCL water as a second signal, report agreement per row |
| Tile seams | Per-scene rows with coverage fraction, aggregate downstream |
| API drift and silent filter ignore | Pinned config, client-side re-checks, weekly live contract tests |
| 60-day Actions auto-disable | Commit the verification report on runs that processed scenes; freshness test opens an issue |
| Parquet is immutable | One file per scene, overwrite on rerun |
| Seasonal drying is not change | Month-of-year baseline |
| SCL weak over water and shadow | Valid-fraction gate, two water signals, DEA agreement column |
| Runner time and memory for Peel-Yalgorup | Spike 3 before code |
| Licence of derived outputs | BY-SA for Ramsar-derived rows, BY for DEA-derived checks, stated in SOURCES.md and the catalogue |
| IAM and OIDC friction | Spike 5 before pipeline code |
| DEA S2 Water Observations retains three months | Live oracle only; Landsat products for history |

## Non-goals for version one

Landsat, Sentinel-1, Lambda, the full DBCA-019 layer, machine-learning
change detection, any web map beyond stac-browser, Peel Inlet and Harvey
Estuary water verification (no DEA waterbody polygon).

## Success criteria

1. The job runs unattended daily for four weeks on GitHub Actions
   (freshness row of the matrix).
2. The catalogue opens in stac-browser and validates (STAC row).
3. DuckDB reads the observations from S3 with one query (GeoParquet row).
4. Every matrix row passes in the weekly verification report.
5. CI is green and the reproducibility audit passes.
6. README explains the design choices and the verification matrix to a
   reviewer.

## Sources

- Earth Search README: https://github.com/Element84/earth-search
- Earth Search offset issue: https://github.com/Element84/earth-search/issues/41
- Sentinel-2 COGs on AWS: https://registry.opendata.aws/sentinel-2-l2a-cogs/
- SCL classes: https://custom-scripts.sentinel-hub.com/sentinel-2/scene-classification
- Sentinel-2 processing baselines: https://sentiwiki.copernicus.eu/web/s2-processing
- DEA Waterbodies: https://knowledge.dea.ga.gov.au/data/product/dea-waterbodies-landsat/
- DEA Water Observations Sentinel-2: https://knowledge.dea.ga.gov.au/data/product/dea-water-observations-sentinel-2-nrt/
- DEA STAC: https://explorer.dea.ga.gov.au/stac
- DBCA-010 Ramsar sites: https://www.data.gov.au/data/dataset/ramsar-sites
- DBCA-019 Geomorphic Wetlands: https://catalogue.data.wa.gov.au/dataset/geomorphic-wetlands-swan-coastal-plain
- Perth 2023-24 rainfall: https://www.bom.gov.au/water/nwa/2024/perth/climateandwater/climateandwater.shtml
- spyndex: https://github.com/awesome-spectral-indices/spyndex
- dea-tools band indices: https://github.com/GeoscienceAustralia/dea-notebooks/blob/develop/Tools/dea_tools/bandindices.py
- geoparquet-validator: https://github.com/geoparquet/geoparquet-validator
- stac-validator and stac-check: https://github.com/stac-utils/stac-validator, https://github.com/stac-utils/stac-check
- GeoParquet 1.1: https://geoparquet.org/releases/v1.1.0/
- GitHub Actions scheduled workflow rule: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- GitHub Actions billing: https://docs.github.com/en/billing/concepts/product-billing/github-actions
- rasterio FAQ on PROJ and GDAL: https://rasterio.readthedocs.io/en/latest/faq.html
