# CDSE baseline 05.10 for the 2022 gap: design

Date: 2026-11-17. Approved by Jarrod section by section on 2026-11-17 in the
design session that followed his direction "use for 2022 gap" (2026-11-16).
Amends ADR 0001 through a new ADR 0018. ADR numbers 0014 and 0015 are held by
st-b6bf and st-dd0d, and 0017 went to the private-bucket decision on
2026-11-17 (renumbered from 0017 on Jarrod's approval that day).

## Purpose

Earth Search `sentinel-2-c1-l2a` holds no usable item over the AOI from
2022-01-01 to 2022-11-30 except one 50JLL scene (spike S4, LEARNINGS.md). The
change baselines, hypotheses H1 to H4 and the whole-history Spearman check all
start at 2022-12. Copernicus Data Space (CDSE) serves ESA's 2024 reprocessing
of those months at baseline 05.10. This design reads those products once,
verifies them against the Collection 1 path on the months both sources hold,
and merges them into the output store after the st-b6bf blindness window.

## Findings this design rests on

Measured 2026-11-16 and 2026-11-17 with scratch probes, not committed.

- Catalogue. CDSE STAC `sentinel-2-l2a` over the AOI bbox, cloud below 20
  percent: 216 items in 2022, all N0510 under `s3://eodata/Sentinel-2/MSI/L2A_N0500/`.
  From 2022-01-01 to 2022-11-30 there are 187 items on 186 acquisitions
  (sensing time, relative orbit, tile). One acquisition, S2B 2022-02-25
  R060 T50HMK, has two products. Earth Search c1 holds 1 of the 186; CDSE
  lacks none that c1 holds. The fill is 185 acquisitions: 50HLJ 25, 50HLK 33,
  50HMJ 28, 50HMK 30, 50JLL 34, 50JML 35.
- Assets. JP2 per band (`B03_10m`, `B04_10m`, `B08_10m`, `B11_20m`,
  `SCL_20m`) plus `product_metadata` (MTD_MSIL2A.xml), each with an `s3://eodata`
  href. There is no `raster:bands` array, but each band asset carries the
  STAC 1.1 fields `raster:scale` 0.0001, `raster:offset` -0.1, `nodata` 0,
  `data_type`, `proj:code` EPSG:32750, `proj:transform`, `file:size` and
  `file:checksum` (a multihash with prefix 1620, read as sha3-256). The items
  carry no item-level `proj:code`. The XML of the sampled product gives
  PROCESSING_BASELINE 05.10, BOA_QUANTIFICATION_VALUE 10000 and BOA_ADD_OFFSET
  -1000 per band. (Amended 2026-11-17 during story planning: the first probe
  looked only for `raster:bands` and reported no scaling metadata.)
- Access. The Sentinel Hub OAuth client is refused by the download service
  (HTTP 401, DAT-ZIP-609 "Token audience not allowed"). The eodata S3 key pair
  in 1Password (vault `luminosity`, item `swan-wetland`, fields `credential`
  and `password`, valid to 2027-11-01) reads both the XML and the JP2 files
  through botocore with endpoint `https://eodata.dataspace.copernicus.eu`,
  region `default`, path-style addressing.
- Speed. A 1024 by 1024 window read over GDAL `/vsis3/` takes about 29 s per
  10 m band and 3.9 s for SCL. Downloading the five band files of one scene
  takes about 31 s for 412 MB (about 14 MB/s); a local 1024 window then reads
  in 0.1 to 0.2 s. `rasterio.Env` refuses AWS credential options unless boto3
  is installed.
- Overlap. From 2022-12-01 to 2023-02-28 Earth Search c1 holds 80 items, all
  baseline 05.09 (ESA's original processing). CDSE holds 81, all N0510. No
  product name is shared; all 80 Earth Search acquisitions have a CDSE
  counterpart. The overlap test therefore compares two processing baselines of
  one acquisition and cannot require identical values.
- Code. Every c1 guard refuses a CDSE item: the `StacConfig` validator
  (`config.py`), `parse_item` (collection, `raster:bands`, `s2:product_uri`,
  `s2:processing_baseline`, asset keys), and `verify --run-id`, which reparses
  each ledger `source_item` with the c1 guard (`verify/run.py`). `RasterioReader.read_text`
  reads http(s) or a local path, not `s3://`. `backfill` writes observations,
  ledger parts and a manifest but does not score or build the catalogue. The
  catalogue credits Element 84 as provider for every item.

## Decisions in the design session

1. Merge timing: stage now, merge later. The backfill is built, run and
   verified into local staging roots now. The rows enter the shared store only
   after st-b6bf's decision files are committed (its sample closes by
   2026-12-31 at the latest).
2. Approach: a separate CDSE adapter. The alternatives were a multi-source
   generalisation of config, `discover` and `parse_item`, rejected because it
   changes code the st-b6bf rows reuse and `config/pipeline.toml` during both
   samples, and synthetic c1 items, rejected because they would carry the
   collection id `sentinel-2-c1-l2a` for data that is not from it.
3. Sections 1 to 3 below were approved as presented.

## Scope rule

CDSE supplies an acquisition only if it was sensed from 2022-01-01T00:00:00Z
to 2022-11-30T23:59:59Z, has cloud cover below the configured 20 percent,
intersects the AOI footprint, has baseline 05.xx, and Earth Search c1 holds no
item for the same sensing time, relative orbit and tile. The c1 holdings come
from Earth Search STAC metadata, never from the output store. Where one
acquisition has more than one product, the product with the newest processing
time is kept and the others are logged as rejections.

## Components

All new code sits outside `src/wetland_change/verify/`.

- `sources/cdse.py`, search. Queries `https://stac.dataspace.copernicus.eu/v1`
  collection `sentinel-2-l2a` with the pipeline's AOI bbox and applies the
  scope rule. Every refused item is returned with its reason.
- `sources/cdse.py`, download. A botocore S3 client on the eodata endpoint
  fetches B03, B04, B08, B11, SCL and MTD_MSIL2A.xml into a per-scene directory
  under a cache directory (default the untracked `scratch/cdse-cache/`), and
  checks each file's size and sha3-256 against the asset's `file:size` and
  `file:checksum`. Keys come from `CDSE_S3_ACCESS_KEY` and
  `CDSE_S3_SECRET_KEY`, set from 1Password at launch and never printed,
  logged or stored.
- `sources/cdse.py`, adapter. Builds the existing `SceneItem` with
  `collection="sentinel-2-l2a"`, bands keyed `green`, `red`, `nir`, `swir16`
  whose hrefs are the local JP2 paths, `scl_href` the local SCL path and
  `product_metadata_href` the local XML. Scale, offset and nodata come from
  each band asset's `raster:scale`, `raster:offset` and `nodata`, and the
  unchanged `check_band_scaling` checks them against the XML at run time, as
  for c1. The adapter also refuses a product whose scale or offset differs
  from the values the stored c1 history uses (0.0001 and -0.1), so the series
  stays on one radiometric scale. (Amended during story planning; the approved
  version took scale and offset from the XML because the asset fields had not
  been seen.)
- `backfill-cdse` command. `wetland-change backfill-cdse --start --end
  --output-root [--keep-downloads] [--now]`. For each scene it downloads,
  adapts, runs the unchanged `process_scene` with the plain `RasterioReader`
  on the local files, writes observations and a ledger part tagged `backfill`,
  then deletes the scene's cache unless `--keep-downloads` is set. It writes
  one run manifest. CDSE settings live in a new `config/cdse-backfill.toml`.

## Unchanged code

`discover`, `parse_item`, the config validator, `process_scene`,
`check_band_scaling`, `read_stack`, everything under `src/wetland_change/verify/`,
`config/pipeline.toml`, `.github/workflows/pipeline.yml` and
`scripts/fetch_aoi.py` stay byte-identical, so the scheduled pipeline behaves
as before and neither pre-registration's code changes. The observation schema
does not change; the ledger's `collection` column and `source_item` record
the source of each row.

`check_band_scaling` runs on CDSE scenes unchanged and compares the assets'
`raster:scale` and `raster:offset` with the XML, the same cross-check c1
scenes get.

## Verification

Pre-registration. Before the overlap run, a dated section is appended to
LEARNINGS.md with the rules below, the definition of a matched row, and the
values reported without deciding anything.

Overlap test, the gate. Both paths run over 2022-12-01 to 2023-02-28, each into
its own staging root: the existing `backfill` from Earth Search c1 and
`backfill-cdse --keep-downloads` from CDSE. A matched row is one acquisition
and one polygon with `valid_fraction` above 0.8 from both sources, the change
detector's own floor. A comparison script reads both pixel stacks and applies
each polygon's configured water setting.

| Rule | Measure | Pass |
|---|---|---|
| O1 | Pooled water-call agreement over pixels clear in both sources | at least 0.98 |
| O2 | Share of matched rows whose wet-share difference is within 5.0 pp (the ADR 0006 clause) | at least 95 percent |
| O3 | Median absolute difference of `ndvi_median` over matched rows | at most 0.02 |

Reported, not decision inputs: SCL class 6 water, `valid_fraction`
differences, a per-tile breakdown, and rows present on one side only. The
numbers are a proposal approved with the design; no 05.09 against 05.10
difference has been measured in this project. If any rule fails, nothing is
merged, ADR 0018 records the rejection and the README limitation stands.

Gap-row checks, reported. A research script calls the existing verify
functions unchanged on the staged 2022-01 to 2022-11 rows against two
independent references: the per-pass DEA Waterbodies wet fraction (within
10 pp and 3 days) and NDVI against DEA NBART, which holds 2022. As for every
backfill row (ADR 0009), `dea_wo_agreement` stays null.

## Merge

After st-b6bf's decision files are committed:

1. Append a dated LEARNINGS.md section that re-tests H1 to H4 on the extended
   history, leaves the recorded results untouched, and states the Spearman
   recalibration by ADR 0007's rule: the floor to 0.01 of the lowest per-lake
   rho minus 0.02.
2. Compute the recalibrated threshold read-only over the store plus the
   staged rows.
3. Copy the staged CDSE observations, ledger part and run manifest into the
   store unchanged and compare checksums.
4. Run `compact-ledger`, `score --start 2022-01-01 --end <today>` and
   `build-catalogue`.
5. Commit the `spearman_min` update in the same window, before the next
   scheduled run at 10:17 UTC. If st-dd0d's sample is still open, its rule
   lists that commit, which the rule allows.

AWS credentials for the store come from the `accu-tracker` `aws login`
profile and expire 15 minutes after export, so they are re-exported before
each S3 step.

## Blindness

Staging never reads the shared output store and never reads a confirmatory
scene (ramsar-21 passes from 2026-11-12). st-b6bf's "no pixel read" outside
its script is read as applying to confirmatory items, as its last sentence
states, so pixel reads of 2022-01 to 2023-02 scenes are allowed now.

## Error handling

- Missing keys: `backfill-cdse` refuses to start and names both variables and
  the 1Password item, never the values.
- HTTP 401 or 403 from eodata: the run stops at once, since every scene would
  fail the same way.
- Transient errors (5xx, dropped connections): up to three attempts through
  the existing `retry_transient`.
- Size or checksum mismatch, asset scale or offset different from the c1 values, a baseline
  other than 05.xx, or an EPSG or grid mismatch: a failed ledger row with the
  reason, the partial download deleted, and a retry on rerun up to the
  existing three-attempt cap.
- Out-of-scope items (outside the window, acquisitions c1 holds, older
  duplicate products): refused at search and logged as rejections with a
  reason, never dropped silently.

## Testing

Default suite, offline:

- Adapter on a trimmed real CDSE item and MTD XML as fixtures: asset mapping,
  scale, offset and nodata from the asset fields, refusal of different scaling or a
  04.xx baseline, `collection` recorded as `sentinel-2-l2a`.
- Scope rule: window edges, exclusion of c1-held acquisitions, duplicate
  products keeping the newest.
- Downloader with a stub S3 client: size mismatch fails the scene, 403 stops
  the run, the cache is removed.
- `backfill-cdse` end to end on small synthetic JP2 files (GDAL's JP2OpenJPEG
  driver is present) through the unchanged `process_scene` into a temporary
  store: rows, the ledger `collection`, and the Copernicus notice footer.
- Comparison script: O1 to O3 on synthetic stacks with exact arithmetic.

Live (`-m live`): download the 1.5 MB SCL band of one gap item, skipped when
the keys are absent. The four gates as usual.

## Documents

- ADR 0018 "CDSE baseline 05.10 for the 2022 gap", amending ADR 0001: the
  scope rule, scaling from the XML, the overlap rules, the two answers above,
  and later the results and the merge record. Status proposed; accepted only on
  Jarrod's approval after the overlap results.
- AGENTS.md: both locked rules ("Only collection `sentinel-2-c1-l2a`" and
  "Reflectance is always DN times scale plus offset read from the item's
  `raster:bands`") gain "except as ADR 0018 allows for acquisitions from
  2022-01 to 2022-11 that c1 lacks".
- README: a CDSE eodata row in the data sources table, `backfill-cdse` in the
  backfill section with the credential route, and the 2022 gap limitation
  rewritten once the merge lands.
- data/SOURCES.md: a new row for CDSE eodata pixels with licence Copernicus
  Sentinel data terms, `redistribute_public` true, CRS EPSG:32750, and as
  checksum the sha256 of a committed manifest listing each product name and
  file size.
- Catalogue: CDSE items get an ESA/CDSE provider and a `derived_from` link to
  the CDSE STAC item instead of the Element 84 credit.

## Risks and open points

- The overlap thresholds are unmeasured proposals. If 05.10 changed the SCL
  cloud mask materially, O1 can fail on clear-mask differences alone; the
  reported `valid_fraction` differences show whether that happened.
- Rows from 2022-01 to 2022-11 shift every later change baseline, the H1 to
  H4 results and the Spearman series. The merge records new results in a new
  section and leaves the old ones in place.
- The merge date depends on when st-b6bf's sample closes, at the latest
  2026-12-31 plus its decision run.
- CDSE item fields `created` and `updated`, required by `SceneItem`, are to be
  confirmed on a real item during implementation.
- Transfer is about 110 GB for 185 gap and 80 overlap scenes, about 2.5 hours
  sequentially at the measured rate. CDSE S3 quotas are to be checked before
  the full run.
