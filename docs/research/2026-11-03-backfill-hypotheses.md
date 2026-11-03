# Collection 1 backfill: hypotheses 1 to 4 (2026-11-03)

Story st-b983. The hypotheses and verdict rules were recorded in `LEARNINGS.md` before the backfill ran (section "Pre-registered hypotheses (st-b983, 2026-11-02)") and implemented in `docs/research/2026-11-02-backfill-analysis.py`. No threshold was changed after the run. Every number below comes from `docs/research/2026-11-03-backfill-evidence.json`, the state files under `/Users/jarrodbaker/Documents/swan-wetland-change-data/state`, or the ledger parts read read-only, and the evidence JSON reports `self_check.matched` true (rescored flags equal the change files).

## 1. Summary

| Hypothesis | Verdict | Basis |
| --- | --- | --- |
| H1, Forrestdale low water, 2023-12-01 to 2024-01-31 | supported | 2 low flags in 3 scored dates; lowest z -8.87 on 2023-12-17 |
| H2, Forrestdale no anomaly, 2023-02-01 to 2023-04-30 | untestable | 0 of 12 dates scored; all 12 are `too_few_samples` |
| H3, winter water at or above baseline, 2025-06-01 to 2025-08-31 | not supported | ramsar-56 median delta -14.38 ha with a low flag; ramsar-52 has no scored date |
| H4, agreement with DEA Waterbodies | not supported | all 4 scored lakes have rho below 0.9 (0.858 to 0.897) |

The 2022 half of H2 is untestable for a separate reason given in section 5.

## 2. Run

- Range: 2022-12-01 to 2026-11-02 (`end_date`). Collection `sentinel-2-c1-l2a`, cloud cover under 20 percent.
- Items processed: 1147 (`processed_sum`). Items failed in their final state: 0. Items rejected: 0 (`rejected_sum` 0, `rejected_count` 0). 25 items failed once and succeeded on a later attempt (section 3).
- Backfill calls: 35 chunk calls in `progress.log`, plus a final score step. No `GAVE_UP` line appears in `progress.log`. The sweep ran 17 chunks, all rc=0, and the score step returned rc=0.
- Wall time, first `driver start` (2026-11-02T13:23:04Z) to `DONE` (2026-11-03T10:27:03Z): 75839 s, 21 h 04 m. No relaunch occurred: `relaunches.txt` does not exist and `progress.log` holds one `driver start` line.
- Sleep gap inside that wall time: pmset recorded a Clamshell Sleep on battery at 13:12:15 AWST on 2026-11-03 and a wake at 17:27:52 AWST, 15337 s (4 h 16 m). Wall time less that gap: 60502 s, 16 h 48 m.
- The gap fell in lane 0's last chunk, 2026-10-01..2026-11-02. Pass 1 logged rc=2 secs=15612 and failed 25 of 26 scenes (section 3). Pass 2 logged rc=0 secs=3189.
- Output size: `du -sh` on the output root reports 274M. The last disk projection (10:22:42Z, 1172 ledger parts) was 240952 KiB total for 1147 items; the 17 projections ranged from 240952 to 251922 KiB. Free space ranged from 23585592 KiB (22.5 GiB) at the last projection to 27120040 KiB (25.9 GiB). No disk stop occurred.
- Three lanes: the driver splits the 17 chunks (quarters from 2022-12 to 2026-11) over `LANES=3` backfill processes so that Earth Search reads overlap. Each lane takes run ids from seconds congruent to its lane number so that no two runs share an id.

## 3. Coverage

| Quantity | Value |
| --- | --- |
| Reference count (fresh search at 2026-11-03T10:30:55Z: scenes plus rejected) | 1147 |
| Raw search count | 1310 |
| Dropped by `discover` (`skipped_filter`) | 163 |
| Items in the ledger in their latest state | 1147 |
| Coverage against the reference (`ledger.coverage`) | 1.0 (1147 of 1147) |
| Raw coverage (`ledger.raw_coverage`) | 0.8756 (1147 of 1310) |
| Missing from the ledger | 0 |
| In the ledger but not in the reference | 0 |

Items whose footprint misses every polygon are dropped by `discover` and cannot enter the ledger under any configuration, so the reference is scenes plus rejected. The 163 dropped items are the difference between the raw count and the reference (1310 minus 1147). The 95 percent coverage criterion is read against the 1147 reference. Against the raw count the figure is 87.6 percent, and the reviewer should confirm which reading applies.

Failed items. The ledger holds 1172 parts: 1147 succeeded and 25 failed. The 25 failed parts are for 25 distinct items (observation dates 2026-10-02 to 2026-10-29), each with `attempts` 1, all written in the chunk 2026-10-01..2026-11-02 pass 1. 24 errors are `RasterioIOError: CURL error: Could not resolve host` for the Earth Search data bucket, the host-resolution failure that followed the sleep. 1 error is `RasterioIOError: Read failed. See previous exception for details.` All 25 items have a later succeeded part (25 of 25 overlap, 0 without one), written in pass 2.

So 25 items failed at some attempt and 0 are failed in their final state. `ledger.by_status` is `{succeeded: 1147}` and `ledger.failed` is empty because the script reads the latest part per item, so the superseded failed attempts are not counted as failed. They appear only as `runs.failed_attempts_sum` 25 and in the 25 extra parts (1172 minus 1147). `ledger.exhausted` is 0.

## 4. Differences from the story's estimate

- Items. The estimate was 996 items (S4, since 2022-01-01, six tiles). The measured reference is 1147, 151 more (15.2 percent). Since st-c6d5, `_load` in `src/wetland_change/cli.py` loads all 1404 DEA Waterbodies polygons beside the Ramsar polygons, so more footprints are searched. By tile, the ledger holds 50HLJ 145, 50HLK 171, 50HMJ 293, 50HMK 175, 50JLL 176 and 50JML 187, against 145, 169, 149, 173, 175 and 185 in S4. The difference sits almost entirely in 50HMJ (293 against 149). The run starts 2022-12-01 where the estimate started 2022-01-01.
- Time per scene. The estimate was 25 s per scene. `runs.backfill_seconds_sum` is 174651 s over 35 calls, and `runs.seconds_per_processed_scene` as the script computes it is 152.3 s (174651 / 1147). Recomputed without the 15612 s pass-1 call that failed on the sleep, the sum is 159039 s and the sleep-excluded figure is 138.7 s per scene. The sum is across three lanes, so it is runner time, not elapsed time. Elapsed time per scene is 66.1 s (75839 s / 1147) and 52.7 s with the sleep gap removed (60502 s / 1147). The estimate is 25 s against 152.3 s and against the sleep-excluded 138.7 s.
- Total time. The estimate was 7 h. The measured wall time is 21 h 04 m (75839 s), or 16 h 48 m less the sleep gap (60502 s).

## 5. Hypotheses

Rules are those pre-registered in `LEARNINGS.md`. A date is scored when `reason` is null and `z` is not null. A low flag is `flagged` true with `z` below zero. Metric is `water_ha_index` (ha), UTC dates, baseline of the same polygon and month on strictly earlier dates. Thresholds: |z| above 3, valid fraction above 0.8, at least 5 baseline samples. Forrestdale is `ramsar-56` (DEA `qd63n1ww5_v3`), Thomsons is `ramsar-52` (DEA `qd635epws_v3`).

### H1, Forrestdale low water, 2023-12-01 to 2024-01-31

Rule: supported if at least one low flag; not supported if a date is scored and none is a low flag; untestable if no date is scored.

Verdict: supported. 11 dates, 3 scored, 2 low flags. Reasons for the 8 unscored dates: `zero_mad` 5, `too_few_samples` 2, `low_valid_fraction` 1.

| Date | Value (ha) | z | Baseline median (ha) | Baseline MAD (ha) | n |
| --- | --- | --- | --- | --- | --- |
| 2023-12-17 | 0.0 | -8.865 | 95.29 | 10.749 | 5 |
| 2023-12-22 | 0.0 | -5.160 | 88.595 | 17.169 | 6 |

The lowest z is -8.865 on 2023-12-17. The third scored date, 2023-12-27, has value 0.0, baseline median 81.90 ha, MAD 30.60 ha, n 7 and z -2.676, so it is not flagged. All 11 dates in the window have `water_ha_index` 0.0; the 5 dates from 2024-01-06 to 2024-01-31 are unscored because the baseline MAD is 0.

DEA Waterbodies wet fraction for `qd63n1ww5_v3` in the window: 5 passes (2023-12-12, 2023-12-28, 2024-01-06, 2024-01-22, 2024-01-29), all 0.0.

### H2, Forrestdale no anomaly, 2023-02-01 to 2023-04-30

Rule: supported if at least one date is scored and no `water_ha_index` row is flagged with either sign; not supported if any is flagged; untestable if no date is scored. NDVI flags are reported separately and do not affect the verdict.

Verdict for 2023: untestable. 12 dates, 0 scored. Count per reason: `too_few_samples` 12. NDVI flags: 0.

The 2022 half is untestable: Earth Search Collection 1 has no items covering Forrestdale for February to April 2022 under the 20 percent cloud filter. `c1_items_feb_apr_2022` is 0 (scoped to ramsar-56). An unfiltered search finds 2 items, both on 2022-03-22 and both excluded by the filter: `S2A_T50HLK_20220322T022405_L2A` at 39.8 percent cloud and `S2A_T50HMK_20220322T022405_L2A` at 68.6 percent cloud. A 50JLL item exists for this period but misses Forrestdale.

Descriptive retrospective z (not a verdict, and not the ADR 0004 baseline): each of the 12 dates against same-month observations from all years other than 2023. Every z is null because the comparison median is 0.0 and the MAD is 0.0. Values are 0.0 on 11 dates and 0.21 ha on 2023-04-11. Comparison n is 10 for February dates (2023-02-05, 02-10, 02-20, 02-25), 17 for March dates (2023-03-07, 03-12, 03-17, 03-22, 03-27) and 11 for April dates (2023-04-06, 04-11, 04-21).

### H3, winter water at or above baseline, 2025-06-01 to 2025-08-31

Rule: a polygon meets the rule if the median of `value - baseline_median` over its scored dates is at least 0 and it has no low flag. Supported if both polygons meet it; not supported if either has scored dates and fails; untestable if a polygon has no scored date and the other does not fail.

Verdict: not supported. 13 dates, 1 scored. Reasons across both polygons: `too_few_samples` 9, `low_valid_fraction` 3.

| Polygon | Dates | Scored | Median delta (ha) | Share of scored dates at or above baseline | Low flags | Meets rule |
| --- | --- | --- | --- | --- | --- | --- |
| ramsar-56 | 8 | 1 | -14.38 | 0.0 | 1 | no |
| ramsar-52 | 5 | 0 | none | none | 0 | no |

ramsar-56 reasons: `too_few_samples` 4, `low_valid_fraction` 3. The one low flag is 2025-08-23: value 78.11 ha, baseline median 92.49 ha, MAD 4.240 ha, n 5, z -3.391. Monthly detail for ramsar-56: 2025-07 has 5 dates and 0 scored (median delta none); 2025-08 has 3 dates and 1 scored (median delta -14.38 ha). The low-valid-fraction date 2025-08-15 (valid fraction 0.363) has an unscored z of -15.345 against the same baseline.

ramsar-52 reasons: `too_few_samples` 5. Monthly detail: 2025-07 has 3 dates and 0 scored; 2025-08 has 2 dates and 0 scored. The window holds no June dates for either polygon.

The verdict follows from ramsar-56 alone, which has a scored date and fails; ramsar-52 has no scored date and so neither meets nor fails the rule.

### H4, agreement with DEA Waterbodies, 2022-12-01 to 2026-11-02

Rule: per lake, check `water_spearman_vs_dea_waterbodies` (passes within 3 days, at least 10 pairs). Supported if at least one lake is scored and every scored lake has rho at least 0.9; not supported if any scored lake has rho below 0.9; untestable if no lake is scored.

Verdict: not supported. 4 of 4 lakes scored, none reaches 0.9.

| Lake | rho | n_pairs | n_unpaired | Per-pass pass | Per-pass fail | Per-pass skip | Median absolute difference (pp) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Forrestdale Lake | 0.8695 | 93 | 137 | 84 | 9 | 116 | 0.151 |
| Thomsons Lake | 0.8973 | 99 | 66 | 87 | 12 | 6 | 0.807 |
| Lake Clifton | 0.8583 | 98 | 40 | 45 | 53 | 7 | 11.625 |
| Lake Preston | 0.8606 | 98 | 38 | 95 | 3 | 9 | 6.625 |

`n_unpaired` counts pipeline rows with no DEA row within 3 days. A per-pass skip is a paired row left out of the check and the correlation, which `verify/waterbodies.py` documents as a valid fraction below the minimum, a non-finite `water_ha_index`, or a scene coverage below full. The median absolute difference is over the pass and fail rows (not skips), in percentage points of wet fraction.

Pairing and duplicate rows. The check keeps one row per `datetime` (the highest `scene_coverage`), but that step does not fire here: Forrestdale has 346 rows and 346 distinct datetimes. Different tiles of one datatake carry different `datetime` values in these observations, so they are not merged. Consequences for Forrestdale:

- Its 137 unpaired rows include 67 partial-tile 50HMK rows (the rest are 50HLK).
- 108 of its 116 skips are scene-coverage skips (all 50HMK); the other 8 are valid-fraction skips.
- Every lake's `n_pairs` includes rows that share a tile and a calendar date: 12 rows for Thomsons, 10 for Forrestdale, 6 for Lake Clifton and 4 for Lake Preston. These rows can pair with the same DEA row, so the pairs are not fully independent.

Sensitivity, descriptive only and not a rule or a verdict: keeping one row per tile and date (highest `valid_fraction`, then latest item) gives rho 0.8932 for Thomsons (n 93), 0.8608 for Forrestdale (n 88), 0.8555 for Lake Clifton (n 95) and 0.8568 for Lake Preston (n 96). No lake reaches 0.9, so the verdict is unchanged. The registered numbers in the table above stand.

The `_lake_checks` function in `src/wetland_change/verify/waterbodies.py` deduplicates on `datetime` alone, not on tile and date. This is outside this story and is filed as story st-e2ae.

## 6. Reproducibility

- Source CRS: UTM zone 50S, EPSG:32750 for these tiles (50HLJ, 50HLK, 50HMJ, 50HMK, 50JLL, 50JML). Operation CRS: EPSG:32750. Geometry CRS in observations: EPSG:4326.
- Units: `water_ha_index` in hectares; `ndvi_median` and z unitless; DEA wet fraction as a fraction of the polygon; per-pass differences in percentage points.
- Config sha256: `9ce8408cb8c554248cd8a8c03a6531405c56fe26b9ca899607625a13b340134f`. Git head at launch and analysis: `114459b6b5cfa507f853574e62b8ddec0da6d223`.
- AOI hashes (`aoi_sha256.txt`; copies are in `/Users/jarrodbaker/Documents/swan-wetland-change-data/aoi`):
  - `dbca_010_ramsar_sites.geojson`: `f946c5e8b4452042bda719751271aafac1f42ba2e70649f5c1bff1051da1d1d4`
  - `dea_waterbodies_v3_swan.geojson`: `c395428f814aa6bc2ff6c415f0a6ffe23f37b95c023c5c62f13346d940ed720c`
- The DEA hash differs from the `data/SOURCES.md` value on this branch (`f89e7b98e6f03ab9ae8bca3f29f14c5deda92db71f98554ebba8b4dee6be39df`). The difference comes from the WFS top-level `timeStamp` field only. A content comparison found 1404 features with identical geometry and properties in the same order. Story st-56b8 addresses it.
- Pre-registration (`state/preregistration.txt`), written before the driver started (launch 2026-11-02T13:23:04Z, head `114459b`):
  - analysis script sha256 `325d017f20297477e6993293303b57370d230317f790f3828bd6d636d906a59e`
  - LEARNINGS pre-registration section sha256 `1580c89b7a4210e389a6c4711753367122869740de12a89ff5a9956040817b18`
  - frozen driver `driver-launched.sh` sha256 `cc2e240f30790655d337c80d58e1f666c6d3a316c3742ee5dfcc8039877b71a3`

  All three hashes were recomputed on 2026-11-03 before the analysis and match. `diff` of `driver-launched.sh` against `docs/research/2026-11-02-backfill-driver.sh` shows no difference. The run used the frozen copy `driver-launched.sh`.
- Analysis script: `docs/research/2026-11-02-backfill-analysis.py`. Driver: `docs/research/2026-11-02-backfill-driver.sh` (identical to the frozen `driver-launched.sh` that ran). Outputs: `docs/research/2026-11-03-backfill-changes.csv` (69 rows: ramsar-56 32, ramsar-52 37), `docs/research/2026-11-03-backfill-scores.csv` and `docs/research/2026-11-03-backfill-evidence.json`.
- Licences: Ramsar sites (DBCA-010) CC BY-SA 4.0; DEA Waterbodies CC BY 4.0.
