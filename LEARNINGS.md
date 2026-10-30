# Learnings

Pre-registered hypotheses and spike results. Append only; never rewrite a
recorded result.

## Pre-registered hypotheses (design, 2026-10-29)

1. Forrestdale shows a low-water anomaly in December 2023 or January 2024.
   Reference: DEA Waterbodies `qd63n1ww5_v3`, wet fraction 0 from December
   2023 to May 2024. Tested by the Milestone 2 backfill.
2. February to April of 2022 and 2023 at Forrestdale raise no anomaly.
3. Winter 2025 at Forrestdale and Thomsons shows water at or above the
   baseline, with no dry-down flag.
4. Spearman correlation between pipeline water hectares and DEA Waterbodies
   wet fraction on passes within three days is at least 0.9.

## Pre-registered hypotheses (st-2048, 2026-10-30)

5. The per-polygon water settings of decision 0005 hold on passes acquired
   after 2026-10-29. For each polygon, pooled `water_vs_dea_s2_wo`
   agreement (agreeing pixels over mutually clear pixels, summed over its
   passes) is at or above its agreement_min: ramsar-15 with scl6 at least
   0.94 (in sample 0.9682), ramsar-28 with ndwi above -0.15 at least 0.92
   (0.9438) and ramsar-56 with mndwi above 0.05 at least 0.95 (0.9795).
   Each polygon fails at most one scored pass in ten (in sample: 1 of 10,
   0 of 22 and 1 of 19). Assessed when a polygon has ten scored passes
   acquired after 2026-10-29. The calibration covers August to October 2026
   only, so these passes are out of season as well as out of sample.

## Pre-registered hypotheses (st-d457, 2026-10-30)

6. NDWI, MNDWI and NDVI from `wetland_change.indices` equal dea-tools 0.4.10
   `calculate_indices` output at `assert_allclose` with atol 1e-6 and rtol 0,
   on synthetic float arrays (seed 42, uniform reflectance 0 to 0.6) and on
   the Thomsons fixture window (tests/fixtures/thomsons_20261027,
   reflectance from the item's raster:bands scale and offset, nodata as
   NaN). The comparison is made with collection 'ga_s2_3' and
   normalise=False, so nbart_green is B03, nbart_red is B04, nbart_nir_1 is
   B08 and nbart_swir_2 is B11. NaN positions also match. Run once as a
   one-off from the pinned PyPI wheel with xarray as an overlay; spyndex in
   tests/test_indices.py stays the standing check.

## Spike results

### S1 Forrestdale seam (2026-10-29)

Pass 2026-10-27T02:26, items S2C_T50HLK_20261027T022351_L2A and
S2C_T50HMK_20261027T022351_L2A. Lattices align (origins differ by a
multiple of 10 m; window origins 398920 and 399960 at northing 6442480).
Window coverage 1.000 in 50HLK (172 x 202 px) and 0.363 in 50HMK (68 x 202
px). Overlap 68 x 202 px. Reflectance bands identical: no. Max |diff| and
share of pixels equal (n=13736 valid in both): green 0.00270 and 0.0306,
red 0.00290 and 0.0466, nir 0.00490 and 0.0084, swir16 0.00450 and 0.0000.
SCL agreement 0.9997, water class agreement 1.0000.
Consequence: the tiles are resampled separately, so the overlap is not
bit-exact and the differences are a few thousandths of reflectance (up to
about 0.005). Per-scene rows with a coverage fraction remain sufficient for
Milestone 1. Milestone 2 aggregation must not treat the two tiles'
Forrestdale pixels as identical duplicates; it should pick one tile per
pixel (for example the one with higher coverage) or accept differences of
this size, and the water decision (SCL class 6) is unaffected in this pass.

### S3 largest polygon (2026-10-29)

ramsar-27, 15555 ha (extent 13.9 x 30.4 km), window 3042 x 1392 px on 50HLJ
(coverage 1.000; the remainder, 936 x 1392 px at coverage 0.412, is in 50HLK,
not 50HMJ). Six windows over three passes (2026-10-12, 10-27, 10-29). Read
20.8 to 24.7 s for the 3042 x 1392 window (9.0, 10.7 and 7.3 s for the 50HLK
part), summarise 0.1 s. Peak RSS 518 MiB (start 173 MiB). Under the 1 GiB
runner budget: yes.

### S4 backfill count (2026-10-29)

Earth Search c1 under 20 % cloud since 2022-01-01: 996 items over 6 tiles
(50HLJ 145, 50HLK 169, 50HMJ 149, 50HMK 173, 50JLL 175, 50JML 185). CDSE:
1194 (50HLJ 172, 50HLK 204, 50HMJ 183, 50HMK 204, 50JLL 209, 50JML 222;
`grid:code` was present on CDSE items, so no fallback was needed). Tile-months
with fewer c1 than CDSE: 71 of 337, largest gap 50JLL 2022-01 (c1 0, CDSE 7),
tied with 50JML 2022-01. 59 of the 71 have zero c1 items, all in 2022-01 to
2022-11: c1 starts 2022-12 for five tiles and 2022-03 for 50JLL, so the c1
collection has no 2022 history before those months. From 2022-12 on the 12
remaining differences are 1 or 2 items (for example 50HMJ 2025-07: 5 vs 7),
consistent with CDSE reprocessed duplicates. At 25 s per scene (assumption,
from S3: 20.8 to 24.7 s read and 0.1 s summarise for the largest polygon's
main window; S3 did not time a whole-scene, all-polygon read) the backfill of
996 c1 items takes about 6.9 h of runner time. Table in
docs/research/2026-10-29-backfill-count.csv.
Consequence: a c1-only backfill covers 2022-12 onward for most tiles; the
2022 gap needs another source (CDSE, or the Earth Search sentinel-2-l2a
collection) if Milestone 2 wants the full five years.

### S8 toolchain isolation (2026-10-29)

rasterio 1.5.2 (GDAL 3.12.2), pyproj 3.8.0 (PROJ 9.8.1), data dir
.venv/lib/python3.12/site-packages/pyproj/proj_dir/share/proj (the wheel's
own copy). `command -v gdalinfo` is /opt/local/bin/gdalinfo (MacPorts), but
the wheels do not use it; PROJ_LIB, GDAL_DATA and PROJ_DATA are all unset in
the shell. Unaffected by PROJ_LIB and GDAL_DATA: no. The as-is run and the
run with PROJ_LIB, GDAL_DATA and PROJ_DATA unset print identical versions,
data dir, fixture CRS (32750, res 10 m) and EPSG:32750 WKT. With
PROJ_LIB=/opt/local/share/proj (a directory that does not exist on this
machine) the rasterio wheel fails: "ERROR 1: PROJ: internal_proj_create_from_database:
Cannot find proj.db", the fixture CRS reads as None and
CRS.from_epsg(32750) raises CRSError. pyproj itself still reported its wheel
data dir in that run. So an exported PROJ_LIB overrides the wheel's bundled
PROJ data for rasterio; keep PROJ_LIB unset in the shell profile. The script
exits 1 on the third run because of this. Fixture generated with the same
versions: scripts/make_fixture.py runs in this virtualenv (rasterio 1.5.2,
pyproj 3.8.0); the versions are not stored in the fixture files.

### S2 water calibration (2026-10-29)

44 lake-scene pairs from 37 items (c1, cloud cover under 20 percent, last 90
days), four largest DEA Waterbodies polygons inside the Ramsar sites
(dea-qd635epws_v3 Thomsons, dea-qd63n1ww5_v3 Forrestdale, dea-qd4mcnhg0_v3,
dea-qd4m02w8q_v3). Pixel-weighted agreement with DEA S2 WO:
NDWI best threshold -0.30 at 0.8660 (the edge of the sweep range); MNDWI best
threshold -0.10 at 0.9303; SCL class 6 at 0.9144. Chosen: mndwi at -0.1. Per-lake
table in docs/research/2026-10-29-water-calibration.csv (the zero threshold
rows are written as -0.0). The uncalibrated NDWI > 0 scored 0.5295 on
Thomsons over its scored scenes (213219 pixels) (the 2026-10-27 pre-start
number was 0.80). Best agreement is below 0.95, so the `wo_check`
agreement_min default is lowered from 0.95 to 0.91 (0.9303 minus 0.02, rounded
down). The live test test_water_agrees_with_dea_wo now reads the calibrated
[water] section from config/pipeline.toml and passes at 0.91.

### Per-polygon water calibration (2026-10-29)

Scope: ramsar-15, ramsar-28 and ramsar-56, the three polygons that failed
water_vs_dea_s2_wo at the global setting. The Earth Search search (c1, cloud
cover under 20 percent, last 90 days, bbox over the three polygons) returned 37
items; 29 of them had a scoreable window, giving 51 polygon-scene passes
between 2026-08-03 and 2026-10-29. DEA ga_s2_wo_provisional_3 keeps about 3
months, so these are the only passes available now. Passes and mutually clear
pixels by polygon: ramsar-15 10 passes (tile 50HLJ), 57288 pixels; ramsar-28 22
passes (10 on 50HLJ, 12 on 50HLK), 126489 pixels; ramsar-56 19 passes (12 on
50HLK, 7 on 50HMK), 345217 pixels. Total 528994 pixels. Agreement is pixel
weighted, sum(n_agree) / sum(n_mutually_clear), over subset=all rows. The sweep
covered NDWI and MNDWI at thresholds -0.50 to 0.50 in steps of 0.05, plus SCL
class 6. wetland_change.config.WaterConfig accepts only ndwi and mndwi, so scl6
cannot be expressed in config today. Applying scl6 to ramsar-15 needs a config
change that a later story must decide; this story changes no config and no code.
The ndwi -0.45 setting below is the best the current config can express.

Proposed settings (agreement_min is pooled agreement minus 0.02, rounded down
to 2 decimals, the S2 convention):
- ramsar-15: method scl6 (class 6, no threshold), agreement 0.9682,
  agreement_min 0.94. Failing passes at agreement_min: 1 of 10 (2026-09-17,
  0.9384). Best setting the config can express: method ndwi, threshold -0.45,
  agreement 0.7814, agreement_min 0.76. wo_check applies agreement_min to each
  pass, not to the pooled figure, and this setting fails 6 of 10 passes
  (2026-09-12 0.4800 on 300 pixels, 08-03 0.6439, 09-07 0.6107, 09-17 0.7247,
  10-02 0.6273, 10-12 0.6145). No ndwi or mndwi setting lets ramsar-15 pass
  most of its passes: the best any of them manages with its own pooled
  agreement_min is 4 of 10 failing. It is not a viable fallback.
- ramsar-28: method ndwi, threshold -0.15, agreement 0.9438, agreement_min 0.92.
  Failing passes at agreement_min: 0 of 22 (worst 0.9202, 2026-08-30, 50HLJ). Selection
  rule: take the best pooled setting, and prefer mndwi -0.1 only when it is
  within 0.005 of the best (it is not: 0.9296). The near-equal alternative is
  mndwi 0.05, pooled 0.9414, 0.24 percentage points below ndwi -0.15; ramsar-56
  uses that same setting.
- ramsar-56: method mndwi, threshold 0.05, agreement 0.9795, agreement_min 0.95.
  Failing passes at agreement_min: 1 of 19 (2026-08-28, 50HLK, 0.9487).

For context, the global setting (method mndwi, threshold -0.1) scores 0.6311 on
ramsar-15, 0.9296 on ramsar-28 and 0.9541 on ramsar-56 (0.9132 pooled over the
three). SCL class 6 scores 0.9682, 0.8485 and 0.8875 (0.8869 pooled).

One setting for all three: the best pooled setting is method mndwi, threshold
0.05, at 0.9311. It loses nothing on ramsar-56 (0.9795, equal to its own best),
0.24 percentage points on ramsar-28 (0.9414 against 0.9438), and 16.5
percentage points on ramsar-15 (0.6169 against 0.7814 for its best
ndwi/mndwi setting, 35.1 against SCL class 6). Pooled over ramsar-28 and
ramsar-56 alone it scores 0.9693 (0.9475 at mndwi -0.1). One setting serves
ramsar-28 and ramsar-56 but not ramsar-15.

ramsar-15 is the odd one. Its MNDWI and NDWI agreement swings by pass (MNDWI at
-0.1 is about 0.50 on 2026-08-03, 08-28, 09-17, 10-02 and 10-12, about 0.90 on
08-30 and 10-29) while SCL class 6 stays between 0.9384 and 0.9754 on every full-size pass. The
2026-10-27 pass scores 0.576 at mndwi -0.1, 0.6887 at mndwi -0.25, 0.8815 with
ndwi -0.45 and 0.9615 with scl6. Because SCL class 6 agrees with DEA WO on
every pass, the outlier is in the index values, not in the scene or the WO
layer. Unconfirmed inference: this 68 ha polygon holds shallow or turbid
water whose green/SWIR contrast sits near the threshold, so small changes in
water colour between passes flip most of its pixels. It has not been checked
at pixel level.

Seam, ramsar-56: at the chosen setting (mndwi 0.05) agreement is 0.9786 on
50HLK against 0.9844 on 50HMK, a 0.58 percentage point difference (HMK higher),
over all in-scene pixels (12 and 7 passes). On the seam-overlap pixels only
(the 7 dates with both tiles, 61574 and 55754 pixels) it is 0.9839 against
0.9844, 0.05 percentage points. At the global setting (mndwi -0.1) the
difference is 0.29 percentage points in scene (0.9545 against 0.9516) and 0.20
on the overlap (0.9536 against 0.9516). The seam does not explain the lower
ramsar-56 agreement at the global setting; the threshold does (0.9541 at -0.1
against 0.9795 at 0.05).

Per-pass rows for every polygon, pass, method and threshold, including the
seam_overlap subset, are in docs/research/2026-10-29-polygon-calibration.csv.
The scripts that produced it (scratch/spikes/polygon_calibrate.py and its log)
are untracked in scratch/spikes/.

Correction (2026-10-30). The unconfirmed inference above about ramsar-15 is
wrong: its missed water is not near-threshold water. On the live re-run of
the 2026-10-12 pass, green BOA reflectance is at or below 0 on 74 percent of
the pixels DEA WO calls wet (median -0.0006), and the DEA-wet pixels the
indices miss have MNDWI median -1.2, so no index threshold recovers them.
An independent check on 2026-10-30 reproduced every figure in this section
from docs/research/2026-10-29-polygon-calibration.csv, and the live re-run
of ramsar-15 on the 2026-10-12 pass gave 0.5162 (mndwi -0.1), 0.6145 (ndwi
-0.45) and 0.9705 (scl6), the same as the CSV. Leave-one-date-out agreement
is 0.9682 (ramsar-15), 0.9434 (ramsar-28) and 0.9788 (ramsar-56), and
holding out any one date leaves each polygon's winning setting unchanged.
Applied in docs/decisions/0005-per-polygon-water-settings.md: ramsar-15
uses SCL class 6 (scl6, agreement_min 0.94), and ramsar-28 and ramsar-56
use the settings proposed above.

### S9 historical tolerance (2026-10-30)

Compared the DEA Waterbodies v3 wet fraction with the ga_ls_wo_3 wet fraction
per Landsat pass over Thomsons Lake (uid qd635epws_v3, 193.2 ha) from 2022-12
onward. A pass is a calendar date on which Waterbodies v3 publishes a non-blank
pc_wet for the polygon. The Waterbodies series has 315 rows since 2022-12-01,
of which 129 are valid and 186 are blank; the blank rows are not compared.
Each valid date was matched to the ga_ls_wo_3 STAC items (two per date) that
intersect the polygon, read on the 30 m EPSG:32650 grid with a pixel-centre
polygon mask (2145 pixels). Passes compared: 129 (2022-12-17 to 2026-10-10).
Passes dropped for lacking a WO item: 0.

Wet fraction convention: wet pixels equal to 128 over all polygon pixels,
including pixels that are not clean, matching px_wet and pc_wet. Difference is
Waterbodies minus ga_ls_wo_3, signed. Absolute difference over the 129 passes:
median 0.024 pp, 90th percentile 0.101 pp (numpy linear), maximum 0.181 pp on
2026-01-11 (0.8905 against 0.892308, valid fraction 1.0). No pass differs by
more than 0.2 pp. The mean signed difference is -0.017 pp. The largest
differences are consistent with pixel-count effects: one polygon pixel is 0.047
pp, the 2145 pixel mask used here differs by 2 pixels from the 2147 pixel
polygon area on the 30 m EPSG:3577 grid (0.093 pp), and the Waterbodies value
is published to four decimals. The maximum is about four pixels, not a frame
seam or a coverage gap; 43 passes have valid fraction below 1 (minimum 0.903)
and the 2022-12-25 pass at 0.919 differs by 0.025 pp.

Chosen tolerance: 10 percentage points. Rule: the smallest whole number of
percentage points in 10..15 that is at least the 90th percentile of absolute
difference; the 90th percentile is below 10, so the floor of the band applies.

The near-zero differences are consistent with Waterbodies v3 being derived from
the same ga_ls_wo_3 data. The tolerance therefore bounds polygon rasterisation
and validity filtering differences between the two DEA reference paths
(Waterbodies and ga_ls_wo_3), not agreement between independent algorithms.
The 10 pp figure is the floor of the 10..15 band applied by rule, not a
measured disagreement. S9 compared only same-date Waterbodies against
ga_ls_wo_3. It did not measure Sentinel-2 versus Landsat wet fraction
disagreement or the effect of the 1 to 3 day offset between pipeline passes and
Waterbodies passes; a different wet definition and a time offset are expected
in the Water extent history check. Between the two DEA reference paths, a
difference beyond 10 pp would indicate a wrong polygon, a wrong pass match or a
different wet definition. The Milestone 2 history check still has to validate
10 pp for the pipeline against Waterbodies.

Per-pass rows are in docs/research/2026-10-30-waterbodies-tolerance.csv. The
script that produced it (scratch/spikes/s9_tolerance.py) is untracked in
scratch/spikes/.

## Live run findings

### SCL overview resampling (2026-10-29)

The first `wetland-change verify` (run 20261029T131944Z) failed
scl_share_vegetation and scl_share_not_vegetated on 5 of 8 scenes (diff 1.9
to 3.1 pp against the 1.0 pp tolerance) while water and cloud passed on all
8. Cause: the check read the SCL at the 1/16 overview, and the Earth Search
SCL COGs build their overviews with mode resampling (dataset tag
OVR_RESAMPLING_ALG=MODE, overviews 2, 4, 8, 16). Mode favours the locally
dominant class, so interspersed classes drift with every level while
contiguous water does not. Measured on S2C_T50HLJ_20261027T022351_L2A,
vegetation diff against s2:vegetation_percentage at factors 2, 4, 8, 16:
+0.135, +0.744, +1.288, +2.039 pp (not_vegetated -0.130, -0.666, -1.176,
-1.867; water within 0.044). On S2C_T50JML_20261027T022351_L2A: -0.515,
-1.690, -2.375, -3.034 pp (not_vegetated +0.522, +1.724, +2.432, +3.125).
The full-resolution read (5490 by 5490, 0.6 to 1.2 s) matches the item
properties to three decimals on both scenes; a plain strided subsample
full[::16] lands within 0.12 pp, so sampling noise is not the cause. Fix:
`scl_checks` reads the SCL at full resolution; the tolerance stays 1.0 pp;
the design matrix row was corrected. Rule: never compute class shares, or
any categorical statistic, from a mode-resampled overview.

### Planetary Computer copies of the 2026-10-29 pass (2026-10-29)

`pixels_vs_planetary_computer` failed on S2A_T50JLL, S2A_T50HLJ and
S2A_T50HLK of 2026-10-29 (measured 0.0, same transform, same baseline
05.13) once the scenes appeared on Planetary Computer at 09:03 UTC, and
passed bit for bit on the five 2026-10-27 scenes. The Planetary Computer B03
10 m COGs for the new pass hold deterministic values between 0 and 255 (256
distinct values; two reads identical; a distant window the same),
uncorrelated with Earth Search (-0.005 on 50HLJ, -0.040 on 50JLL; a linear
fit explains nothing), while the SCL asset of the same scene holds plausible
classes (4: 1154, 5: 3369, 6: 1831, 7: 356 in the ramsar window on 50HLJ,
against 1302, 3078, 1830, 500 on 2026-10-27). The files differ from the
healthy copies in size (B03 158 MB against 255 MB), nodata (0 against unset)
and an IMAGE_STRUCTURE tag OVERVIEW_RESAMPLING=cubic, so they came from a
different writer. Reading: a Planetary Computer ingestion fault, external to
this pipeline; no code changed. Rule: a reference oracle can be the broken
side. When a bit-identity check fails, compare value ranges and correlation
before suspecting the read, and never convert a bad reference into a skip.

### DEA NBART scale (2026-10-30)

The scale and offset of DEA Surface Reflectance NBART (ga_s2am_ard_3,
ga_s2bm_ard_3, ga_s2cm_ard_3) are 1e-4 and 0: reflectance = DN / 10000. The
source is the DEA Knowledge Hub product pages for DEA Surface Reflectance
NBART (Sentinel-2A, 2B and 2C MSI), for example
https://knowledge.dea.ga.gov.au/data/product/dea-surface-reflectance-nbart-sentinel-2c-msi/,
which state "Valid data range [1,10000]" and "For all 'nbart_' bands,
Surface Reflectance is scaled between 0 and 10,000".

No machine-readable source states the scale. Re-checked on 2026-10-30: STAC
`raster:bands` for nbart_red and nbart_nir_1 on item
155b809a-5595-41b4-a1c2-09bd487347c6 holds only nodata -999, data_type int16
and unit "1". The ODC product YAML
https://explorer.dea.ga.gov.au/products/ga_s2cm_ard_3.odc-product.yaml has
dtype int16, units '1' and nodata -999 for every measurement and no
scale_factor (a case-insensitive grep for "scale" finds nothing). The dataset
proc-info YAML has no scale or offset either. The band04 COG carries no scale
or offset tags; rasterio reports the GDAL defaults 1.0 and 0.0.

NDVI does not change under a pure scale, so only the zero offset matters. The
check refuses an item whose `raster:bands` states another scale or offset.

Grid and CRS: nbart_red and nbart_nir_1 are 10 m on EPSG:32750 with the
50HLK origin (300000, 6500020), identical to Earth Search. oa_fmask is 20 m
and is not used. The compared mask is the pipeline SCL clear mask minus DEA
-999.

Maturity: values seen are final up to 2026-10-17 and nrt from 2026-10-22. nrt
is DEA's provisional.

Live result: the newest 50HLK pass with a DEA match on 2026-10-30,
S2A_T50HLK_20261029T021516_L2A, against ga_s2am_ard_3 item
def48e1d-e43d-4314-a381-fb269120f4a6 (nrt): pipeline ndvi_median 0.4749,
DEA NBART median 0.4715, abs_diff about 0.003, n_compared 63600, passed True
(tolerance 0.05).

This resolves the design's open research item on the NBART scale factor.

### dea-tools index comparison (2026-10-30)

Result against hypothesis 6: held. All six comparisons passed at assert_allclose atol 1e-6, rtol 0 (6 of 6). NaN counts were 0 for both wetland_change.indices and dea-tools in every case, and dea-tools produced no inf values. The NaN-position clause of hypothesis 6 held only vacuously: the fixture window had 0 nodata pixels and no case had a zero denominator, so no NaN positions were ever compared. The two implementations also differ on x/0: dea-tools returns +-inf where wetland_change.indices returns NaN (stated in the script docstring). That difference is not covered by this comparison.

- synthetic NDWI: max absolute difference 2.965e-08, PASS
- synthetic MNDWI: max absolute difference 2.974e-08, PASS
- synthetic NDVI: max absolute difference 2.979e-08, PASS
- Thomsons fixture NDWI: max absolute difference 0.000e+00, PASS
- Thomsons fixture MNDWI: max absolute difference 0.000e+00, PASS
- Thomsons fixture NDVI: max absolute difference 0.000e+00, PASS

The synthetic differences come from our float32 output against dea-tools float64 (seed 42, uniform 0 to 0.6, 32x32 arrays). On the fixture window both sides were float32 and matched exactly.

Method: dea-tools 0.4.10 `calculate_indices` with collection 'ga_s2_3' and normalise=False, drop=True. Band mapping: nbart_green=B03, nbart_red=B04, nbart_nir_1=B08, nbart_swir_2=B11 (the MNDWI SWIR band). Cases were synthetic arrays (seed 42, float64 uniform 0 to 0.6, 32x32) and the Thomsons fixture window (64x64, B11 nearest-upsampled from 20 m).

Wheel: `dea_tools-0.4.10-py3-none-any.whl`, sha256 `8f42620975a8b904446718e561c25d1c39f38c1511359e7730cf3d786890c4ba` (verified by the script before use). Command: `uv run --with xarray python scripts/compare_dea_tools_indices.py`.

Only dea_tools/bandindices.py was loaded from the wheel; it imports only numpy and warnings. xarray was a `--with` overlay. No dependency was added, and pyproject.toml and uv.lock are unchanged.

Decision context: dea-tools 0.4.10 resolves on Python 3.12, but its transitive geomad 1.0.0 (via odc-algo) has no macOS wheel and the sdist build fails with 'omp.h file not found'. The standing check therefore stays spyndex 0.12.0 in tests/test_indices.py (human decision 2026-10-30).
