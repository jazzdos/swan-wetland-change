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

## Pre-registered hypotheses (st-b983, 2026-11-02)

Recorded before the Collection 1 backfill runs. The verdict rules are fixed here and implemented in `docs/research/2026-11-02-backfill-analysis.py`. Thresholds stay as configured: |z| above 3, valid fraction above 0.8, at least 5 baseline samples, and the per-polygon water settings in `config/pipeline.toml` (ramsar-56 MNDWI 0.05; ramsar-52 and the DEA polygons the global MNDWI -0.1). Nothing is tuned after the run.

Definitions. H1 to H3 use metric `water_ha_index`, UTC acquisition dates and one daily score per polygon, computed as `wetland-change score` computes it, with a baseline of the same polygon and month on strictly earlier dates (ADR 0004). A date is scored when `reason` is null and `z` is not null. A low flag is a row with `flagged` true and `z` below zero. Forrestdale is `ramsar-56` (DEA `qd63n1ww5_v3`). Thomsons is `ramsar-52` (DEA `qd635epws_v3`). The code has no dry-down flag, so H3 reads a dry-down flag as a low flag.

- H1, Forrestdale low water, 2023-12-01 to 2024-01-31. Supported if there is at least one low flag. Not supported if at least one date is scored and there is no low flag. Untestable if no date is scored.
- H2, Forrestdale no anomaly, 2023-02-01 to 2023-04-30. Supported if at least one date is scored and no `water_ha_index` row is flagged with either sign. Not supported if any such row is flagged. Untestable if no date is scored. NDVI flags are reported separately and do not affect the verdict. The 2022 half is untestable because Earth Search Collection 1 has no items covering Forrestdale for February to April 2022 under the pipeline's 20 percent cloud filter. An unfiltered search finds two items intersecting ramsar-56, both on 2022-03-22 and both excluded by that filter: S2A_T50HLK_20220322T022405_L2A at 39.8 percent cloud and S2A_T50HMK_20220322T022405_L2A at 68.6 percent cloud.
- H3, winter water at or above baseline, 2025-06-01 to 2025-08-31, ramsar-56 and ramsar-52. A polygon meets the rule if the median of `value - baseline_median` over its scored dates is at least 0 and it has no low flag. Supported if both polygons meet it. Not supported if either polygon has scored dates and fails. Untestable if a polygon has no scored date and the other does not fail. A per-date reading is rejected because about half of any series sits below its median.
- H4, agreement with DEA Waterbodies, 2022-12-01 to the run end date, per lake in `LAKES` (Thomsons, Forrestdale, Lake Clifton, Lake Preston), from check `water_spearman_vs_dea_waterbodies` (passes within 3 days, at least 10 pairs). Supported if at least one lake is scored and every scored lake has rho at least 0.9. Not supported if any scored lake has rho below 0.9. Untestable if no lake is scored.

H2 may come out untestable. The store starts in December 2022, so a February to April 2023 baseline holds only earlier dates of that same month, and 4 to 5 dates a month may not reach 5 samples. The report gives the count per `reason`. It also gives a descriptive z for those dates against same-month observations from all years other than 2023; that figure is not a verdict and does not follow ADR 0004.

## Pre-registered hypotheses (st-9aff, 2026-11-05)

Recorded before any wet-area measurement. The design's Water extent, live row (line 226) asks for wet area within 5 pp, and `water_vs_dea_s2_wo` does not score it. Over mutually clear pixels, the absolute wet-area gap is at most 1 minus agreement, so the clause was implied at the design's 0.95 floor and can bind only below it. In `docs/research/2026-10-29-polygon-calibration.csv`, 17 of 22 ramsar-28 rows at its configured setting sit between its 0.92 floor and 0.95. The same rows for ramsar-15 and ramsar-56 show none. No recorded data holds wet counts.

Definitions. Sample: every polygon in the Ramsar AOI at its configured setting, on the 6 newest of the 12 dates in that CSV, and ramsar-28 on all 12. A row is one polygon on one scene with at least 100 mutually clear pixels. Wet share is the share of mutually clear pixels that are wet, for the pipeline and for DEA WO, using the clear rule in `wo_agreement`. Gap is pipeline share minus WO share, in percentage points. A row passes agreement when agreement is at or above the polygon's agreement_min.

- H1. Of the rows that pass agreement, at least 90 percent have an absolute gap of 5 pp or less.
- H2. Of the ramsar-28 rows that pass agreement, at least 90 percent have an absolute gap of 5 pp or less.

Decision rule. Both hold: implement the 5 pp clause as part of `Check.passed`. Either fails: do not add it as a hard gate at 5 pp, and park the story with the measured rates, because a clause that fails often would turn verify red the way st-b602's Spearman check does. The result also records, per scene, the share with at least one failing polygon, with and without the clause.

## Pre-registered hypotheses (st-7047, 2026-11-06)

Recorded before any measurement for this story. Part A fixes an exit rule for wet-area failures and Part B fixes the hypotheses for the ramsar-12 wet-area gap. Disclosure: the per-date counts were readable in the committed `docs/research/2026-11-05-wet-area-gap.csv` when the Part A rule was written, and the st-9aff section 'Wet area clause (2026-11-05)' already gives 2 failing dates for agreement alone and 6 for agreement or clause, which are the counts for K2 and K1 below. The Part A rule is a policy choice recorded before the script runs, not a blind test. It is implemented in a research script and recorded in ADR 0008. No raster is read for Part A.

### Part A, exit rule

Context. ADR 0006 put the clause (absolute wet-area gap of 5.0 pp or less) into `Check.passed` for `water_vs_dea_s2_wo` and left the exit logic of `verify` unchanged, so `verify` exits 3 if any check fails. On the 6 dates with every polygon measured in `docs/research/2026-11-05-wet-area-gap.csv`, dates with a failing row go from 2 (agreement alone) to 6 (agreement or clause), per the st-9aff section 'Wet area clause (2026-11-05)'.

Definitions. Sample: the rows of `docs/research/2026-11-05-wet-area-gap.csv` with n_mutually_clear at or above 100 (253 rows, the same filter as verify's min_clear_pixels of 100). No new raster reads. Measured dates: the 6 newest pass_date values in that file (2026-09-12 to 2026-10-29), the dates with every polygon measured. The other 6 dates hold ramsar-28 only and are listed but not counted. A row fails agreement when passes_agreement is False. A row fails the clause when abs(gap_pp) is above 5.0. A date fails under a candidate rule when `verify` would exit 3 for a run holding every scene of that date.

Candidates.

- K1. Any single failing check fails the run (ADR 0006 as it stands). A date fails if any row fails agreement or the clause.
- K2. Agreement alone fails the run. A row that passes agreement and fails only the clause is advisory: shown as a warning with its gap, exit code unchanged. A date fails if any row fails agreement.
- K3. As K2 for agreement. A wet-area failure fails the run only when some polygon fails the clause on every one of its scored scene rows in that date (persistent for the polygon). A date fails if any row fails agreement or some polygon meets that condition.
- K4. As K2 for agreement. A wet-area failure fails the run only when the wet-share gap pooled over every row of the date exceeds 5.0 pp in absolute value. The pooled gap is 100 * (sum of pipeline wet counts - sum of WO wet counts) / sum of n_mutually_clear, with each count recovered as round(share * n). A date fails if any row fails agreement or the pooled gap breaks the limit.

Decision rule. Let B be the number of measured dates that fail under K2 (agreement alone). A candidate is admissible if the number of measured dates it fails exceeds B by at most 1. Choose the admissible candidate that fails the most measured dates. Ties go to the candidate whose failing condition includes the other's for every possible run: K3 and K4 each include K2 (they fail every run K2 fails, and possibly more), and K1 includes K2, K3 and K4. If neither of two tied candidates includes the other, the one listed first (K1, K2, K3, K4) wins. On this data K2 and K4 are expected to tie, so the expected choice is K4, but the script decides. Reason: when two rules fail the same measured dates, keep the one under which the wet area clause can still fail a run, so a run-wide wet bias against WO is not reduced to warnings.

The result records, for the chosen rule and for each candidate, the share of the 6 measured dates that fail, plus the share of rows that fail the clause alone. Whichever candidate wins, the markdown report and the CLI line must show the wet-area gap for a check that fails on wet area alone. That is an acceptance criterion, not a hypothesis.

### Part B, ramsar-12 gap

Context. ramsar-12 (Peel-Yalgorup System, about 100.7 ha, global setting MNDWI above -0.1, agreement_min 0.91) is 5 of the 9 rows that fail only the clause. The pipeline is wetter than WO on all 12 of its rows (6 dates, tiles 50HLJ and 50HLK), by 3.12 to 6.82 pp. The gap rises from 3.1-3.3 pp (2026-09-17) to 5.9-6.8 pp (2026-10-27, 2026-10-29) while pipeline wet share is 0.127 to 0.168 and WO wet share is 0.060 to 0.132.

Sample. The 12 ramsar-12 rows of the CSV, re-read from Earth Search and DEA with the same window, clear mask, inside mask and WO clear rule as `wo_check`. Reproduction check first: the re-read n_mutually_clear must equal the CSV and gap_pp must be within 0.01 pp on all 12 rows. If not, record that and stop. Per row, a is the count of mutually clear pixels the pipeline calls wet and WO calls clear dry, b is the reverse, n is the mutually clear count, and gap = 100 * (a - b) / n.

- G1, threshold. Supported if some MNDWI threshold on the grid -0.10, -0.05, 0.00, 0.05, 0.10, 0.15, 0.20 gives an absolute gap of 5 pp or less on all 12 rows. Not supported otherwise. The result also reports the threshold with the lowest mean absolute gap and the pooled agreement at each grid value.
- G2, SCL. Supported if scl6 (clear and SCL class 6) gives an absolute gap of 5 pp or less on all 12 rows.
- G3, edge. The edge ring is the pixels inside the polygon mask within 2 pixels (20 m) of a pixel outside the mask (two 4-neighbour erosions of the inside mask, numpy only). Supported if the ring's share of the a-pixels summed over the 12 rows is at least twice the ring's share of the mutually clear pixels summed over the 12 rows.
- G4, class. Supported if at least 50 percent of the a-pixels summed over the 12 rows are SCL class 4 or 5 (vegetation or not vegetated). The shares of every SCL class among the a-pixels are reported.
- G5, history. Over the stored observation rows for ramsar-12 in the read-only backfill (`/Users/jarrodbaker/Documents/swan-wetland-change-data/outputs/observations`), supported if `water_ha_index` exceeds `water_ha_scl` on at least 75 percent of the rows where either is above 0. This tests whether the over-call is specific to the 6 sampled dates.

Reading rule. The cause recorded is every supported hypothesis, stated with its numbers. If none is supported, LEARNINGS.md records that no cause was found and lists what was checked (G1 to G5 with their numbers).

## Pre-registered hypotheses (st-5f74, 2026-11-06)

Recorded before the availability script is written or run. Context. The observation column `dea_wo_agreement` is null on every row, although AGENTS.md (locked decision), ADR 0002 and design line 179 say it stores the pixel agreement with DEA Sentinel-2 Water Observations (`ga_s2_wo_provisional_3`). ADR 0002 says verify fills it while the provisional product retains the pass, and nothing does. DEA keeps the product about three months, so a later backfill cannot fill it. The daily run (`.github/workflows/pipeline.yml`, cron `17 10 * * *`, 10:17 UTC) already calls DEA in verify. The question is whether DEA already holds the matching WO item when the daily run first processes a scene-tile.

Disclosure. Before this section was written the planner ran an exploratory, unrecorded pass over 2026-08-08 to 2026-11-05 (cloud cover at most 20, six MGRS tiles, the bbox below). It found a WO item before the first cron for 49 of 49 scene-tiles, with a smallest margin of 0.4 hours. DEA WO `created` fell at 07:32 to 09:42 UTC on the acquisition day and Earth Search `created` at 06:34 to 08:43 UTC. That pass had a pagination bug. This section is therefore a policy rule recorded before the recorded script runs, not a blind test.

Sample. The unit is one scene-tile, that is one Earth Search item. Items are `sentinel-2-c1-l2a` from Earth Search (`https://earth-search.aws.element84.com/v1/search`, POST) with bbox [115.3, -33.2, 116.0, -31.6], an approximation of the AOI union bbox (the AOI GeoJSON in `data/external` is untracked and absent here). Items are kept when `properties.datetime` (UTC date) is from 2026-08-15 to 2026-11-03 inclusive, `eo:cloud_cover` is at most 20.0 (`stac.cloud_cover_max` in `config/pipeline.toml`) and `properties.created` is not null. The window starts on 2026-08-15 so DEA's three-month retention has not removed the oldest WO items, and ends on 2026-11-03 so every item had at least one full day for its WO item to appear. The tile is `properties["grid:code"]` with the `MGRS-` prefix removed (for example 50HLK).

Match. A DEA WO item from `https://explorer.dea.ga.gov.au/stac/search` (collection `ga_s2_wo_provisional_3`, same bbox, datetime window 2026-08-15T00:00:00Z/2026-11-04T23:59:59Z) with the same UTC acquisition date and `properties["odc:region_code"]` equal to the tile. This is the same rule as `find_wo_href` in `src/wetland_change/verify/wo.py`.

Times. T_es is Earth Search `properties.created`. T_proc is the first instant at or after T_es that is 10:17:00 UTC, the scheduled run; GitHub scheduler delay and run duration are ignored. A_wo is the DEA WO item's `properties.created`, the STAC index time, chosen because the explorer exposes no other availability timestamp. The date-time stamp in the asset path (for example 20260810T071416) is recorded as a secondary field `wo_path_stamp`. If DEA re-creates an item later, A_wo is later and the share is understated, which errs towards amend.

Metrics. S is the number of scene-tiles with a matched WO item and A_wo at or before T_proc, over all scene-tiles in the sample. Also recorded: the Wilson 95 percent interval for S; the share with a WO item at measurement time whenever it arrived; the scene-tiles with no WO item at all; the lag A_wo minus T_proc in hours (negative means WO was ready before the run) as min, p25, median, p75, p90 and max by nearest rank; S2, the same share with T_proc plus 2 hours, as a sensitivity for run duration; and counts by acquisition month.

- H1 (prediction). S is at least 0.90. Whether it holds is recorded.

Decision rule. If S is at least 0.50, populate `dea_wo_agreement` at processing time in the daily run, which honours the locked decision. If S is below 0.50, amend the locked decision and leave the column null, because filling it later would need rewriting per-scene observation files after the fact (one file per scene, overwritten only by rerun) and the verify step does not own them. In addition, populate is chosen only if a DEA failure provably cannot fail the daily run (DEA errors are logged and write None, proven by a test). If that cannot be achieved, amend.

When WO arrives later than first processing, that row stays null and is never filled afterwards. The column means the agreement at first processing, and the verification report remains the record for later passes.

## Pre-registered hypotheses (st-2a78, 2026-11-06)

Recorded before any measurement for this story and before the confirmatory script is written or run. Context. Story st-2a78 decides whether ramsar-12 (Peel-Yalgorup System, global water setting MNDWI above -0.1, agreement_min 0.91) gets a per-polygon override in `config/pipeline.toml`, using the ADR 0005 mechanism. The evidence is in the st-7047 section 'ramsar-12 wet area gap (2026-11-06)' and in `docs/research/2026-11-06-ramsar-12-gap.py`, `.csv` and `.txt`. On 12 scene-tile rows (6 dates: 2026-09-12, 2026-09-17, 2026-10-02, 2026-10-12, 2026-10-27, 2026-10-29; tiles 50HLJ and 50HLK) the global setting is wetter than DEA Water Observations (WO) by 3.12 to 6.82 pp. Any MNDWI threshold from -0.05 to +0.15 keeps the absolute gap at 5 pp or less on all 12 rows. The mean absolute gap by threshold is 0.512 pp at +0.05 (the lowest), 1.221 at 0.00, 1.821 at +0.10, 2.977 at -0.05 and 3.065 at +0.15. Those 12 rows have already been seen, so they only nominate candidates. The decision is made on a confirmatory sample of dates that are not among the 12.

Disclosure.

- (a) The 12 ramsar-12 rows of `docs/research/2026-11-06-ramsar-12-gap.csv` have been seen. They are not used to decide. They only nominate the candidates and supply the seen-row counts for the agreement_min pooling in R6.
- (b) The planner read the Earth Search item list in `docs/research/2026-11-06-wo-availability.csv`. It shows ramsar-12-tile scenes with cloud cover at most 20 on 2026-08-23 (50HLK only), 2026-08-28, 2026-08-30 and 2026-09-07 (both tiles), each with a WO item, so about 7 scene-tiles on 4 dates are expected. No gap value for any of them has been seen.
- (c) These dates fall in August and September, the wetter season, so the dry end of the season is covered only by the seen rows.
- (d) DEA S2 WO is unvalidated. The rule measures consistency with WO, as in ADR 0005, not accuracy.
- (e) Choosing among 3 candidates on about 7 rows is a small-sample choice.

Candidates C. MNDWI above t for t in {0.00, +0.05, +0.10}, the three grid values around the seen-data optimum. The values -0.05 and +0.15 are excluded because their seen mean absolute gaps (2.977 and 3.065 pp) are about six times the optimum. Baseline: the global -0.10. scl6 is reported for context only (G2 was not supported).

Confirmatory sample. Earth Search `sentinel-2-c1-l2a` items returned by the pipeline's own `discover` (`src/wetland_change/catalogue/search.py`) with acquisition date 2026-08-15 to 2026-11-05 inclusive, cloud cover at most the config `cloud_cover_max` (20.0), and a planned window for ramsar-12. The start date keeps the window inside DEA's roughly three-month WO retention. The window is fixed and is not widened after seeing results. Items acquired on any of the 6 seen dates are excluded. An item is kept only with a DEA WO item per `find_wo_href` in `src/wetland_change/verify/wo.py` a WO grid transform equal to the scene's (otherwise the scene-tile is dropped as 'grid differs', as in `wo_check`) and at least 100 mutually clear pixels (verify's min_clear_pixels). Before any read, each scene passes the pipeline's guards: grid and item EPSG equal to the operation EPSG, and every band's scale and offset checked against the ESA product XML; a guard failure raises and is not dropped. The window, clear mask, inside mask and WO clear rule are the same as in `wo_check` and in `docs/research/2026-11-06-ramsar-12-gap.py`. Per row: a is the count of mutually clear pixels the pipeline calls wet and WO calls dry, b is the reverse, n is the mutually clear count, gap_pp = 100 * (a - b) / n and agreement = 1 - (a + b) / n. Scene-tiles dropped (no WO item, grid differs, fewer than 100 clear pixels) are listed, not substituted. The script runs once.

Selection. T is the candidate in C with the lowest mean absolute gap_pp over the confirmatory rows. Ties go to the candidate closest to +0.05, then the lower one.

Decision rule. Adopt a per-polygon override for ramsar-12 at T only if all of R1 to R6 hold. Otherwise keep the global setting and record the failed ids.

- R1, sample. At least 6 confirmatory rows on at least 3 distinct acquisition dates. Failing R1 is recorded as 'inconclusive' and keeps the global setting.
- R2, clause. The absolute gap_pp is 5.0 or less on every confirmatory row at T.
- R3, gain. Pooled agreement at T minus pooled agreement at -0.10, over the confirmatory rows, is at least 0.005. Pooled agreement is 1 - sum(a + b) / sum(n).
- R4, consistency. Agreement at T is strictly greater than agreement at -0.10 on at least two thirds of the confirmatory rows.
- R5, no over-correction. The absolute value of the mean signed gap_pp at T over the confirmatory rows is 2.0 or less.
- R6, floor. agreement_min is the floor to 0.01 of (pooled agreement at T over all rows, the 12 seen plus the confirmatory rows, minus 0.02), the ADR 0005 convention, computed exactly with rational arithmetic. The override is adopted only if agreement_min is at least 0.91.

The override form is `[water.overrides.ramsar-12]` with method = "mndwi", threshold = T and agreement_min as computed.

Reported but not decision inputs: gap and agreement at -0.10, 0.00, +0.05, +0.10 and scl6 per row; the number of all rows below the computed agreement_min; and whether T equals +0.05.

Status. The outcome is recorded in ADR 0010 as decided under Jarrod's delegation; Jarrod approved it on 2026-11-06. Changing ramsar-12's setting is an ADR 0005 calibration decision.

## Pre-registered hypotheses (st-da75, 2026-11-14)

Recorded before any measurement for this story and before the research script `docs/research/2026-11-12-ndvi-nbart-rows.py` is written or run.

Context. GitHub issue #2 (CI run 43072355326), second cause.

Since st-a32a (ADR 0012) the per-polygon check `ndvi_vs_dea_nbart` in `src/wetland_change/verify/ndvi.py` blocks on ramsar rows only. The check requires the pipeline NDVI median to be within 0.05 of the DEA NBART NDVI median. It still fails 4 ramsar rows on each of the two passes measured, so `verify` exits 3 on every run with scenes.

The 0.05 tolerance and the 0.95 correlation limit come from the NDVI row of the design matrix (`docs/plans/2026-10-29-swan-wetland-change-design.md`). The 0.05 tolerance was checked live on one area only, the live test's Thomsons Lake box on the 2026-10-29 pass (Live run findings, 'DEA NBART scale (2026-10-30)'). The box is `THOMSONS_32750` in `tests/test_live_verify.py`, 2,400 m by 2,650 m, and is not a ramsar polygon. That check is one row and does not test the 0.95 correlation limit, which needs at least 5 rows. No exit rule has been measured for NDVI the way ADR 0008 measured one for water.

Disclosure.

- (a) The eight seen failing rows come from `docs/research/2026-11-12-issue-2-repro-20261029.json` and `docs/research/2026-11-12-issue-2-repro-20261111.json`. Both were written by `wetland-change verify` at commit ad1fe76, and their sha256 is in ADR 0012. Each row gives the pipeline median against the DEA median, the compared pixels and the DEA item. DEA nodata pixels were 0 on all eight.
  - 2026-10-29: 31 ramsar rows scored, Pearson 0.9983, DEA maturity final.
    - ramsar-15 on 50HLJ: 0.1150 against 0.2141 (6,742 px).
    - ramsar-20 on 50HLJ: -0.6697 against -0.5776 (1,942 px).
    - ramsar-21 on 50HLJ: -0.8081 against -0.6575 (5,976 px).
    - These three are against ga_s2am_ard_3 item 15ea7fec-e565-400b-a2c7-051485dab1cd.
    - ramsar-27 on 50HLK: -0.5448 against -0.4314 (641,110 px), against db9546b0-7a1c-40f0-be5d-bad97788733e.
  - 2026-11-11: 42 ramsar rows scored, Pearson 0.9921, DEA maturity nrt.
    - ramsar-13 on 50HLK: 0.4217 against 0.3475 (228 px), against ga_s2bm_ard_3 item e2b6b9df-8064-4729-962f-6ed5193b22ad.
    - ramsar-13 on 50HLJ: 0.4490 against 0.3483 (228 px), against 0fea38ac-eddc-4852-ba7b-76875fc9f218.
    - ramsar-20 on 50HLJ: -0.2259 against -0.1561 (1,732 px).
    - ramsar-21 on 50HLJ: -0.0521 against 0.0066 (3,756 px).
    - ramsar-20 and ramsar-21 are against 0fea38ac-eddc-4852-ba7b-76875fc9f218.
  - The pipeline is lower than DEA on 6 of the 8 rows and higher on the two ramsar-13 rows. For ramsar-13, the two tiles' stored medians differ by 0.0273 and the two DEA medians differ by 0.0008.
- (b) The other 65 scored ramsar rows of those two reports have been seen, and so have the waterbody rows. On the 2026-10-29 waterbody rows the largest polygons fail most: 21 of 31 rows at 10,000 px and over fail, with a median absolute difference of 0.141. Over all 310 failing waterbody rows of that pass, the median pipeline NDVI is +0.021 against +0.134 for DEA. Over the 21 failing rows at 10,000 px and over, it is -0.352 against -0.105. The two passes are the nomination sample and are not used to decide.
- (c) The Thomsons Lake value on the 2026-10-29 50HLK pass has been seen: 0.4749 against 0.4715 on 63,600 px, against nrt item def48e1d-e43d-4314-a381-fb269120f4a6, which DEA has since replaced with a final item. It was read over the live test's box, not over a ramsar polygon. The box contains ramsar-50, ramsar-51 and 99.9% of ramsar-52 by area. Their rows on that scene-tile in the 2026-10-29 report, ramsar-52 at 0.4600 against 0.4515 on 49,147 px, are among the rows seen under (b). Both are from a nomination pass.
- (d) The ramsar-12 WO wet-area gap was measured on 2026-09-12, 2026-09-17, 2026-10-02, 2026-10-12 and 2026-10-27 (st-7047, st-2a78). Pipeline `ndvi_median` for ramsar-52 and ramsar-56 on all 8 confirmatory passes (15 rows) is readable in `docs/research/2026-11-03-backfill-scores.csv` (st-b983), and the pipeline's output store holds `ndvi_stored` for the rows of every confirmatory scene-tile the backfill has processed. No DEA NBART value, abs_diff or band value (red or nir) of any confirmatory pass has been seen.
- (e) On 2026-11-14 the planner ran the pipeline's `discover` over the 27 ramsar polygons to fix the confirmatory item ids below. This was metadata only, with no pixel read. The planner also read DEA STAC item metadata, for maturity only.
  - DEA held final items for every confirmatory scene-tile except 2026-10-27 on 50HLK, 50JLL and 50JML, which were nrt.
  - DEA still served the 2026-11-11 nrt items recorded in the report.
  - The confirmatory sample is therefore final maturity except those three scene-tiles, while daily runs score against nrt.
- (f) The working explanation tested in H1 (NDVI is ill-conditioned at low reflectance) was formed after the eight rows were seen.
- (g) DEA NBART is another processing of the same Sentinel-2 acquisition and is not ground truth. The result measures consistency, as ADR 0005 says of WO.

Definitions, shared by every candidate and by the script.

- Row: one ramsar polygon on one Earth Search `sentinel-2-c1-l2a` scene-tile for which `plan_window` (`src/wetland_change/windows.py`) returns a window. Pass: all scene-tiles with the same UTC acquisition date.
- Reads are those of `_verify_scene` (`src/wetland_change/verify/run.py`) and `ndvi_scene_check`, in this order:
  - The scene grid is taken from the green asset.
  - The raising guards of `process_scene` (`src/wetland_change/pipeline.py`) run before any pixel read: grid and item EPSG must equal the operation EPSG 32750, and `check_band_scaling` checks every band's scale and offset against the ESA product XML. `_verify_scene` records the scaling check without raising, so the guards are taken from `process_scene`.
  - `read_stack` reads the bands; reflectance is DN times scale plus offset from the item's `raster:bands`.
  - `rasterise` gives the inside mask.
  - The DEA item is the one `find_nbart_item` selects (final before interim before nrt), checked by `parse_nbart_item`.
  - DEA `nbart_red` and `nbart_nir_1` are read at the scene's 10 m window, after the DEA CRS and grid transform are found equal to the scene's.
  - DEA reflectance comes from `nbart_reflectance`.
- clear is `clear_mask(scl, green, red, nir, swir16)` combined with inside. P, the compared pixels, is the clear pixels where both DEA bands are not -999 and the DEA NDVI is finite. n_compared is the size of P, as in `dea_ndvi_median`.
- ndvi_stored is the median that `summarise` (`src/wetland_change/stats.py`) stores: pipeline NDVI over clear pixels with a finite value. ndvi_dea is the DEA NDVI median over P. abs_diff = |ndvi_stored - ndvi_dea|, the value `ndvi_median_check` tests. ndvi_pipeline_same is the pipeline NDVI median over P.
- Over P:
  - red_pipeline, nir_pipeline, red_dea and nir_dea are the medians of each band's reflectance.
  - d_red = red_pipeline - red_dea, and d_nir = nir_pipeline - nir_dea.
  - band_max = max(|d_red|, |d_nir|).
  - s_pipeline and s_dea are the medians of per-pixel red + nir for each source.
- A row is scored as in `ndvi_median_check` with min_pixels 100 (`verify.min_clear_pixels`). It is skipped when ndvi_stored is not finite, when n_compared is 0 or when n_compared is below 100. A DEA CRS or grid difference fails the row under every candidate, as in `ndvi_scene_check`. A read error drops the row with its reason.
- Reflectance and NDVI are unitless. The source CRS and the operation CRS are EPSG:32750 for both sources.

Conditioning. For a per-band reflectance difference e, NDVI moves by at most 2e / (red + nir) to first order. For a limit g, S*(g) = 40 g is the value of red + nir at which a band difference of g moves NDVI by at most 0.05. W(g) is the set of scored rows with s_dea at or above S*(g), the well-conditioned rows. I(g) is the other scored rows.

Candidates.

- K0, status quo. Every scored row blocks on abs_diff at most 0.05. The correlation check is unchanged: Pearson over the scored ramsar rows of the run, at least 5 rows, passing when r is above 0.95.
- K1(g), conditioning split.
  - A row in W(g) blocks on abs_diff at most 0.05, unchanged.
  - A row in I(g) leaves the 0.05 comparison. It blocks instead on |d_red| at most g and |d_nir| at most g, against the same DEA NBART item.
  - The correlation check is unchanged and still covers every scored ramsar row.
  - Every row K0 scores stays scored, and 0.05 and 0.95 keep their values.
- Not candidates:
  - Widening 0.05, or a tolerance scaled by red + nir, since both widen 0.05.
  - A minimum pixel count above 100, or one row per polygon and pass across tiles, since both leave ramsar rows unscored.
  - Band limits on every row, since that drops the design's NDVI comparison on well-conditioned rows.

Parameter rule, nomination sample only.

The nomination sample is every ramsar row of the 8 seen scene-tiles:
- 2026-10-29: S2A_T50HLJ_20261029T021516_L2A, S2A_T50HLK_20261029T021516_L2A, S2A_T50JLL_20261029T021516_L2A.
- 2026-11-11: S2B_T50HLJ_20261111T022009_L2A, S2B_T50HLK_20261111T022009_L2A, S2B_T50HMK_20261111T022009_L2A, S2B_T50JLL_20261111T022009_L2A, S2B_T50JML_20261111T022009_L2A.

These rows are re-read and scored against the DEA item `find_nbart_item` selects on the day the script runs, so the 2026-11-11 rows are re-scored against whatever maturity DEA then holds. The nomination is run once. It is rerun only after a network failure before its files are written, or after a fix to the script's reading code, with at most two further attempts. A fix never changes a decision function, a constant or a sample. Every attempt and its date are recorded in the Spike results entry, and the files committed are those of the last attempt.

g is taken from 0.002, 0.003, ..., 0.010, so S* runs from 0.08 to 0.40. A value of g is admissible when, over the scored nomination rows:
- (N1) at least 0.95 of W(g) rows have abs_diff at most 0.05;
- (N2) I(g) is not empty and at least 0.95 of its rows have band_max at most g;
- (N3) W(g) holds at least half of the scored rows.

The nominated g is the smallest admissible value. If none is admissible, K1 is not nominated and the outcome is K0. The nomination is written to `docs/research/2026-11-12-ndvi-nbart-nomination.csv` and `docs/research/2026-11-12-ndvi-nbart-nomination.txt` and committed before the confirmatory sample is read. The confirmatory phase takes g only from these two committed files. Before any network call it exits non-zero when either file is absent, is not committed at HEAD, differs from the committed version or records a reproduction gate failure. The Spike results entry records the nomination commit. When the committed nomination passed the reproduction gate and names no g, the confirmatory phase still reads the sample once and reports the K0 rates and H1 to H4. A0 to A5 are not computed and the outcome is K0.

Reproduction gate. Before the nomination is computed, the script re-reads the eight seen rows against the DEA item recorded in the report, fetched by id from the DEA STAC collection.
- Each row must give ndvi_stored and ndvi_dea within 1e-6 of the report, and the same n_compared.
- A recorded item that DEA no longer serves is allowed only when its recorded maturity is not final. That row is then compared on ndvi_stored alone.
- If any of the eight fails, the script records the reason in the nomination text, exits non-zero and does not read the confirmatory sample. A network error while reading the eight is not a gate failure: the script exits before writing its files and the parameter rule's network rerun applies. A failure caused by the script's reading code may be fixed and the nomination rerun as the parameter rule allows. st-da75 is parked with the gate's message when the cause is outside the script or when the last allowed attempt still fails the gate.
- The other scored ramsar rows of the two reports are compared the same way. Their match count is reported, not gated.

Confirmatory sample, fixed: 32 scene-tiles on 8 passes. These are the ids that the pipeline's own `discover` (`src/wetland_change/catalogue/search.py`) returned for the 27 ramsar polygons, with cloud cover below `cloud_cover_max` 20.0 as `discover` applies it.

- 2026-09-12: S2B_T50HLJ_20260912T022111_L2A, S2B_T50HLK_20260912T022111_L2A
- 2026-09-17: S2C_T50HLJ_20260917T022244_L2A, S2C_T50HLK_20260917T022244_L2A, S2C_T50HMK_20260917T022244_L2A, S2C_T50JLL_20260917T022244_L2A, S2C_T50JML_20260917T022244_L2A
- 2026-10-02: S2B_T50HLJ_20261002T021907_L2A, S2B_T50HLK_20261002T021907_L2A, S2B_T50HMK_20261002T021907_L2A, S2B_T50JLL_20261002T021907_L2A, S2B_T50JML_20261002T021907_L2A
- 2026-10-12: S2B_T50HLJ_20261012T021555_L2A, S2B_T50HLK_20261012T021555_L2A, S2B_T50HMK_20261012T021555_L2A, S2B_T50JLL_20261012T021555_L2A, S2B_T50JML_20261012T021555_L2A
- 2026-10-27: S2C_T50HLJ_20261027T022351_L2A, S2C_T50HLK_20261027T022351_L2A, S2C_T50HMK_20261027T022351_L2A, S2C_T50JLL_20261027T022351_L2A, S2C_T50JML_20261027T022351_L2A
- 2026-01-30, the newest January 2026 pass: S2C_T50HLJ_20260130T022322_L2A, S2C_T50HLK_20260130T022322_L2A, S2C_T50HMK_20260130T022322_L2A, S2C_T50JLL_20260130T022322_L2A, S2C_T50JML_20260130T022322_L2A
- 2026-04-30, the newest April 2026 pass: S2C_T50HMK_20260430T021807_L2A
- 2026-07-29, the newest July 2026 pass: S2C_T50HLK_20260729T022253_L2A, S2C_T50HMK_20260729T022253_L2A, S2C_T50JLL_20260729T022253_L2A, S2C_T50JML_20260729T022253_L2A

How the sample is read:
- Each scene-tile is read once against the DEA item `find_nbart_item` selects on the run day, and its maturity is recorded.
- These are listed with their reasons: a scene-tile that `discover` no longer returns, a scene-tile DEA holds no item for, and every row with a read error or skipped by the scored-row rule. Nothing is substituted.
- An item that `discover` returns on these dates but that is not listed above is reported and not read.
- A guard failure raises and stops the run, as in st-2a78.
- The script runs once on this sample. If a network failure stops it before it writes its results, it is rerun once and both attempts are recorded.
- If the rerun also stops before results are written, or the run stops for any other reason before results are written (a guard failure or an error in the script), no decision is computed. The outcome is recorded as 'inconclusive', K0 stays and st-da75 is parked with the reason.

Decision rule, on the scored confirmatory rows at the nominated g. Adopt K1(g) only if A0 to A5 all hold. Otherwise K0 stays and st-da75 is parked with the measured rates.

- A0, sample: at least 100 scored rows on at least 6 passes. Failing A0 is recorded as 'inconclusive' and keeps K0.
- A1, well-conditioned rows: at least 0.95 of W(g) rows have abs_diff at most 0.05.
- A2, explained failures: at least 4 rows fail K0, and at least 0.75 of them are in I(g) with band_max at most g. With fewer than 4 K0-failing rows, A2 is untestable and counts as not met.
- A3, substitute comparison: at least 0.95 of I(g) rows have band_max at most g.
- A4, gain: K1(g) fails strictly fewer confirmatory passes than K0.
- A5, coverage: W(g) holds at least half of the scored confirmatory rows.

How shares and comparisons are computed:
- Shares are exact ratios of counts.
- Comparisons with g and S* are exact rational comparisons of the float64 values.
- The 0.05 comparison is the float comparison `ndvi_median_check` makes.

A pass fails a candidate when any of the following holds:
- any of its scored rows fails the candidate;
- any of its rows fails on a DEA CRS or grid difference;
- its correlation check has at least 5 rows and r is 0.95 or less.

A correlation check that `ndvi_correlation_check` skips does not fail a pass. It skips below 5 rows and when the correlation is undefined because the values are constant.

Reported for each candidate:
- the number and share of confirmatory passes, and of the two nomination passes, on which the NDVI checks alone would make `verify` exit 3;
- the share of scored rows that fail.

Hypotheses, reported and not decision inputs.

- H1, conditioning: the K0 failures come from ill-conditioning at low red + nir. Supported when A1 and A2 hold. Not supported when K1 is not nominated or either criterion fails.
- H2, mask (ramsar-13): the stored median and the compared pixels differ for ramsar-13. Supported when, on both seen 2026-11-11 ramsar-13 rows, |ndvi_pipeline_same - ndvi_dea| is at most 0.05 while abs_diff is above 0.05. Both rows are those of the nomination sample, read against the DEA item `find_nbart_item` selects on the run day. H2 is untestable when either row is not scored. Expected not supported, since DEA nodata was 0 on both rows.
- H3, tile: per-tile Sen2Cor processing makes one polygon's pipeline median differ between overlapping tiles of a pass more than DEA's median does.
  - It is tested over confirmatory pairs of one polygon and pass on two tiles, both scored with equal n_compared.
  - Supported when there are at least 10 pairs and the median absolute between-tile difference of ndvi_stored is both at least twice that of ndvi_dea and at least 0.005.
  - Untestable with fewer than 10 pairs.
- H4, maturity: nrt references explain the 2026-11-11 failures.
  - It is tested on the four seen 2026-11-11 failing rows as re-read in the nomination sample, each against the run-day DEA item of its own tile (50HLK or 50HLJ).
  - Testable only if the run-day items of both tiles are not nrt. It is untestable when either is still nrt, when either tile has no run-day DEA item or when any of the four rows is not scored.
  - Supported when all four rows then pass K0.
  - Reported for context: the K0 row failing share by DEA maturity over the confirmatory rows.

Reading rule.
- The decision depends on A0 to A5 only.
- The cause recorded in Spike results and ADR 0013 names every supported hypothesis, or 'not identified' when none is supported.
- No hypothesis result changes the decision.
- The outcome is written as a line on its own, `NDVI row rule: K0` or `NDVI row rule: K1`. For K1, a second line gives `NDVI row parameters: g = <g>, S* = <S*>`.

Status. The outcome is recorded in ADR 0013 (`docs/decisions/0013-ndvi-row-rule-against-dea-nbart.md`). It is decided by this pre-registered rule under Jarrod's request to complete the outstanding work, and is not yet approved by Jarrod. If K1 is adopted, a follow-up story for the code change is filed depending on st-a32a. If not, st-da75 is parked with the measured rates.

## Pre-registered hypotheses (st-dd0d, 2026-11-14)

Recorded before any advisory summary of the sample below exists or is read, and before the research script is written.

Context. Since st-a32a (ADR 0012) the rows of the live water check `water_vs_dea_s2_wo` on the `dea_waterbody` layer (the 1,404 DEA Waterbodies polygons, polygon_id `dea-<uid>`) are advisory: they hold no verdict, and each `wetland-change verify` run reports one advisory summary per live check and layer (`advisory_summaries` and `advisory_note` in `src/wetland_change/verify/layers.py`). For water the summary gives the rows scored, skipped and errored, the rows outside the ramsar limit and those outside it on wet area alone, the pooled agreement with DEA WO over the mutually clear pixels, and the pooled wet gap. No limit has been calibrated for this layer. Story st-dd0d decides whether the layer gets its own blocking run-level limit on its pooled agreement, set from runs that had not been seen when this rule was written. Whether a waterbody polygon is ever scored one by one is not part of this rule.

Disclosure.

- (a) Two passes measured before st-a32a have been seen and are not part of the sample. On the dea_waterbody layer the pooled agreement was 0.9237 with a pooled wet gap of -2.21 pp on 2026-10-29, and 0.9054 with +5.51 pp on 2026-11-11, against 0.9878 and 0.9616 on the ramsar layer (ADR 0012; `docs/research/2026-11-12-live-check-layers.csv` and `.txt`). At the default agreement_min of 0.91, 297 of 653 and 262 of 599 scored waterbody rows failed agreement. The size-bin figures in ADR 0012 have also been seen.
- (b) The minimum sample, the candidate formula, the 0.85 floor and the 90 percent wet gap share were written in story st-dd0d on 2026-11-12, after (a) was seen. The sample end of 2027-01-31, the minimum of 30 scored rows per run and the exclusion of `verify.yml` runs were set on 2026-11-14 as option (b) of the story's park question. The question did not label a recommendation; Jarrod replied 'push & approved recommended', and the orchestrator took option (b), its own recommendation, as approved. The close at the first eligible run that meets the minimum is the planner's reading of 'closes at the 8th eligible run' in that option. All of these were fixed after (a) was seen and before any run of the sample existed.
- (c) Checked on 2026-11-14 at 12:35 UTC from git and GitHub run metadata only, with no report, run log or output-store object opened. st-a32a was merged to local main at 08ec2ec (02:14 UTC) and reached GitHub main in 2db25a1956062302b11522308ac571a3ea0061b2, pushed at 04:11 UTC. The last scheduled `pipeline` run before it, 43475454140, started at 2026-11-13 17:42 UTC on 37af4e4. No `pipeline` run had started since, and GitHub main held no commit `Verification report for <id>` after 2db25a1.
- (d) On 2026-11-14 the planner read Earth Search item metadata, with no pixel read. Full AOI passes came every 5 days (2026-11-01, 2026-11-06, 2026-11-11) and a T50HMJ edge pass 2 days after each (2026-11-03, 2026-11-08, 2026-11-13). The edge footprint touches 32 of the 1,404 waterbody polygons, so an edge-pass run scores at most 32 waterbody rows. A clear edge-pass run that scores 30 to 32 of them is therefore eligible under the 30-row minimum and can set A_min. The same window of 2025 and of 2024 had 6 acquisition dates each under the 20 percent cloud limit. The minimum is therefore not expected by 2026-12-05, the end of the four-week trial, and the sample runs past it.
- (e) The sample falls in November to January, early in the dry season. The ramsar limits were calibrated on August to October passes. A limit set from this sample may not hold in winter.
- (f) DEA S2 WO is unvalidated. The limit measures consistency with WO, as ADR 0005 says, not accuracy.
- (g) With 8 or 9 sample runs, D3 below allows no run outside 5.00 pp. With 10 to 19 runs it allows one.

Definitions.

- Scheduled run: a GitHub Actions run of `.github/workflows/pipeline.yml` with event `schedule` and run attempt 1 whose head commit is 2db25a1956062302b11522308ac571a3ea0061b2 or a descendant of it. Runs of `.github/workflows/verify.yml`, `pipeline` runs with event `workflow_dispatch`, later attempts of a run, and any other `wetland-change verify` or backfill call are not scheduled runs. `verify.yml` re-verifies the scenes of the latest daily run, so counting it would count the same rows twice.
- Report of a scheduled run: the markdown report `docs/research/verification-<run_id>.md` that the run committed to main in its commit `Verification report for <GitHub run id>`, for the run id that the run's own `wetland-change run` step created. That run id (UTC, `%Y%m%dT%H%M%SZ`) falls between the GitHub run's start and its last update; reports of recovered runs in the same commit have earlier run ids and are not used. For a GitHub run that has later attempts, the start and last update are those of attempt 1. The markdown report is the record because the scheduled `verify.yml` run overwrites `verification/<run_id>.json` in the unversioned output bucket for the run it checks (header of `.github/workflows/verify.yml`), so the JSON copy may no longer be the one the scheduled run wrote.
- Values of a run: read from the report's `## Advisory` row with check `water_vs_dea_s2_wo` and layer `dea_waterbody`, as `advisory_note` prints them: rows scored, skipped and errored, rows outside the ramsar limit, rows outside it on wet area alone, pooled agreement (4 decimals), mutually clear pixels and pooled wet gap (pp, 2 decimals). The `ndvi_vs_dea_nbart` row for the layer gives rows scored and the median absolute difference, which are reported only. A report without the water row for the layer has 0 scored waterbody rows.
- Acquisition dates of a run: the UTC dates of `datetime` of the run's succeeded scenes, as `scenes_for_run` (`src/wetland_change/verify/run.py`) reads them from the output store's ledger. These are the scenes `verify` scored.
- Eligible run: a scheduled run with a report, at least 30 scored waterbody rows in its water row and no scene acquired on 2026-10-29 or 2026-11-11. Every other scheduled run is listed with its reason: no report (no processed scenes, no report written or the commit failed), fewer than 30 scored rows (with the count), or a scene on a seen date.

Sample. The eligible runs in order of GitHub run start. The sample closes at the first eligible run at which it holds at least 8 runs on at least 6 distinct acquisition dates. That is the 8th eligible run when those 8 runs span at least 6 dates; otherwise it is the first later eligible run that brings the dates to 6. If no eligible run meets that among runs started on or before 2027-01-31 23:59:59 UTC, the sample closes then and holds every eligible run started by that time. No eligible run before the close is dropped and none after it is added. The trial end on 2026-12-05 does not close the sample.

Candidate. A_min is the lowest pooled agreement over the sample runs, as printed to 4 decimals. The candidate limit L is the floor to 0.01 of (A_min minus 0.02), computed exactly in decimal arithmetic from the printed value, the ADR 0005 and ADR 0007 convention. For example, an A_min of 0.9054 gives 0.88. W is the share of sample runs whose pooled wet gap, as printed to 2 decimals, has an absolute value of 5.00 pp or less, an exact ratio of counts.

Decision rule. Adopt a run-level limit of L on the dea_waterbody layer only if D1 to D3 all hold. Otherwise the layer stays advisory and the measured rates are recorded.

- D1, sample: at least 8 runs on at least 6 distinct acquisition dates. When D1 fails, the outcome is recorded as below the minimum with the counts of runs and dates, and D2 and D3 are reported for context when the sample holds at least one run.
- D2, floor: L is at least 0.85.
- D3, wet gap: W is at least 0.9.

Meaning of the limit. An adopted limit fails a run whose dea_waterbody pooled agreement in `water_vs_dea_s2_wo` is below L, the run-level analogue of agreement_min. Rows on the layer stay advisory and get no per-row verdict. The wet gap enters only through D3, and this rule sets no wet gap limit for the layer. Story st-dd0d adds no limit to config or code. An adopted limit is implemented by a follow-up story after Jarrod approves the ADR, and that change supersedes ADR 0012 for this layer's water check.

Reported, not decision inputs:
- per scheduled run: the GitHub run id, start time and head commit, the run id, eligibility and reason, acquisition dates and tiles, every value of the water row, and the NDVI rows scored and median absolute difference;
- over the sample: A_min, the median and range of the pooled agreement and of the pooled wet gap, and the share of scored waterbody rows outside the ramsar limit, summed over the runs;
- for each sample run whose JSON report in the output store has the same `generated_at` as the markdown report's 'Generated' time, the unrounded pooled agreement beside the printed one, and the L the unrounded values would give; L itself always uses the printed values;
- the commits between 2db25a1 and the head commit of the last sample run that change a file under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/pipeline.yml` or `scripts/fetch_aoi.py`, listed and not corrected for;
- whether L would have failed either seen pass of (a).

How the script runs. The research script `docs/research/<date>-waterbody-layer-agreement.py`, where `<date>` is the UTC date of its decision run, is written and its tests pass on synthetic reports before it reads any report of the sample, and no report of the sample is opened by hand before the script's output files are committed. The same ban covers every other route to a sample report until the decision files are committed: the run logs of sample pipeline and `verify.yml` runs, `verification/` objects in the output store, and any `git diff`, `git log -p`, `git show` or search output that includes a sample report. Outside the script, only commit metadata and `gh run list` JSON fields may be read. Before the sample closes, the script may run in a status mode that prints only the counts of scheduled runs, eligible runs and acquisition dates and whether the sample has closed, and writes nothing; st-dd0d is re-parked with those counts. After the close the decision run happens once. If a network failure stops it before it writes its files, it is rerun once and both attempts are recorded. It writes a CSV with one row per scheduled run considered and a text summary. The outcome is written as a line on its own, `Waterbody layer water limit: <L>` when adopted (for example `Waterbody layer water limit: 0.88`) or `Waterbody layer water limit: advisory` otherwise, followed by a line `Failed criteria: <ids>` naming the failed criteria or `none`.

Status. The outcome is recorded in ADR 0015 (`docs/decisions/0015-waterbody-layer-live-water-limit.md`) with a status line saying it is decided by this pre-registered rule and is not yet approved by Jarrod. st-dd0d stays parked until the sample closes.

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
The script that produced it is docs/research/2026-10-29-polygon-calibration.py
(it takes --start and --end). The original DEA WO provisional window has
passed, so the CSV is the record.

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
script that produced it is docs/research/2026-10-30-waterbodies-tolerance.py.

### Backfill hypotheses (2026-11-03)

Report: [docs/research/2026-11-03-backfill-hypotheses.md](docs/research/2026-11-03-backfill-hypotheses.md). Range 2022-12-01 to 2026-11-02, 1147 items processed, 0 failed, coverage 1.0 of a 1147 item reference (0.8756 of the 1310 item raw search count).

- H1: supported, 2 low flags in 3 scored dates: 2023-12-17 (z -8.87) and 2023-12-22 (z -5.16). DEA wet fraction is 0.0 on all 5 passes in the window.
- H2: untestable for 2023, 0 of 12 dates scored, all 12 `too_few_samples`; no NDVI flags. The 2022 half is untestable: Earth Search Collection 1 has no items covering Forrestdale for February to April 2022 under the 20 percent cloud filter (2 unfiltered items on 2022-03-22 were excluded by it, at 39.8 and 68.6 percent cloud).
- H3: not supported. ramsar-56 median delta -14.38 ha over 1 scored date (0.0 share at or above baseline) with a low flag on 2025-08-23 (z -3.39); ramsar-52 has 0 of 5 dates scored.
- H4: not supported. Spearman rho and n pairs: Forrestdale 0.870 (93), Thomsons 0.897 (99), Lake Clifton 0.858 (98), Lake Preston 0.861 (98); all below 0.9.

### Wet area clause (2026-11-05)

Rows: [docs/research/2026-11-05-wet-area-gap.csv](docs/research/2026-11-05-wet-area-gap.csv), written by [docs/research/2026-11-05-wet-area-measure.py](docs/research/2026-11-05-wet-area-measure.py), summarised in [docs/research/2026-11-05-wet-area-summary.txt](docs/research/2026-11-05-wet-area-summary.txt). 253 rows with at least 100 mutually clear pixels, over 35 scenes and the 27 polygons `load_ramsar` keeps for the configured `site_prefixes`: every polygon on the 6 newest dates (2026-09-12 to 2026-10-29), and ramsar-28 on all 12. 2 rows fall under 100 pixels and are left out, ramsar-14 with 0 and ramsar-22 with 22, both on `S2B_T50HLJ_20260912T022111_L2A`. DEA held WO for every scene. `agreement` was checked against `wo_check`'s `measured` on every row, and the two never differed.

- H1: held. 251 rows pass agreement and 242 of them are within 5 pp, rate 0.9641.
- H2: held. 22 ramsar-28 rows pass agreement and 21 of them are within 5 pp, rate 0.9545.
- Per scene: 2 of 35 (0.0571) have at least one polygon failing agreement. 10 of 35 (0.2857) have at least one failing agreement or the clause.
- Decision rule: both hold, so the clause goes into `Check.passed`.

| group | rows | pass agreement | within 5 pp | rate | median abs gap (pp) | p95 abs gap (pp) |
|---|---|---|---|---|---|---|
| ramsar-15 | 6 | 5 | 5 | 1.0000 | 0.445 | 4.533 |
| ramsar-28 | 22 | 22 | 21 | 0.9545 | 2.326 | 4.967 |
| ramsar-56 | 10 | 10 | 10 | 1.0000 | 0.717 | 1.709 |
| other 24 polygons | 215 | 214 | 206 | 0.9626 | 0.000 | 4.839 |

Not pre-registered, found after the rule was applied:

- H1 and H2 count rows, and verify's exit code depends on the whole run. A date has 29 to 45 rows, and `verify` exits 3 if any check fails. On the 6 dates with every polygon measured, 2 have a row failing agreement (ramsar-15 on 2026-09-17, ramsar-16 on 2026-09-12). All 6 have a row failing agreement or the clause. A daily run holding all of one of these dates' scenes would exit 3 on 2 of 6 dates today and on 6 of 6 with the clause, and the pipeline job then ends red. This sample is 6 dates from one season.
- ramsar-12 is 5 of the 9 rows that fail only the clause. The pipeline is wetter than WO on both tiles on all 6 dates, by 3.12 to 4.83 pp through 2026-10-02, 4.86 and 5.38 pp on 2026-10-12, and 5.90 to 6.82 pp on 2026-10-27 and 2026-10-29. The cause was not investigated.
- 124 of the 253 rows are dry in both sources and pass the clause trivially. Of the 104 rows that pass agreement with at least 1 percent wet in either source, 95 are within 5 pp, rate 0.9135.
- The clause can bind on 30 of the 251 rows that pass agreement, those with 1 minus agreement above 5 pp. 9 of the 30 fail it.

### Exit rule for the live water check (2026-11-06)

Rows: [docs/research/2026-11-06-exit-rule-shares.csv](docs/research/2026-11-06-exit-rule-shares.csv), written by [docs/research/2026-11-06-exit-rule-shares.py](docs/research/2026-11-06-exit-rule-shares.py), summarised in [docs/research/2026-11-06-exit-rule-shares.txt](docs/research/2026-11-06-exit-rule-shares.txt). Decision: [docs/decisions/0008-exit-code-for-live-water-check-failures.md](docs/decisions/0008-exit-code-for-live-water-check-failures.md). Input is `docs/research/2026-11-05-wet-area-gap.csv` (sha256 8eda9a0d4d304ad96fcda3f82a66ca52d5a0022d5b73a7ae7e3c4f9006b6506c), 253 rows with at least 100 mutually clear pixels; 2 rows under 100 are left out. No raster was read. The pre-registered rule is the st-7047 Part A section above, which discloses that the per-date counts for K2 and K1 were already readable when it was written. This is a policy choice recorded before the script ran, not a blind test.

Measured dates, newest first. FAIL means `verify` would exit 3 for a run holding every scene of that date. Pooled gap is in percentage points, positive when the pipeline is wetter than WO.

| pass date | rows | rows failing agreement | rows failing the clause alone | pooled gap (pp) | K1 | K2 | K3 | K4 |
|---|---|---|---|---|---|---|---|---|
| 2026-10-29 | 34 | 0 | 2 | 1.142 | FAIL | ok | FAIL | ok |
| 2026-10-27 | 45 | 0 | 2 | 1.560 | FAIL | ok | FAIL | ok |
| 2026-10-12 | 45 | 0 | 1 | 1.138 | FAIL | ok | ok | ok |
| 2026-10-02 | 45 | 0 | 1 | 0.778 | FAIL | ok | ok | ok |
| 2026-09-17 | 45 | 1 | 1 | 0.434 | FAIL | FAIL | FAIL | FAIL |
| 2026-09-12 | 29 | 1 | 1 | 1.992 | FAIL | FAIL | FAIL | FAIL |

Share of the 6 measured dates that fail: K1 6 of 6 (1.0000), K2 2 of 6 (0.3333), K3 4 of 6 (0.6667), K4 2 of 6 (0.3333). B, the number of dates failing under K2 (agreement alone), is 2. Admissible set: K2 and K4 (K1 fails 4 more dates than B and K3 fails 2 more, both above the allowed 1). K2 and K4 tie on 2 of 6, and K4's failing condition includes K2's, so the tie goes to K4. Chosen rule: K4. Reason: when two rules fail the same measured dates, keep the one under which the wet area clause can still fail a run, so a run-wide wet bias against WO is not reduced to warnings. Under K4 the 2 failing dates, 2026-09-17 and 2026-09-12, both fail on agreement, and the pooled gap stays below 2.0 pp on every measured date, so the pooled condition fails no measured date.

Rows failing the clause alone, which pass agreement and have an absolute gap above 5.0 pp: 9 of 253 (0.0356). Under the chosen rule these are `warn` rows.

K4's script recovers each wet count as round(share * n) from the CSV, and the code recovers the counts the same way and sums them as integers, so the pooled gap is exact at the 5.0 pp limit.

The sample is 6 dates from one season. The unmeasured dates hold ramsar-28 only (6 dates, 1 to 2 rows each) and are not counted.

### ramsar-12 wet area gap (2026-11-06)

Rows: [docs/research/2026-11-06-ramsar-12-gap.csv](docs/research/2026-11-06-ramsar-12-gap.csv), written by [docs/research/2026-11-06-ramsar-12-gap.py](docs/research/2026-11-06-ramsar-12-gap.py), summarised in [docs/research/2026-11-06-ramsar-12-gap.txt](docs/research/2026-11-06-ramsar-12-gap.txt). The hypotheses G1 to G5 are the st-7047 Part B section above.

Reproduction check: passed. All 12 ramsar-12 rows re-read from Earth Search and DEA match the CSV on n_mutually_clear and on gap_pp (within 0.01 pp). At the global setting (MNDWI above -0.1) the pipeline is wetter than WO on all 12 rows, from +3.12 pp to +6.82 pp, with a pooled a of 5563 and b of 386.

- G1, threshold: supported. Every grid value from -0.05 to +0.15 gives an absolute gap of 5 pp or less on all 12 rows. -0.10 gives 7 of 12 rows within 5 pp (mean absolute gap 4.875 pp) and +0.20 gives 10 of 12 (4.155 pp). The lowest mean absolute gap is at +0.05 (0.512 pp, mean signed gap -0.374 pp). Pooled agreement by threshold: -0.10 0.9437, -0.05 0.9563, +0.00 0.9637, +0.05 0.9632, +0.10 0.9586, +0.15 0.9526, +0.20 0.9471.
- G2, SCL class 6: not supported. scl6 gives 7 of 12 rows within 5 pp, mean absolute gap 3.964 pp, pooled agreement 0.8998, and the gap is negative (SCL drier than WO) with a minimum of -7.74 pp.
- G3, edge: supported. The edge ring holds 1555 of the 5563 a-pixels (0.2795) and 10096 of the 105736 mutually clear pixels (0.0955). The ratio is 2.927 against a rule of at least 2.0.
- G4, SCL class of the a-pixels: supported. Of the 5563 a-pixels, class 4 (vegetation) holds 373 (0.0671) and class 5 (not vegetated) 3356 (0.6033), together 0.6703 against a rule of at least 0.50. Class 6 (water) holds 943 (0.1695) and class 7 (unclassified) 891 (0.1602).
- G5, stored history: supported. Of 299 stored ramsar-12 rows with water_ha_index or water_ha_scl above 0 (316 rows read, 1147 files), 296 have water_ha_index above water_ha_scl, share 0.9900 against a rule of at least 0.75. The median difference is 8.55 ha. Every calendar year from 2022 to 2026 has a share of at least 0.9524, so the over-call is not specific to the 6 sampled dates.

Cause: the supported hypotheses are G1, G3, G4 and G5. The MNDWI threshold of -0.1 over-calls water against WO on this polygon, and some threshold from -0.05 to +0.15 would bring every sampled row within 5 pp (G1). The extra wet pixels sit disproportionately on the polygon edge (G3) and are mostly vegetation or not-vegetated land in the SCL (G4). The same direction shows in the stored history from 2022 to 2026 (G5).

What remains unknown. The result does not say which source is right. DEA S2 WO is unvalidated, so the gap measures consistency with WO, and G1 shows that a threshold near 0 to +0.05 matches WO, not that it is correct. G1, G3 and G4 are not tested against each other, so the share of the gap each explains is not separated. The sample is 12 rows from 6 dates of one season, and G5 tests only the direction of the index and SCL columns. Changing ramsar-12's water setting is a decision under ADR 0005 and is not made here.

### DEA WO availability at first processing (2026-11-06)

Rows: [docs/research/2026-11-06-wo-availability.csv](docs/research/2026-11-06-wo-availability.csv), written by [docs/research/2026-11-06-wo-availability.py](docs/research/2026-11-06-wo-availability.py), summarised in [docs/research/2026-11-06-wo-availability.txt](docs/research/2026-11-06-wo-availability.txt). The sample, match rule, timestamps and decision rule are the st-5f74 section above. The script ran once live on 2026-11-06 at 02:09 UTC against Earth Search and the DEA explorer (120 Earth Search items and 140 DEA items fetched, 44 of the Earth Search items inside the sample window and cloud limit).

Share available at first processing: 44 of 44

N is 44 scene-tiles over tiles 50HLJ, 50HLK, 50HMJ, 50HMK, 50JLL and 50JML, with no duplicate item ids. S is 1.0000 (K = 44), Wilson 95 percent interval 0.9197 to 1.0000. H1 (S at least 0.90) holds. Every scene-tile has a WO item at measurement time, so none lacks a WO item and none arrived after first processing. With T_proc plus 2 hours (S2) the share is also 44 of 44.

Lag, A_wo minus T_proc in hours, nearest rank over the 44 scene-tiles: min -22.963, p25 -2.824, median -1.942, p75 -1.369, p90 -1.196, max -0.352. The smallest margin is 0.352 hours (21 minutes), so a run delay of more than about 21 minutes on the least favourable scene-tile would make that row null under the pre-registered timing. The -22.963 minimum is a scene-tile whose Earth Search item was created at 11:22 UTC on the acquisition day, after that day's run, so its T_proc is the next day's.

By acquisition month, available of n: 2026-08 9 of 9, 2026-09 12 of 12, 2026-10 23 of 23, and no scene-tile without a WO item in any month.

Outcome: populate

The decision is recorded in [docs/decisions/0009-dea-wo-agreement-populated-at-processing-time.md](docs/decisions/0009-dea-wo-agreement-populated-at-processing-time.md).

The rule is the pre-registered one (S at least 0.50), applied by the script's `decide`. It matches the exploratory pass noted in the disclosure, so this result is not a blind confirmation. The second condition of the rule, that a DEA failure provably cannot fail the daily run, is not tested by the script. Update 2026-11-06: it is met by `test_process_scene_survives_dea_errors` and `test_run_once_with_failing_lookup_still_processes_the_scene` in `tests/test_wo_observation.py`, so the outcome stays populate.

Limits. The bbox approximates the AOI union bbox, so a scene-tile touching only the real AOI edge could differ. The cron instant ignores scheduler delay and run duration; S2 adds 2 hours and does not change the result. A_wo is the DEA STAC index time (`properties.created`), not a documented product-ready time; the asset-path stamp (`wo_path_stamp`) is recorded as a secondary field and was not used for the decision. The sample is 44 scene-tiles over 81 days of one season and covers cloud cover of at most 20 only. The result says nothing about a DEA outage or a processing backlog later in the year.

### ramsar-12 setting confirmation (2026-11-06)

Rows: [docs/research/2026-11-06-ramsar-12-confirm.csv](docs/research/2026-11-06-ramsar-12-confirm.csv), written by [docs/research/2026-11-06-ramsar-12-confirm.py](docs/research/2026-11-06-ramsar-12-confirm.py), summarised in [docs/research/2026-11-06-ramsar-12-confirm.txt](docs/research/2026-11-06-ramsar-12-confirm.txt). The candidates, sample, selection and R1 to R6 are the st-2a78 pre-registration above, committed as 959d15a ("st-2a78: Pre-register the ramsar-12 water setting rule"). The script and its decision tests were committed as ca8742e ("st-2a78: Add the ramsar-12 confirmatory script and its decision tests"), before the measurement. The script ran once live on 2026-11-06, starting 05:08 UTC and finishing 05:09 UTC (about 60 seconds), against Earth Search and DEA. It exited 0 on the first attempt, so there was no rerun, and no script or rule change after the commits.

Sample: 7 scene-tiles on 4 dates (2026-08-23, 2026-08-28, 2026-08-30, 2026-09-07; tiles 50HLJ and 50HLK; 50HLK only on 2026-08-23). Discovery returned 19 scene-tiles in the window. 12 were dropped, all with the reason 'acquired on seen date' (2026-09-12, 2026-09-17, 2026-10-02, 2026-10-12, 2026-10-27 and 2026-10-29, both tiles each). None was dropped for a missing WO item, a differing grid or fewer than 100 mutually clear pixels. Mutually clear pixels per row ranged from 8707 to 9859. This matches the 7 scene-tiles on 4 dates expected in disclosure (b).

Over the 7 confirmatory rows, by threshold (pooled agreement, mean absolute gap, mean signed gap):

- -0.10 (baseline): 0.9495, 1.942 pp, -0.544 pp
- +0.00: 0.9474, 2.998 pp, -2.926 pp
- +0.05: 0.9440, 4.073 pp, -4.073 pp
- +0.10: 0.9365, 5.227 pp, -5.227 pp
- scl6 (context only): 0.8636, 8.850 pp, -8.850 pp

Selected T: +0.00, the candidate with the lowest mean absolute gap. +0.05 is not the selected value.

- R1, sample: pass. 7 rows on 4 dates, need at least 6 rows on at least 3 dates.
- R2, clause: fail. Maximum absolute gap 6.465 pp (2026-08-23, 50HLK), need 5.0 or less. Three of the 7 rows exceed 5.0 pp at +0.05 and 1 row exceeds it at +0.00.
- R3, gain: fail. Pooled agreement 0.9474 minus 0.9495 is -0.0020, need at least 0.005.
- R4, consistency: fail. Agreement at +0.00 exceeds agreement at -0.10 on 2 of 7 rows (0.2857), need at least 0.6667.
- R5, no over-correction: fail. Mean signed gap -2.926 pp, need an absolute value of 2.0 or less.
- R6, floor: pass. agreement_min computes to 0.93 over 19 rows (12 seen plus 7 confirmatory) at +0.00, need at least 0.91. 1 of the 19 rows is below 0.93.

Failed: R2, R3, R4, R5. Not inconclusive.

Outcome: keep-global

The global setting (MNDWI above -0.1, agreement_min 0.91) stays for ramsar-12. No per-polygon override is added. At the global setting the confirmatory rows show the opposite sign to the seen rows: the pipeline is drier than WO on 5 of 7 rows (gap -4.107 to -0.261 pp) and wetter on the 2 rows of 2026-09-07 (+2.466 and +2.426 pp), with a mean signed gap of -0.544 pp. The seen rows were wetter than WO on all 12 (+3.12 to +6.82 pp). The sign of the gap therefore differs between the seen and confirmatory dates, and every raised threshold makes the confirmatory rows drier than WO.

Limits. The confirmatory dates are 2026-08-23 to 2026-09-07, the wetter season, so the dry end of the season rests on the seen rows and is not confirmed. The sample is 7 rows on 4 dates, and the 2 tiles of one date are not independent. DEA S2 WO is unvalidated, so this measures consistency with WO and not accuracy. The 12 seen rows were not used to decide, except as seen-row counts in R6. The result does not say why the gap changes sign between August to early September and September to October; the two samples differ in date, and no test here separates a seasonal effect from a scene effect.

### S5 runner timing (2026-11-14)

Spike 5 in the design ("Pre-start spikes", item 5) planned a runner dry run in a throwaway public repository: uv sync time, rasterio import, OIDC role assumption, minutes per run, and confirmation that Actions minutes are free on standard runners for public repositories. It was blocked on a throwaway repository with an OIDC role. The production workflow `.github/workflows/pipeline.yml` (cron `17 10 * * *`, 10:17 UTC; `runs-on: ubuntu-24.04`; job `timeout-minutes: 120`) has since run through OIDC, so the figures below are read from those runs with `gh run list` and `gh run view` on 2026-11-14, not from a dry run. No run for 2026-11-14 was listed at the time of writing.

Runs read: 8, one `workflow_dispatch` and 7 scheduled. The manifest printed by the step "Read the processed scene count and recovered runs" shows processed 0 and failed 0 on 7 of them. One run processed scenes.

- 42227866026, workflow_dispatch, 2026-11-06, created 13:43:58Z. Processed 0. "Verify the run" skipped. Job 45 s.
- 42391137737, scheduled, 2026-11-07, created 16:24:29Z. Processed 0, verify skipped. Job 50 s.
- 42500964092, scheduled, 2026-11-08, created 16:39:02Z. Processed 0, verify skipped. Job 54 s.
- 42695477540, scheduled, 2026-11-09, created 20:42:14Z. Processed 0, verify skipped. Job 50 s.
- 42868562753, scheduled, 2026-11-10, created 17:47:39Z. Processed 0, verify skipped. Job 53 s.
- 43072355326, scheduled, 2026-11-11, created 17:52:40Z. Processed 5, failed 0. "Verify the run" ran. Job 1560 s.
- 43278279989, scheduled, 2026-11-12, created 18:17:29Z. Processed 0, verify skipped. Job 53 s.
- 43475454140, scheduled, 2026-11-13, created 17:42:32Z. Processed 0, verify skipped. Job 56 s.

Processed runs as measured on the day: n = 1 (43072355326). The story's n = 1 matches the runs listed.

Run 43072355326 concluded `failure`. The step "Verify the run" failed: its output holds FAIL rows on `water_vs_dea_s2_wo` and `ndvi_vs_dea_nbart` (424 lines containing FAIL in the log). The pipeline step succeeded, and "Build the catalogue" and "Commit the verification report" still ran and succeeded. Seconds per step, from each step's `completedAt` minus `startedAt`, for steps of 1 s or more:

| Step | Seconds | Conclusion |
|---|---|---|
| Set up job | 3 | success |
| Check out the repository | 1 | success |
| Install uv and Python | 2 | success |
| Install the project (`uv sync --locked`) | 5 | success |
| Assume the AWS role through OIDC | 1 | success |
| Fetch the AOI | 4 | success |
| Run the incremental pipeline (17:53:00 to 17:58:36) | 336 | success |
| Verify the run (17:58:36 to 18:18:10) | 1174 | failure |
| Build the catalogue so it links the verification report | 28 | success |
| Commit the verification report | 2 | success |
| Job total (`startedAt` 17:52:43 to `completedAt` 18:18:43) | 1560 (26 min 0 s) | failure |

The read count step, the skipped "Verify the runs this run recovered" step and the post steps are under 1 s. Gaps between steps are not attributed. The job total is 1560 s against the 7200 s limit.

Seconds per scene, with `processed` as the divisor. In the manifest, `processed` counts ledger entries with status succeeded (`_tally` in `src/wetland_change/pipeline.py` adds 1 per succeeded entry). A ledger entry is keyed by `item_id`, one Earth Search item, so a scene here is one scene-tile (one tile of one pass), not a pass.

- Pipeline step: 336 / 5 = 67.2 s per scene.
- Verify step: 1174 / 5 = 234.8 s per scene.
- Sum: 302.0 s per scene.

The local figure in `docs/research/2026-11-03-backfill-hypotheses.md` is 138.7 s (sleep call excluded) to 152.3 s per processed scene, which is the sum of the 35 backfill call durations divided by the 1147 succeeded ledger entries. It covers the backfill process only, run as three overlapping lanes on a laptop, so its seconds are summed runner time, and it does not include verify. Only the pipeline step is comparable: 67.2 s on the runner against 138.7 to 152.3 s locally. The 67.2 s includes the step's fixed work (start-up and discovery) spread over 5 scenes. No test here separates a machine effect from a lane or batch-size effect.

Start delay against the 10:17 UTC cron, from `createdAt` on the same UTC date, scheduled runs only: 6 h 07 m (11-07), 6 h 22 m (11-08), 10 h 25 m (11-09), 7 h 30 m (11-10), 7 h 35 m (11-11), 8 h 00 m (11-12), 7 h 25 m (11-13). The range is 6.1 to 10.4 h. The dispatch run is not a cron start and is left out. These delays exceed the 21-minute smallest margin recorded in "DEA WO availability at first processing (2026-11-06)"; this is an observation only and changes no decision. The weekly verify workflow (`verify.yml`) runs at 22:43 UTC on Sundays.

Zero-processed days: job duration 45 to 56 s (scheduled runs 50 to 56 s), and 50 to 80 s from run creation to the run's `updatedAt` (the 80 s is 43475454140).

How many scenes fit in the 120 minute job. Fixed overhead is the job total minus the pipeline and verify steps: 1560 - 336 - 1174 = 50 s. At 302.0 s per scene, (7200 - 50) / 302.0 = 23.7, so 23 scenes. For the pipeline step alone, 7200 / 67.2 = 107 scenes. The estimate assumes linear scaling from one run of 5 scenes. The verify step also reads the whole stored observation history for the Spearman check (see "Spearman threshold calibration" and ADR 0007), so its cost per scene is not separable from the history it reads at n = 1, and its fixed part grows with the store. `pipeline.yml` sets no step-level timeout on the verify step, so a slow verify is bounded only by the 120 minute job limit.

What spike 5 planned and what these runs cover. The design lists uv sync time, rasterio import, OIDC role assumption, minutes per run, and free Actions minutes for public repositories.

- uv sync time: covered. "Install the project" is `uv sync --locked`, 5 s on this run (5 to 6 s on the 8 runs read); "Install uv and Python" was 1 to 2 s.
- OIDC role assumption: covered. "Assume the AWS role through OIDC" was 1 s on this run and 1 to 2 s on the others, and the later S3 steps used the credentials.
- Minutes per run: covered for one processed run (26 min 0 s) and 7 zero-processed runs (under 1 min).
- rasterio import: not timed separately. It happens inside the first `uv run` steps and is not isolated.
- Free Actions minutes: not checked in this entry. `gh repo view` reports this repository as PRIVATE on 2026-11-14, so the planned public-repository condition does not hold for these runs, and the minutes the runs used were not looked up.
- Peak memory on the runner: not measured. The design's risk table assigns "Runner time and memory for Peel-Yalgorup" to spike 3, not spike 5; spike 5 as written plans no memory measurement. The S3 entry above recorded a peak RSS of 518 MiB for the largest polygon read, which was a local run, not a runner.
- Per-request S3 latency: not measured, and not in the spike 5 plan either.

Other spikes. Spike 6 (hand-written catalogue on a bucket with CORS, opened in stac-browser) and the anonymous-read form of spike 7 (DuckDB reading the observations from S3 with one glob, with no credentials) stay blocked while the output bucket is private (`docs/decisions/0011-private-output-bucket.md`). The credentialed read is recorded in `stories/st-b49e-say-how-a-reader-with-an-aws-login-profi.md`: on 2026-11-14 both tests in `tests/test_live_private_outputs.py` passed against the bucket with credentials exported to the environment, and failed with `AWS_PROFILE` set to a login-session profile.

Report size. The per-processed-day verification report for the run, `docs/research/verification-20261111T175303Z.md`, is 730856 bytes (about 730 KB). The workflow committed it as 37af4e4 ("Verification report for 43072355326").

Limits. One processed run (n = 1, 5 scenes), on one day of one season (2026-11-11). That run failed verify, so the verify duration may differ from a passing verify, and a day with more scenes may scale differently. No repeat measurement was made. The runs read are the 8 listed by `gh run list` on 2026-11-14, and a later run may change the count.

### NDVI row rule against DEA NBART (2026-11-14)

Rows: [docs/research/2026-11-12-ndvi-nbart-nomination.csv](docs/research/2026-11-12-ndvi-nbart-nomination.csv) with [docs/research/2026-11-12-ndvi-nbart-nomination.txt](docs/research/2026-11-12-ndvi-nbart-nomination.txt) for the nomination sample, and [docs/research/2026-11-12-ndvi-nbart-rows.csv](docs/research/2026-11-12-ndvi-nbart-rows.csv) with [docs/research/2026-11-12-ndvi-nbart-rows.txt](docs/research/2026-11-12-ndvi-nbart-rows.txt) for the confirmatory sample. All four are written by [docs/research/2026-11-12-ndvi-nbart-rows.py](docs/research/2026-11-12-ndvi-nbart-rows.py). The candidates, samples, parameter rule, reproduction gate and A0 to A5 are the st-da75 pre-registration above. Both reads used the DBCA-010 ramsar GeoJSON whose sha256 matches the DBCA-010 row of `data/SOURCES.md`.

Commits on story/st-da75, oldest first:

- 098fb14, "st-da75: Pre-register the NDVI row rule against DEA NBART".
- fe0cf3c, "st-da75: Add the NDVI row research script and its decision tests".
- 47233f0, "st-da75: Harden the NDVI row script before the live reads". This is the only script change after fe0cf3c, and it came before any live read. No decision function, constant or sample changed.
- 3b82198, "st-da75: Record the NDVI row nomination read". This is the nomination commit, and the confirmatory phase took its input from the nomination files committed there.
- cd5af57, "st-da75: Record the NDVI row confirmatory read".

Runs, both against Earth Search and DEA on 2026-11-14 (UTC):

- Nomination: one attempt, 04:45:16 to 04:51:07 (5 min 51 s), exit 0, results written, no rerun.
- Confirmatory: one attempt, 05:03:18 to 05:25:43 (22 min 25 s), exit 0, results written, no rerun.

Nomination sample: 8 scene-tiles (3 on 2026-10-29, 5 on 2026-11-11), 79 rows. 78 were scored and 1 was skipped; no row had a grid or CRS difference, a read error, no DEA item or a rejection by `discover`. The skipped row is 2026-11-11 S2B_T50HLJ_20261111T022009_L2A ramsar-16 ('pipeline median not finite or fewer than 100 compared pixels'; 0 compared pixels). DEA maturity of the 8 scene-tiles: 3 final (all of 2026-10-29) and 5 nrt (all of 2026-11-11). The 78 scored rows are 34 on 2026-10-29 and 44 on 2026-11-11.

Reproduction of the eight seen failing rows: pass. All 8 reproduced `ndvi_stored`, the DEA NDVI median and `n_compared` with deviation 0.0, each against the DEA item the report recorded, which DEA still served. Of the other scored ramsar rows of the two issue #2 reports, 65 of 65 matched. 0 report rows were not produced.

Confirmatory sample: 32 scene-tiles on 8 passes, all 32 read. 294 rows: 292 scored and 2 skipped, with no grid or CRS difference, read error, missing DEA item, rejection by `discover`, row not returned or row outside the sample. Both skipped rows are on 2026-09-12 S2B_T50HLJ_20260912T022111_L2A and share the reason 'pipeline median not finite or fewer than 100 compared pixels'. For ramsar-14 the pipeline median is not finite (0 clear pixels and 0 compared pixels). For ramsar-22 the median is finite (0.4947) and the compared pixels are 28, below 100. DEA maturity of the scene-tiles read: 29 final and 3 nrt (2026-10-27 on 50HLK, 50JLL and 50JML). Of the 292 scored rows, 270 are against final items and 22 against nrt items.

Nominated g: none. K1 is not nominated, so A0 to A5 are not computed. No g in 0.002 to 0.010 meets N2: the share of I(g) rows with band_max at most g is 0.0000 to 0.3750 (0.3750 at g = 0.005), against the 0.95 required. N1 also fails at g = 0.002 (0.9452) and g = 0.003 (0.9429), and N3 fails from g = 0.007 (W holds 0.2949 of the scored rows at g = 0.007).

K0, the only candidate, by the share of passes on which the NDVI checks alone would make `verify` exit 3, and the failing row share:

- Confirmatory: 8 of 8 passes (1.0000); 87 of 292 scored rows fail (0.2979). The correlation check passes on every pass (r from 0.9779 to 0.9995), so the failures are rows.
- Nomination passes: 2 of 2 passes (1.0000); 9 of 78 scored rows fail (0.1154).
- K1 is not nominated, so no K1 share is computed.

Rows found after the pre-registration. The nomination read produced six rows that the issue #2 reports held as a RasterioIOError or with no value: 2026-10-29 tile 50HLJ ramsar-26, ramsar-27 and ramsar-28 (scored) and 2026-11-11 tile 50HLJ ramsar-14 and ramsar-15 (scored) and ramsar-16 (skipped). Their `matches_report` is blank. One of them, 2026-10-29 50HLJ ramsar-27 (abs_diff 0.0776, red + nir 0.0428, band_max 0.0030), fails K0 and is not among the eight seen failing rows. The nomination K0 failing row share is therefore 9 of 78, against the 8 failing rows the reports gave. This was found after the pre-registration and did not change any rule.

A0 to A5: not computed, K1 not nominated.

Failed: none computed. The result is not inconclusive: A0 is not evaluated without a nominated g, and the pre-registration sets the outcome to K0.

NDVI row rule: K0

Hypotheses, reported and not decision inputs:

- H1: not supported. K1 is not nominated.
- H2: not supported. On both 2026-11-11 ramsar-13 rows of the nomination sample, read against the run-day DEA item, the same-pixel gap equals abs_diff and is above 0.05 (50HLK 0.0741, 50HLJ 0.1007). The pipeline median over the compared pixels is the stored median, so the mask does not explain the gap.
- H3: supported. Over 97 confirmatory pairs of one polygon and pass on two tiles with equal `n_compared`, the median between-tile difference of `ndvi_stored` is 0.0099 and of `ndvi_dea` 0.0047, which meets both the factor of two and the 0.005 floor.
- H4: untestable. The run-day DEA items of both 2026-11-11 tiles (50HLK and 50HLJ) are still nrt. As context, the K0 failing share by DEA maturity over the confirmatory rows is 86 of 270 on final items and 1 of 22 on nrt items.

Cause, per the reading rule: H3 (tile) is the one supported hypothesis. The decision does not depend on it. H1 and H2 are not supported and H4 is untestable.

Context only, not a decision input: the rows TXT also lists the number of confirmatory passes that fail a K1 rule at each g of the grid, 8 of 8 at g = 0.002 to 0.008 and 7 of 8 at g = 0.009 and 0.010. The pre-registration does not use it when no g is nominated, and no conclusion is drawn from it.

Limits. DEA NBART is another processing of the same Sentinel-2 acquisition and is not ground truth, so this measures consistency and not accuracy. The confirmatory sample is final maturity except the 3 nrt scene-tiles (22 scored rows), while daily runs score against nrt, and the nomination 2026-11-11 rows are against nrt items. The confirmatory sample is 8 passes, which is a small number of passes. The tiles of one pass share an acquisition and are not independent, so the 292 rows are fewer independent observations than their count. The 2 nomination passes were seen, and the nomination failing rows and H2 rest on them. The earlier live check of the 0.05 tolerance was read over the live test's Thomsons Lake box (`THOMSONS_32750` in `tests/test_live_verify.py`), not over a ramsar polygon.

Status. Jarrod approved ADR 0013 on 2026-11-14, so the status quo stays. No other rule has been named for testing.

## Live run findings

### Issue #2 daily verify exit 3 (2026-11-12)

The daily verify of CI run 43072355326 (GitHub issue #2) exited 3. Reproduced at ad1fe76 on the 2026-11-11 and 2026-10-29 passes, most of the failing rows were DEA Waterbodies rows judged against limits calibrated on the ramsar layer only: 262 blocking water rows and 150 blocking NDVI rows on the waterbody layer on 2026-11-11, and 297 and 310 on 2026-10-29 (`docs/research/2026-11-12-live-check-layers.txt`). The fix was st-a32a, under ADR 0012 (`docs/decisions/0012-live-check-limits-apply-to-their-calibrated-layer.md`, approved by Jarrod on 2026-11-14): waterbody rows are advisory, and ramsar rows keep their limits.

After the layer rule, `ndvi_vs_dea_nbart` still failed 4 ramsar rows on each of the 2026-10-29 and 2026-11-11 passes (ramsar-15, ramsar-20, ramsar-21 and ramsar-27 on 2026-10-29; ramsar-13 twice, ramsar-20 and ramsar-21 on 2026-11-11), so `verify` still exited 3. st-da75 measured the row on 32 scene-tiles on 8 passes, with the pre-registered rule choosing between the status quo (K0) and a conditioning split (K1). K1 was not nominated, since no band-difference limit g was admissible on the nomination rows. K0 stays: the check fails all 8 passes and 87 of 292 scored confirmatory rows. See ADR 0013 (`docs/decisions/0013-ndvi-row-rule-against-dea-nbart.md`, not yet approved by Jarrod) and the Spike results entry 'NDVI row rule against DEA NBART (2026-11-14)'.

Rule: apply a check's limit only to the layer it was calibrated on, and measure a limit that keeps failing on its own rows before changing it.

### Catalogue footprint difference failed the Copernicus count check (2026-11-12)

The weekly verify of 2026-11-09 (run 42548248931, GitHub issue #1) failed `freshness_count_vs_copernicus` on tile 50HMK with measured 1.0. The one-sided scene was S2C_MSIL2A_20261014T020311_N0513_R017_T50HMK_20261014T062152 (Earth Search item S2C_T50HMK_20261014T021347_L2A), a swath-edge pass with 34.7 percent nodata and cloud cover 0.299 on Earth Search and 0.3 on CDSE. Both catalogues list the datatake.

`normalise_scenes` filtered each catalogue's listing by that catalogue's own item footprint against the AOI polygons. The CDSE footprint reaches further west than the Earth Search footprint (CDSE minus Earth Search is 68.8 km2) and covers 54 percent of the 0.27 ha DEA Waterbodies polygon dea-qd4xhuft4_v3, while the Earth Search footprint ends 566 m short of it. The scene was kept on the CDSE side only. The ledger rightly had no row: the Earth Search SCL is nodata on all 27 pixels of that polygon, so the pipeline had nothing to read. The check counted a comparison artefact as a missing scene.

Fix (st-9812): AOI membership is decided once per datatake. A datatake both catalogues list (in the bbox, the window and under the cloud limit) whose footprint intersects the AOI in only one of them is a footprint-edge case. It is reported under `footprint_edge` in the detail of `discovery_vs_copernicus` and `freshness_count_vs_copernicus` and is not counted as a mismatch. A datatake only one catalogue lists stays a mismatch. `freshness_count_vs_earth_search` is unchanged. The cloud-cover straddle limit in the `copernicus.py` docstring is a separate known limit. Rule: never decide scope for a cross-catalogue comparison from each catalogue's own footprint; decide it once per datatake.

### pyarrow S3 delete PUTs a directory marker (2026-11-06)

pyarrow 26.0.0 `S3FileSystem.delete_file` sends HEAD key, DELETE key, then `PUT <parent>/` with Content-Type application/x-directory, which re-creates the parent marker that writes avoid. pyarrow has no `delete_files` and no option to stop it. A botocore `delete_object` sends a single `DELETE /prefix/key`, so `OutputStore.delete` uses botocore on S3 roots (st-c667).

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

### Spearman calibration rule and reconciliation check (2026-11-06)

This is not a blind pre-registration. The rule was chosen with the whole-history rho already measured (2026-11-05), and R1 was predictable from the 2026-11-03 sensitivity numbers. Both were written down in the same change as the result.

1. Calibration rule, set by Jarrod on 2026-11-06: `spearman_min` is the lowest whole-history per-lake rho from the gate's code path (`waterbody_checks` with `history` set to every stored observation up to the newest scene) minus 0.02, rounded down to two decimals.
2. Reconciliation hypothesis R1: the legacy pairing (datetime-only de-duplication by highest `scene_coverage`, start 2022-12-01, end 2026-11-02) reproduces the H4 per-lake rho to three decimals and the H4 pair counts exactly (Forrestdale 0.870 with 93, Thomsons 0.897 with 99, Lake Clifton 0.858 with 98, Lake Preston 0.861 with 98). The result is recorded whether R1 holds or not.

### Spearman threshold calibration (2026-11-06)

Rows: [docs/research/2026-11-06-spearman-calibration.csv](docs/research/2026-11-06-spearman-calibration.csv), written by [docs/research/2026-11-06-spearman-calibration.py](docs/research/2026-11-06-spearman-calibration.py), reconciliation in [docs/research/2026-11-06-spearman-calibration.txt](docs/research/2026-11-06-spearman-calibration.txt). Decision: [docs/decisions/0007-spearman-threshold-from-whole-history.md](docs/decisions/0007-spearman-threshold-from-whole-history.md). The script ran the gate's code path (`waterbody_checks` with `history` set to every stored observation up to the newest scene, 2026-10-29T02:27:01Z) over 1147 files and 235,595,220 bytes. It is read only.

Calibration, whole-history rho and n pairs: Forrestdale 0.8608 (88), Lake Clifton 0.8555 (95), Lake Preston 0.8568 (96), Thomsons 0.8932 (93). The lowest is 0.8555, so by the calibration rule `spearman_min` is floor((0.8554980859546633 - 0.02) * 100) / 100 = 0.83, set in `config/pipeline.toml` and as the `WaterbodiesVerifyConfig` default. H4 stays not supported: no lake reached 0.9.

R1 held. The legacy pairing (datetime-only de-duplication, 2022-12-01 to 2026-11-02) reproduces the H4 rho to three decimals and the H4 pair counts exactly. Gate against H4, rho and pairs: Forrestdale 0.861 with 88 against 0.870 with 93; Lake Clifton 0.855 with 95 against 0.858 with 98; Lake Preston 0.857 with 96 against 0.861 with 98; Thomsons 0.893 with 93 against 0.897 with 99.

Cause: commit 00e8fb0 (tile and date de-duplication) landed at 2026-11-03 18:49:11 +0800, after the H4 report at fc9f4ba (18:45:32 +0800). It drops 24, 6, 6 and 12 rows (Forrestdale, Lake Clifton, Lake Preston, Thomsons) that share a tile and a calendar date, which lowers rho by 0.0088, 0.0028, 0.0038 and 0.0041 and the pair counts by 5, 3, 2 and 6. No stored row falls outside the H4 date range, and the gate and range-restricted columns agree on every lake, so the range does not contribute.

Limits: the threshold is calibrated on the same backfill it then gates. Each verify reads all 1147 files (235,595,220 bytes) and the count grows with each pass. S3 read time is unmeasured, against a 20 minute verify step timeout in `verify.yml`.
