---
id: st-2522
title: "Spike S9: set the historical wet-fraction tolerance"
type: spike
epic: st-1d45
priority: P2
depends_on: []
touches: [LEARNINGS.md, docs/research/2026-10-30-waterbodies-tolerance.csv]
exclusive: false
gates: [test]
created: 2026-10-29
updated: 2026-10-29
---
## Description

Spike S9 from the design's pre-start list: compare DEA Waterbodies v3 wet fraction, from the per-lake CSV whose URL pattern is in the design's Verified facts, with DEA Landsat Water Observations `ga_ls_wo_3` per scene over one lake. Use Thomsons, uid qd635epws_v3, 193.2 ha. The result sets the 10 to 15 pp tolerance band that the history check uses.

Both products are CC BY 4.0 and unsigned (DEA STAC `https://explorer.dea.ga.gov.au/stac`, bucket `dea-public-data`). The waterbody polygons are in `data/external/dea_waterbodies_v3_swan.geojson` after `uv run python scripts/fetch_aoi.py`. Use passes from 2022-12 onward. Work in the gitignored `scratch/spikes/`.

## Acceptance Criteria

- [ ] `docs/research/<date>-waterbodies-tolerance.csv` has one row per pass with date, Waterbodies wet fraction, `ga_ls_wo_3` wet fraction and difference.
- [ ] LEARNINGS.md gains a dated "S9 historical tolerance" section with the pass count, median, 90th percentile and maximum absolute difference, and the chosen tolerance in percentage points.
- [ ] No file under `src/` or `config/` changes in this story.

## Implementation Plan

## Verified against the worktree (st-2522)

- Branch is clean; `scratch/` and `data/*` are gitignored, `data/external` does not exist in the worktree, so it must be symlinked from `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/feature/wetland-change-pipeline/data/external` (holds `dea_waterbodies_v3_swan.geojson`, `dbca_010_ramsar_sites.geojson`). No refetch.
- Thomsons feature `qd635epws_v3` is in the geojson: `area_m2` 1932300 (= 2147 Landsat 30 m pixels exactly, so the polygon is pixel-aligned), `timeseries` URL `https://data.dea.ga.gov.au/derivative/dea_waterbodies/3-0-0/timeseries/qd63/qd635epws_v3.csv`.
- CSV live (verified): columns `date,pc_wet,px_wet`, date is an ISO timestamp of the Landsat pass, `pc_wet` is percent (0 to 100), blank on invalid passes. Check: 1941 px / 2147 px = 90.41, so the Waterbodies denominator is all polygon pixels.
- DEA STAC `https://explorer.dea.ga.gov.au/stac`, collection `ga_ls_wo_3` is live, returns one item per scene/frame (two items can share a date, e.g. 2022-12-02T02:06:01 and 02:06:25). Asset `water` is a uint8 COG at `s3://dea-public-data/derivative/ga_ls_wo_3/1-6-0/<path>/<row>/<yyyy>/<mm>/<dd>/..._final_water.tif`, 30 m, nodata=1, **proj:code EPSG:32650 with negative northings** (not 32750), so the polygon must be reprojected to each item's `proj:code`.
- WO bit flags: 1 nodata, 2 noncontiguous, 4 low solar angle, 8 terrain shadow, 16 high slope, 32 cloud shadow, 64 cloud, 128 wet. "Clear wet" is value 128 with none of the other bits.
- `src/` and `config/` must not change. New files: `scratch/spikes/s9_tolerance.py` (ignored), `docs/research/<date>-waterbodies-tolerance.csv` (tracked; date = run date, expected 2026-10-30), edit to `LEARNINGS.md` (new section under "## Spike results", before "## Live run findings" at line 177).
- Project env: `uv run` from the worktree; rasterio, geopandas, pystac-client, numpy, requests are already dependencies. `PROJ_LIB` must stay unset (it is unset now).

## Steps

1. Setup: symlink `data/external`, confirm `env | grep PROJ_LIB` is empty, `mkdir -p scratch/spikes`.
2. Write `scratch/spikes/s9_tolerance.py` (one script, run with `uv run python scratch/spikes/s9_tolerance.py`):
   - Load Thomsons polygon (`uid == qd635epws_v3`) from the geojson (EPSG:4326). Assert `area_m2` about 1932300.
   - Fetch the CSV with requests; parse; keep rows with date >= 2022-12-01; split into valid (`pc_wet` not blank) and invalid; report both counts. `waterbodies_wet_fraction = pc_wet / 100`.
   - STAC search (pystac-client on `https://explorer.dea.ga.gov.au/stac`, collection `ga_ls_wo_3`, bbox = polygon bounds, datetime 2022-12-01 to today). Group items by UTC date.
   - For each valid Waterbodies date, take the items for that date whose footprint intersects the polygon. Read the `water` COG window over the polygon bounds with rasterio using `AWS_NO_SIGN_REQUEST=YES` (`/vsis3/dea-public-data/...`, or the https S3 endpoint if vsis3 fails), after reprojecting the polygon to the item's `proj:code`. Rasterise with `rasterio.features.geometry_mask(all_touched=False)` on the window transform; assert the polygon pixel count is 2147 (or within 1 pct; record if not). If two items cover the polygon (frame seam), combine per pixel (a pixel counts if any item has it as a valid clear observation).
   - WO wet fraction, matching the Waterbodies convention: `wet = (water == 128)` among polygon pixels, divided by the TOTAL polygon pixel count. A pass is usable only if the clear-pixel share is high enough that Waterbodies also kept it (Waterbodies already blanks invalid passes, so only dates valid in the CSV are compared). Also compute `valid_fraction` (pixels with no nodata/cloud/shadow/noncontiguous flags) for diagnostics.
   - Join on date; a Waterbodies pass with no WO item is logged and dropped from the comparison (count them). Output `docs/research/<YYYY-MM-DD>-waterbodies-tolerance.csv` with columns `date,waterbodies_wet_fraction,wo_wet_fraction,difference,valid_fraction` where fractions are 0 to 1 and `difference = waterbodies_wet_fraction - wo_wet_fraction` (signed fraction; x100 for pp). Sorted by date, ISO dates (YYYY-MM-DD).
   - Print: pass count, median, 90th percentile and maximum of `abs(difference) * 100` in pp, count of dropped passes, and the largest 5 differences with dates.
   - Built-in sanity assertions (the spike's tests): CSV has one row per date (no duplicates), every fraction in [0,1], row count > 50, polygon pixel count check above, and a spot check that for 2026-10-10 the WO fraction is within 5 pp of 0.9041 if that date is in range.
3. Run it. If Waterbodies and WO differ by about 0 on most passes (expected: Waterbodies v3 is derived from the same ga_ls_wo_3 data), state that and still report the numbers; investigate any pass with a difference above 5 pp (frame seam, validity threshold) before choosing the tolerance.
4. Choose the tolerance by this rule and record it: the smallest whole number of pp in 10..15 that is at least the 90th percentile of absolute difference; if p90 is below 10 use 10; if p90 exceeds 15 use 15 and say the band is exceeded and why. Record the rule in LEARNINGS.
5. Add to `LEARNINGS.md`, inside "## Spike results" before "## Live run findings", a section `### S9 historical tolerance (<run date>)` stating: lake and uid, 193.2 ha, window (2022-12 onward), pass count compared, passes dropped, median, 90th percentile and maximum absolute difference in pp, the chosen tolerance in pp, the rule, any explanation for the largest differences, and a pointer to the CSV path. Match the flat factual prose style of the other sections (no em dashes, no editorial lead-ins).
6. Verify: `git status --short` shows only the CSV and `LEARNINGS.md` (scratch and data are ignored); `git diff --stat -- src config` is empty; CSV row count equals the reported pass count; reported stats in LEARNINGS equal a fresh `pandas`/numpy recompute from the CSV. Run `uv run pytest` and `uv run ruff check` to confirm nothing else changed state (no new tests; this is a spike). Commit the CSV and LEARNINGS.md only.

## What each check proves
- Pixel count assertion: the polygon rasterisation matches the Waterbodies footprint, so differences are not a mask artefact.
- 2026-10-10 spot check: the WO read and denominator convention reproduce a known Waterbodies value (90.41 pc).
- Recompute from CSV: LEARNINGS numbers are traceable to the committed artefact.
- Empty `git diff -- src config`: acceptance criterion 3.

## Implementation Notes

## Questions
