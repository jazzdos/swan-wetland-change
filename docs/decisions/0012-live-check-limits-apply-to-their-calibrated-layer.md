# 0012 Live check limits apply to the layer they were calibrated on

Status: decided by the orchestrator on 2026-11-12; approved by Jarrod on 2026-11-14.
Amends the Decision of 0008 (pooled population) and the NDVI row of the
design (correlation population).

## Context

Since st-c6d5, `wetland-change verify` is given 27 ramsar polygons (polygon_id
`ramsar-<n>`) and 1,404 DEA Waterbodies polygons (polygon_id `dea-<uid>`). It
scores the live per-polygon checks `water_vs_dea_s2_wo` and
`ndvi_vs_dea_nbart` on all of them. Every limit those checks use was
calibrated on the ramsar layer only:

- Water agreement: 0.91 by default and the per-polygon overrides (0.94, 0.92
  and 0.95), from ADR 0005 and ADR 0010.
- Wet area clause: absolute gap of 5.0 pp or less, ADR 0006.
- Exit rule: a row that fails only the clause is a `warn`, and the run fails
  on the pooled gap, ADR 0008.
- NDVI median absolute difference of 0.05 or less and a correlation above
  0.95 over the run, from the design
  (`docs/plans/2026-10-29-swan-wetland-change-design.md`).

Issue #2 (CI run 43072355326) reported that `verify` fails on the daily run.
The failing rows are mostly on the waterbody layer, which no limit was
calibrated on. AGENTS.md makes DEA Waterbodies polygons the verification unit
for the history checks. This ADR does not change that.

## Decision

Ramsar rows stay blocking exactly as before, including the per-polygon
overrides and the ADR 0008 warn rule. Their detail gains `layer`: `ramsar`.

Rows on any other layer (today `dea_waterbody`) are measured and stored as
before, with `layer`, `advisory: true` and `within_ramsar_limit` in the
detail. `within_ramsar_limit` is the verdict the row would have had on the
ramsar limits. An advisory row:

- holds no verdict (`passed` is null);
- never changes `all_passed`, the matrix counts or the exit code;
- prints no per-row line in the CLI or the markdown report.

Each live check gets one advisory summary per non-ramsar layer, in three
places: the JSON report (`advisory`, with `n_advisory` in the totals), the
markdown report (`## Advisory`) and the CLI (one `advisory` line per summary).
A summary gives the rows scored, the rows skipped and the rows outside the
ramsar limit. For water it adds the pooled agreement and the pooled wet gap.
For NDVI it adds the median absolute difference.

The pooled wet area check `water_vs_dea_s2_wo_pooled_wet_area` and the check
`ndvi_correlation_vs_dea_nbart` use ramsar rows only and name the layer and the
row count in their detail. Scene-level rows without a polygon keep their
verdict. The history checks are unchanged. No limit is loosened.

Implementation: `src/wetland_change/verify/layers.py` (the rule and the
summaries), `src/wetland_change/verify/checks.py` (`Check.advisory`, the report
keys and the markdown table), `src/wetland_change/verify/wo.py` (the pooled
check takes a layer), `src/wetland_change/verify/matrix.py` (`n_advisory`),
`src/wetland_change/verify/run.py` (the rule is applied after the scene loop)
and `src/wetland_change/cli.py` (the `advisory` lines; exit codes come from the
verdict rows). The tests are `tests/test_verify_layer_rule.py` and
`tests/test_verify_layer_rule_run.py`.

## Rejected alternatives

- Keep waterbody rows blocking at the ramsar limits. Both reproductions fail on
  the waterbody layer alone: 262 blocking water rows and 150 NDVI rows on
  2026-11-11, 297 and 310 on 2026-10-29. The run could not go green on a layer
  whose limits nobody calibrated.
- Drop waterbody rows from the live checks. This loses the measurements a later
  waterbody floor needs (st-dd0d).
- Loosen the limits or set a waterbody floor now. There is no pre-registered
  calibration, and the floor is out of scope here (st-dd0d).
- A minimum-size floor for the waterbody layer. The share of scored rows that
  fail agreement stays between 0.40 and 0.50 for every bin from 100 to 9,999
  mutually clear pixels on both dates (size bins below), so a floor of 100 to
  2,000 pixels does not remove the failures. It falls only in the 10,000+ bin
  (0.33 and 0.15), which holds 21 and 26 rows.
- Keep pooling every layer. On 2026-11-11 the waterbody pooled wet gap is +5.51
  pp against +3.70 pp for ramsar. On 2026-10-29 the correlation over all rows is
  0.9480 and fails the 0.95 limit, while the ramsar rows give 0.9983.
- Mark waterbody failures as `warn`. Warn rows count in the matrix and print one
  line each, which is 262 and 150 more lines on 2026-11-11 and 297 and 310 more
  on 2026-10-29, and `warn` implies a calibrated limit.

## Evidence

Source CRS of every item in both reports is EPSG:32750 (UTM zone 50S), and the
operation CRS is EPSG:32750. Agreement and wet shares are fractions, wet gaps
are percentage points and NDVI differences are unitless.

The reports pre-date this rule. They were made at git ad1fe76 with:

- `wetland-change backfill --start 2026-11-11 --end 2026-11-11 --output-root <root>`
  then `wetland-change verify --output-root <root> --run-id 20261112T032325Z`;
- `wetland-change backfill --start 2026-10-29 --end 2026-10-29 --output-root <root>`
  then `wetland-change verify --output-root <root> --run-id 20261112T032444Z`.

The per-layer counts below are from `docs/research/2026-11-12-live-check-layers.csv`
and `.txt`. Rows are every row of the check on that layer, so skipped rows are
included. Each row is scored under the ramsar limits.

Water, `water_vs_dea_s2_wo`:

| date | layer | pass | fail | warn | skipped | pooled agreement | pooled wet gap (pp) |
|---|---|---|---|---|---|---|---|
| 2026-11-11 | ramsar | 34 | 1 | 5 | 5 | 0.9616 | +3.70 |
| 2026-11-11 | dea_waterbody | 290 | 262 | 47 | 1172 | 0.9054 | +5.51 |
| 2026-11-11 | all | 324 | 263 | 52 | 1177 | 0.9421 | +4.33 |
| 2026-10-29 | ramsar | 30 | 0 | 2 | 2 | 0.9878 | +0.98 |
| 2026-10-29 | dea_waterbody | 323 | 297 | 33 | 919 | 0.9237 | -2.21 |
| 2026-10-29 | all | 353 | 297 | 35 | 921 | 0.9579 | -0.51 |

NDVI, `ndvi_vs_dea_nbart`:

| date | layer | pass | fail | skipped | Pearson r | median absolute difference |
|---|---|---|---|---|---|---|
| 2026-11-11 | ramsar | 38 | 4 | 3 | 0.9921 | 0.0125 |
| 2026-11-11 | dea_waterbody | 468 | 150 | 1153 | 0.9914 | 0.0297 |
| 2026-11-11 | all | 506 | 154 | 1156 | 0.9917 | 0.0289 |
| 2026-10-29 | ramsar | 27 | 4 | 3 | 0.9983 | 0.0271 |
| 2026-10-29 | dea_waterbody | 395 | 310 | 867 | 0.9456 | 0.0400 |
| 2026-10-29 | all | 422 | 314 | 870 | 0.9480 | 0.0384 |

Water on the waterbody layer by mutually clear pixels, scored rows only:

| date | pixels | rows | pass | fail | warn | pooled agreement | pooled wet gap (pp) |
|---|---|---|---|---|---|---|---|
| 2026-11-11 | 100-199 | 246 | 122 | 106 | 18 | 0.8810 | +6.53 |
| 2026-11-11 | 200-499 | 157 | 72 | 71 | 14 | 0.8727 | +4.48 |
| 2026-11-11 | 500-1999 | 135 | 64 | 62 | 9 | 0.8680 | +0.95 |
| 2026-11-11 | 2000-9999 | 40 | 19 | 16 | 5 | 0.9078 | +1.47 |
| 2026-11-11 | 10000+ | 21 | 13 | 7 | 1 | 0.9137 | +7.21 |
| 2026-10-29 | 100-199 | 236 | 107 | 119 | 10 | 0.8687 | -0.12 |
| 2026-10-29 | 200-499 | 166 | 76 | 80 | 10 | 0.8732 | -4.36 |
| 2026-10-29 | 500-1999 | 165 | 86 | 70 | 9 | 0.8761 | -6.55 |
| 2026-10-29 | 2000-9999 | 60 | 33 | 24 | 3 | 0.8400 | -11.41 |
| 2026-10-29 | 10000+ | 26 | 21 | 4 | 1 | 0.9558 | +0.78 |

Outcome under each rule, from `docs/research/2026-11-12-live-check-layers.txt`:

| date | rule | blocking water rows | blocking NDVI rows | pooled wet gap (pp) | NDVI correlation | exits 3 |
|---|---|---|---|---|---|---|
| 2026-11-11 | every layer | 263 | 154 | +4.3278 over 639 rows, pass | 0.991684 over 660 rows, pass | yes |
| 2026-11-11 | this ADR | 1 (ramsar-21) | 4 (ramsar-13 twice, ramsar-20, ramsar-21) | +3.7012 over 40 rows, pass | 0.992071 over 42 rows, pass | yes |
| 2026-10-29 | every layer | 297 | 314 | -0.5103 over 685 rows, pass | 0.947954 over 736 rows, fail | yes |
| 2026-10-29 | this ADR | 0 | 4 (ramsar-15, ramsar-20, ramsar-21, ramsar-27) | +0.9830 over 32 rows, pass | 0.998334 over 31 rows, pass | yes |

`tests/test_config.py` checks the digests, recomputes the counts from the two
reports and compares them with the committed CSV and text.

Files, with sha256:

- `docs/research/2026-11-12-live-check-layers.py` sha256 `5c2d9f343909bcd8e1a6c5ac979ec0187fe1e84d39a49ffcd6f8de9917b8b688`
- `docs/research/2026-11-12-live-check-layers.csv` sha256 `e9430d3343c4684640aa98a2532bf91cdb51d37182346c4d033110ae60c8a2bf`
- `docs/research/2026-11-12-live-check-layers.txt` sha256 `63f999eb9fec91b5ce09e014198fa5ee49f5b9f95fe481f94607ce7ea71dd9a1`
- `docs/research/2026-11-12-issue-2-repro-20261111.json` sha256 `9b53bbd3a877fc721610b7ca5f25dcadfe431a9db0db58223da583da213ba26a`
- `docs/research/2026-11-12-issue-2-repro-20261029.json` sha256 `c579bed357ca58bf4ed6c1b2062accf71e3f7c626b5b174ae0712dd361f10db5`

## Limits

- Both reproduced runs still exit 3 under the rule. On 2026-11-11 the blocking
  rows are ramsar-21 on water agreement (0.8539) and four ramsar NDVI rows. On
  2026-10-29 they are four ramsar NDVI rows. The NDVI rows are st-da75 (NDVI on
  dark ramsar polygons) and the ramsar-21 water row is st-b6bf. This ADR does
  not address either.
- The advisory summaries are not a verification of the waterbody layer. They
  record what the ramsar limits would have said, and no limit was calibrated on
  that layer.
- Two dates, one season. The waterbody pooled wet gap changes sign between
  them (+5.51 pp and -2.21 pp), so neither date supports a waterbody limit.

## Consequences

JSON readers find waterbody rows with `passed` null, `advisory` true and
`within_ramsar_limit`, plus an `advisory` list with one summary per live check
and layer, and `n_advisory` in the totals. The markdown report has an
`## Advisory` table and lists no waterbody row elsewhere. The CLI prints one
`advisory` line per summary and no line per waterbody row. The exit code and
`all_passed` depend on ramsar rows, scene-level rows and the history checks
only. A later waterbody floor (st-dd0d) can be calibrated from the stored
advisory rows and would supersede this ADR for that layer.
