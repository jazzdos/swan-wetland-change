# 0013 NDVI row rule against DEA NBART

Status: decided by the pre-registered rule on 2026-11-14 under Jarrod's request to complete the outstanding work; not yet approved by Jarrod.
Applies the NDVI row of the design; changes no limit.

## Context

GitHub issue #2 (CI run 43072355326) reported that `wetland-change verify`
exits 3 on the daily run. ADR 0012 (st-a32a) removed the waterbody rows from
the blocking set. After it, `ndvi_vs_dea_nbart` in
`src/wetland_change/verify/ndvi.py` still failed 4 ramsar rows on each of the
two reproduced passes, so `verify` still exits 3 on every run with scenes. This
is the second cause of issue #2.

The eight seen failing rows (from the two reports whose sha256 are in ADR 0012):

- 2026-10-29, DEA maturity final: ramsar-15, ramsar-20 and ramsar-21 on 50HLJ
  and ramsar-27 on 50HLK. The pipeline median is lower than the DEA NBART median
  by 0.0991, 0.0921, 0.1506 and 0.1134.
- 2026-11-11, DEA maturity nrt: ramsar-13 on 50HLK and 50HLJ (pipeline higher
  than DEA) and ramsar-20 and ramsar-21 on 50HLJ (pipeline lower).

The design (`docs/plans/2026-10-29-swan-wetland-change-design.md`) sets a
median absolute difference of 0.05 or less and a correlation above 0.95.
The 0.05 tolerance was checked live once, over the live test's Thomsons Lake
box (`THOMSONS_32750` in `tests/test_live_verify.py`), not over a ramsar
polygon. No exit rule had been measured for NDVI the way ADR 0008 measured one
for water.

## Pre-registration

The candidates, samples, parameter rule, reproduction gate, decision rule and
reading rule are in LEARNINGS.md under 'Pre-registered hypotheses (st-da75,
2026-11-14)'. The result is under 'NDVI row rule against DEA NBART
(2026-11-14)'.

Commits on story/st-da75: 098fb14 (pre-registration), fe0cf3c (research script
and decision tests), 47233f0 (script hardening before any live read), 3b82198
(nomination read) and cd5af57 (confirmatory read).

- K0, status quo: every scored row blocks on abs_diff at most 0.05, and the
  correlation check (r above 0.95 over at least 5 rows) is unchanged.
- K1(g), conditioning split: a row with DEA red + nir at or above S* = 40 g
  blocks on abs_diff at most 0.05. A row below S* blocks instead on
  |d_red| at most g and |d_nir| at most g against the same DEA NBART item.
  The correlation check and 0.05 are unchanged and no row becomes unscored.
- g is nominated on the nomination sample (the 8 seen scene-tiles, re-read) as
  the smallest g in 0.002 to 0.010 that meets N1 (at least 0.95 of well
  conditioned rows within 0.05), N2 (at least 0.95 of the other rows within g)
  and N3 (well conditioned rows at least half of the scored rows). With no
  admissible g, K1 is not nominated and the outcome is K0.
- K1 is adopted only if A0 to A5 all hold on the confirmatory sample (32
  scene-tiles on 8 passes).

## Decision

NDVI row rule: K0

K1 is not nominated, so A0 to A5 are not computed. `ndvi_vs_dea_nbart` is
unchanged. `verify` keeps exiting 3 when a ramsar row fails it, and st-da75 is
parked with the measured rates.

## Results

The nomination read (2026-11-14, 04:45:16 to 04:51:07 UTC, one attempt, exit 0)
scored 78 of 79 rows on 8 scene-tiles (3 final, all of 2026-10-29, and 5 nrt,
all of 2026-11-11). The reproduction gate passed: 8 of 8 seen rows reproduced
with deviation 0.0, and 65 of 65 other report rows matched. No g is admissible.
N2 fails at every g, with the share of the other rows within g at most 0.3750
(g = 0.005) against 0.95. N1 also fails at g = 0.002 and 0.003, and N3 fails
from g = 0.007.

The confirmatory read (2026-11-14, 05:03:18 to 05:25:43 UTC, one attempt,
exit 0) read 32 of 32 scene-tiles (29 final, 3 nrt) and scored 292 of 294 rows.
The 2 skipped rows are 2026-09-12 S2B_T50HLJ_20260912T022111_L2A ramsar-14
(pipeline median not finite, 0 compared pixels) and ramsar-22 (finite median,
28 compared pixels, below 100).

A0 to A5: not computed, K1 not nominated. Not inconclusive.

Failing shares of K0, the only candidate:

| sample | passes exiting 3 on the NDVI checks alone | failing scored rows |
|---|---|---|
| confirmatory | 8 of 8 (1.0000) | 87 of 292 (0.2979) |
| nomination | 2 of 2 (1.0000) | 9 of 78 (0.1154) |

The correlation check passes on every confirmatory pass (r 0.9779 to 0.9995),
so the failures are rows. By DEA maturity, 86 of 270 scored confirmatory rows
on final items fail, and 1 of 22 on nrt items.

Hypotheses, not decision inputs: H1 not supported (K1 not nominated); H2 not
supported (same-pixel gap equal to abs_diff and above 0.05 on both ramsar-13
rows: 0.0741 on 50HLK, 0.1007 on 50HLJ); H3 supported (97 pairs, median
between-tile difference 0.0099 for the pipeline and 0.0047 for DEA); H4
untestable (the run-day DEA items of both 2026-11-11 tiles are nrt).

Finding made after the pre-registration. The nomination read produced six rows
that the issue #2 reports held as a RasterioIOError or with no value:
2026-10-29 tile 50HLJ ramsar-26, ramsar-27 and ramsar-28 (scored) and
2026-11-11 tile 50HLJ ramsar-14 and ramsar-15 (scored) and ramsar-16 (skipped).
One of them, 2026-10-29 50HLJ ramsar-27 (abs_diff 0.0776), fails K0 and is not
among the eight seen failing rows. The nomination K0 failing row share is
therefore 9 of 78, against the 8 failing rows the reports gave. No rule changed.

## Cause

H3 (tile) is the one supported hypothesis: the pipeline median of one polygon
differs between overlapping tiles of a pass by more than DEA's median does. H1
and H2 are not supported and H4 is untestable. Per the reading rule, the cause
is recorded and does not change the decision.

## Rejected alternatives

- K1. Not nominated: N2 fails at every g, so the substitute band comparison
  does not hold on the rows it would take over.
- Widening 0.05, or a tolerance scaled by red + nir. Excluded by the story,
  since both widen the design's tolerance.
- A minimum pixel count above 100, or one row per polygon and pass across
  tiles. Both leave ramsar rows unscored.
- Band limits on every row. This drops the design's NDVI comparison on rows
  where it is well conditioned.
- Making `ndvi_vs_dea_nbart` advisory. Not tested by this pre-registration; see
  Consequences.

## Evidence

Source CRS of every item and DEA grid is EPSG:32750, the operation CRS is
EPSG:32750, and reflectance and NDVI are unitless. Both reads used the DBCA-010
ramsar GeoJSON whose sha256 matches the DBCA-010 row of `data/SOURCES.md`
(f946c5e8b4452042bda719751271aafac1f42ba2e70649f5c1bff1051da1d1d4). The
collection is `sentinel-2-c1-l2a`.

Files, with sha256:

- `docs/research/2026-11-12-ndvi-nbart-rows.py` sha256 `8f6c79fee8e71d047e5ab2bf92e8472c688d6e6f7fe3699982e7b48010a3f8ae`
- `docs/research/2026-11-12-ndvi-nbart-nomination.csv` sha256 `13d67e3fa8915a4d0571f2bf2c67a911800ac292899360c24a30695310cfee73`
- `docs/research/2026-11-12-ndvi-nbart-nomination.txt` sha256 `bd3c583d2ef197d06700f06e81ee017031f9fa4326d32b45a0a6fe968a512375`
- `docs/research/2026-11-12-ndvi-nbart-rows.csv` sha256 `ca8c751eb938d60e7494851239bca28fc073e5e9d58efcbe99f889a1904b65f5`
- `docs/research/2026-11-12-ndvi-nbart-rows.txt` sha256 `7c4fef6aa98b2ab093f694519b51678a79551dc1beb951462c776604eaf053ff`
- `docs/research/2026-11-12-issue-2-repro-20261029.json` sha256 `c579bed357ca58bf4ed6c1b2062accf71e3f7c626b5b174ae0712dd361f10db5`
- `docs/research/2026-11-12-issue-2-repro-20261111.json` sha256 `9b53bbd3a877fc721610b7ca5f25dcadfe431a9db0db58223da583da213ba26a`

`tests/test_config.py` checks the digests, rebuilds both text files from the
CSV files and checks that the outcome recorded here and in LEARNINGS.md is the
pre-registered rule applied to the committed rows.

## Limits

- DEA NBART is another processing of the same Sentinel-2 acquisition and is
  not ground truth. This measures consistency, not accuracy.
- The confirmatory sample is final maturity except 3 nrt scene-tiles (2026-10-27
  on 50HLK, 50JLL and 50JML; 22 scored rows), while daily runs score against
  nrt. The nomination 2026-11-11 rows are against nrt items.
- The confirmatory sample is 8 passes.
- The tiles of one pass share an acquisition and are not independent.
- The 2 nomination passes were seen, and the nomination result and H2 rest on
  them.
- The rows found after the pre-registration (Results) changed the nomination
  failing row count from 8 to 9, not any rule.

## Consequences

Nothing changes in `src/`, `config/pipeline.toml` or the README. `verify` keeps
exiting 3 whenever a ramsar row fails `ndvi_vs_dea_nbart`. On the confirmatory
sample that is every pass, and it is both reproduced passes. st-da75 is parked with the measured rates, and the
question for Jarrod is whether to keep the status quo, make
`ndvi_vs_dea_nbart` advisory pending a new pre-registered spike, or name
another rule to test. This ADR is not approved until Jarrod approves it.

## Disclosure

From the pre-registration:

- (a) The eight seen failing rows come from the two issue #2 reports, written
  by `wetland-change verify` at commit ad1fe76.
- (b) The other 65 scored ramsar rows of those reports and the waterbody rows
  had been seen. The two passes are the nomination sample and did not decide.
- (c) The Thomsons Lake value on the 2026-10-29 50HLK pass (0.4749 against
  0.4715) had been seen. It was read over the live test's box, not over a
  ramsar polygon. The box contains ramsar-50, ramsar-51 and 99.9% of
  ramsar-52 by area.
- (d) The ramsar-12 WO wet-area gap had been measured on five of the
  confirmatory dates. Pipeline NDVI medians for ramsar-52 and ramsar-56 on the
  confirmatory passes were readable in
  `docs/research/2026-11-03-backfill-scores.csv`, as was `ndvi_stored` for
  processed confirmatory scene-tiles. No DEA NBART value, abs_diff or band
  value of any confirmatory pass had been seen.
- (e) The planner ran `discover` over the 27 ramsar polygons to fix the
  confirmatory ids (metadata only) and read DEA item metadata for maturity.
- (f) The working explanation in H1 (NDVI is ill-conditioned at low
  reflectance) was formed after the eight rows were seen.
- (g) DEA NBART is not ground truth.

After the pre-registration, the nomination read found the six rows described
under Results, one of which fails K0.
