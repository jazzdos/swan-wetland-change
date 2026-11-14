---
id: st-da75
title: Measure why Ramsar NDVI rows miss the DEA NBART tolerance and decide the row rule
type: spike
priority: P1
complexity: hard
depends_on: []
discovered_from: st-a32a
touches: [LEARNINGS.md, README.md, data/SOURCES.md, docs/decisions/0013-ndvi-row-rule-against-dea-nbart.md, docs/research/2026-11-12-ndvi-nbart-nomination.csv, docs/research/2026-11-12-ndvi-nbart-nomination.txt, docs/research/2026-11-12-ndvi-nbart-rows.csv, docs/research/2026-11-12-ndvi-nbart-rows.py, docs/research/2026-11-12-ndvi-nbart-rows.txt, tests/test_config.py, tests/test_ndvi_rows_decision.py]
exclusive: false
created: 2026-11-12
updated: 2026-11-14
parked_complexity: hard
---

## Description

GitHub issue #2, second cause. After st-a32a limits the live verdict to the ramsar layer, the per-polygon check ndvi_vs_dea_nbart (pipeline NDVI median within 0.05 of the DEA NBART NDVI median) still fails 4 ramsar rows on each of the two passes measured, so verify still exits 3 on every run with scenes.

Rows seen (disclose all eight in the pre-registration). Evidence files are in /Users/jarrodbaker/Documents/swan-wetland-change/scratch/issue-2-repro/ (untracked, absolute path; sha256 in st-a32a and ADR 0012).
- 2026-10-29, DEA maturity final, 31 ramsar rows scored, 4 fail, Pearson 0.9983: ramsar-15 on 50HLJ 0.115 against 0.214 (6,742 px); ramsar-20 on 50HLJ -0.670 against -0.578 (1,942 px); ramsar-21 on 50HLJ -0.808 against -0.657 (5,976 px); ramsar-27 on 50HLK -0.545 against -0.431 (641,110 px). The pipeline is lower than DEA on all four.
- 2026-11-11, DEA maturity nrt, 42 ramsar rows scored, 4 fail, Pearson 0.9921: ramsar-13 on 50HLK 0.422 against 0.348 and on 50HLJ 0.449 against 0.348 (228 px each; the two tiles' stored medians differ by 0.027 for the same polygon and day); ramsar-20 on 50HLJ -0.226 against -0.156 (1,732 px); ramsar-21 on 50HLJ -0.052 against 0.007 (3,756 px).
- On the 2026-10-29 waterbody rows the largest polygons fail most (21 of 31 at 10,000 px and over, median absolute difference 0.141) and the failing rows have a median pipeline NDVI of +0.021 against +0.134 for DEA.

What is known about the tolerance. The 0.05 figure comes from the design matrix (line 228). It was checked live on one polygon only: Thomsons Lake on 2026-10-30 (difference about 0.003) and on 2026-11-06 (0.4749 against 0.4715 on 63,600 px). No exit rule was ever measured for NDVI the way ADR 0008 did for water.

Working explanation, to be tested and not assumed. NDVI is ill-conditioned at low reflectance: for a per-band reflectance difference e the worst-case NDVI change is 2e / (red + nir), so over open water, where red + nir is a few percent, a difference of 0.005 between the ESA Sen2Cor reflectance and the DEA NBART reflectance moves NDVI by more than 0.05 with correct pipeline arithmetic. Six of the eight failing rows have negative or near-zero NDVI. The two ramsar-13 rows do not fit: bright vegetation, 228 px, seen only against an nrt reference. Mask differences between the stored pipeline median and the compared pixels are a second candidate for ramsar-13.

What this story produces. A measured answer and a decided rule, in the pattern of st-7047 and st-2a78: (1) a pre-registration section in LEARNINGS.md written before the script exists, with the disclosure above, hypotheses on the mechanism, the candidate row rules, numeric adoption criteria and the reading rule; (2) one research script under docs/research that re-reads red and nir for the pipeline and for DEA NBART with the same window, masks and scaling as ndvi_scene_check, checks first that it reproduces the eight seen rows, and records per row the two NDVI medians, the per-band reflectance medians of both sources, red + nir, pixel count, DEA maturity and tile; (3) results in LEARNINGS.md 'Spike results'; (4) ADR 0013 with the outcome, status decided by the pre-registered rule under Jarrod's request to complete the outstanding work and not yet approved by Jarrod; (5) if a rule is adopted, a follow-up story for the code change filed with story create --discovered-from this story, depending on st-a32a. No file under src changes in this story.

Samples. Nomination sample: the two seen passes, used only to fix the parameters of the candidates. Confirmatory sample: ramsar rows of passes never scored against DEA NBART, namely the passes of 2026-09-12, 2026-09-17, 2026-10-02, 2026-10-12 and 2026-10-27 and, for season cover, the newest pass with cloud cover at most 20 in each of January, April and July 2026 taken from the pipeline's own discover. The sample is fixed before any read and not widened afterwards. The script runs once on the confirmatory sample. Dropped rows are listed, not substituted.

Constraints on every candidate rule, fixed here and not open to the planner:
- No ramsar row becomes unscored. A row taken out of the 0.05 NDVI comparison must be scored by another blocking comparison against the same DEA NBART item, for example per-band reflectance medians within a fixed absolute limit.
- The 0.05 tolerance and the 0.95 correlation limit keep their values wherever the rule keeps the NDVI comparison. Widening 0.05 is not a candidate.
- Every parameter is fixed from the nomination sample before the confirmatory sample is read.
- The adoption criteria are numeric and say what share of well-conditioned rows must pass 0.05 and what share of failing rows the mechanism must explain. If they are not met, no rule is adopted, the status quo stays, and the story is parked with the measured rates.
- The status quo (every failing row fails the run) is always one of the candidates and its failing share of measured passes is reported next to the others.
- DEA maturity is recorded per row. nrt references cannot be re-read for old passes, so the result states that the confirmatory sample is final maturity and that daily runs score against nrt, and it re-scores the 2026-11-11 rows against whatever maturity DEA holds on the day the script runs.
- DEA NBART is another processing of the same Sentinel-2 acquisition and is not ground truth. The result measures consistency, as ADR 0005 says of WO.

This story also adds the LEARNINGS.md 'Live run findings' entry for issue #2 (the layer finding of st-a32a with a pointer to ADR 0012, and the NDVI finding), because st-a32a does not edit LEARNINGS.md.

Every dataset first used here gets its data/SOURCES.md row in the same commit. Only collection sentinel-2-c1-l2a. Reflectance from raster:bands scale and offset, never a constant.

## Acceptance Criteria

- [ ] LEARNINGS.md holds a pre-registration section for this story committed before the research script: disclosure of the eight seen rows and the mechanism hypotheses and the candidate row rules and numeric adoption criteria and the fixed confirmatory sample
- [ ] The research script reproduces the eight seen rows before it reads the confirmatory sample and stops with a recorded message if it cannot
- [ ] docs/research holds the script and its CSV and text summary with one row per polygon and scene giving both NDVI medians and the per-band reflectance medians of both sources and red plus nir and pixel count and DEA maturity
- [ ] The confirmatory sample holds the five named 2026 passes and one pass from each of January and April and July 2026 and every dropped row is listed with its reason
- [ ] Every candidate rule keeps each ramsar row under a blocking comparison against DEA NBART and keeps 0.05 and 0.95 unchanged where it keeps the NDVI comparison
- [ ] LEARNINGS.md Spike results states for each candidate the share of measured passes that would exit 3 and whether each adoption criterion held and the rule chosen or that none was adopted
- [ ] docs/decisions/0013 records the outcome with its evidence files and sha256 values and a status line saying it is not yet approved by Jarrod
- [ ] If a rule is adopted a follow-up story for the code change exists on the board depending on st-a32a and if none is adopted this story is parked with the measured rates
- [ ] LEARNINGS.md Live run findings holds the issue #2 entry naming run 43072355326 and the layer finding with a pointer to ADR 0012 and the NDVI finding
- [ ] No file under src is changed by this story
- [ ] ruff check and ruff format --check and mypy and pytest all exit 0

## Implementation Plan

# st-da75 implementation plan: measure why Ramsar NDVI rows miss the DEA NBART tolerance and decide the row rule

Worktree `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-da75` on branch `story/st-da75`, at a0693ba. st-a32a is merged (08ec2ec) and ADR 0012 is approved. No file under `src/` changes.

## Verified facts

- Every story pointer resolves:
  - The design NDVI row (`docs/plans/2026-10-29-swan-wetland-change-design.md` line 228: "Per-polygon median within 0.05, correlation above 0.95").
  - `ndvi_scene_check`, `ndvi_median_check`, `dea_ndvi_median`, `find_nbart_item`, `parse_nbart_item` and `nbart_reflectance` in `src/wetland_change/verify/ndvi.py`.
  - `_verify_scene` in `src/wetland_change/verify/run.py`.
  - `summarise` and `_median` in `src/wetland_change/stats.py`, and `clear_mask` in `src/wetland_change/mask.py`.
  - `read_stack` in `src/wetland_change/raster/read.py`, and `discover` in `src/wetland_change/catalogue/search.py`.
- The eight seen failing rows are in the committed reports `docs/research/2026-11-12-issue-2-repro-20261029.json` and `-20261111.json` (verify at ad1fe76; sha256 in ADR 0012).
  - 2026-10-29: 34 ramsar rows, 31 scored, 4 fail, against ga_s2am_ard_3 final items. 15ea7fec is HLJ, db9546b0 is HLK and 64d1e8fb is JLL.
  - 2026-11-11: 45 ramsar rows, 42 scored, 4 fail, against ga_s2bm_ard_3 nrt items. 0fea38ac is HLJ, e2b6b9df is HLK, 6bcf3109 is HMK, 0a7f58ef is JLL and bd87c77f is JML.
  - n_dea_nodata is 0 on all eight.
- No commit since ad1fe76 touches stats, mask, indices, raster, windows, aoi, verify/ndvi or catalogue, so the stored medians should reproduce exactly.
- The planner ran the pipeline's `discover` (metadata only) on 2026-11-14 and it fixed the confirmatory sample at 32 scene-tiles on 8 passes:
  - 2026-09-12: 2 tiles.
  - 2026-09-17, 2026-10-02, 2026-10-12 and 2026-10-27: 5 tiles each.
  - 2026-01-30: 5 tiles (newest January pass).
  - 2026-04-30: 50HMK only (newest April pass).
  - 2026-07-29: 4 tiles, no HLJ (newest July pass).
  - There were no rejections. The exact ids are in batch b1.
- DEA STAC metadata on 2026-11-14:
  - Every confirmatory scene-tile is final, except 2026-10-27 on 50HLK, 50JLL and 50JML, which are nrt.
  - The recorded 2026-11-11 nrt items are still served.
  - The 2026-10-29 nrt item def48e1d is gone (404).
  - So the sample is final maturity except three nrt scene-tiles. The ADR states that mix.
- The `discover` cloud rule is strictly below 20.0.
- The ramsar AOI is read from `/Users/jarrodbaker/Documents/swan-wetland-change-data/aoi/dbca_010_ramsar_sites.geojson` via `--ramsar`, because the config's data/external path is absent in the worktree.
- Existing LEARNINGS regexes use `^Outcome: (populate|amend)$` and `^Outcome: (override|keep-global)$`. This story's outcome line is `NDVI row rule: K0|K1`, which collides with neither.
- The next ADR number is 0013, named `docs/decisions/0013-ndvi-row-rule-against-dea-nbart.md` per the story touches.

## Design (fixed in the pre-registration)

### Row definitions

Rows use exactly verify's reads:
- The grid comes from green.
- Guards run first: EPSG 32750, and `check_band_scaling` against the ESA XML.
- Then `read_stack` (raster:bands scale and offset), `rasterise`, `find_nbart_item` (best maturity) with `parse_nbart_item`, and the DEA CRS and transform checks.
- DEA nbart_red and nbart_nir_1 are read at window10, and DEA reflectance comes from `nbart_reflectance`.

Per-row quantities:
- P is clear & inside & DEA valid & finite DEA NDVI, so n_compared is |P|.
- ndvi_stored comes from `summarise`.
- ndvi_dea is the DEA median over P, and abs_diff is |ndvi_stored - ndvi_dea|.
- ndvi_pipeline_same is the pipeline median over P.
- Per-band medians over P for both sources give d_red, d_nir and band_max.
- s_dea and s_pipeline are the medians of per-pixel red+nir.
- A row is scored as in `ndvi_median_check` with min_pixels 100.
- A DEA CRS or grid difference fails every candidate.
- Read errors are dropped and listed.

### Candidates

- K0 is the status quo.
- K1(g) splits rows by conditioning:
  - Rows with s_dea >= S*(g) = 40g keep abs_diff <= 0.05.
  - Rows with s_dea < S*(g) block on |d_red| <= g and |d_nir| <= g against the same DEA item.
  - The correlation (r > 0.95, at least 5 rows) is unchanged and covers every scored ramsar row.
  - No row becomes unscored, and 0.05 and 0.95 are unchanged.
- Excluded:
  - Widening 0.05, or a tolerance scaled by red+nir (both widen 0.05).
  - A minimum pixel count above 100, or tile de-duplication (both leave rows unscored).
  - Band limits on every row (drops the NDVI comparison).

### Parameter rule

The rule runs on the nomination rows, which are all ramsar rows of the 8 seen scene-tiles re-read against the DEA item selected on the run day. g is chosen from {0.002, ..., 0.010}. A value is admissible when:
- N1: at least 0.95 of W rows pass 0.05.
- N2: I is non-empty and at least 0.95 of I rows have band_max <= g.
- N3: |W| is at least half of the scored rows.

The smallest admissible g is nominated. If none is admissible, the outcome is K0.

### Reproduction gate

- The eight rows are re-read against the recorded DEA item, fetched by id.
- ndvi_stored and ndvi_dea must match the report within 1e-6, and n_compared must match exactly.
- A recorded item that is no longer served is allowed only if it was not final.
- On failure the script records the message and exits non-zero. The confirmatory read is then refused, and st-da75 is parked.

### Decision

The decision uses the confirmatory rows at the nominated g. Adopt K1 only if all of A0 to A5 hold:
- A0: at least 100 scored rows on at least 6 passes, else the result is inconclusive and K0 stays.
- A1: at least 0.95 of W rows pass 0.05.
- A2: at least 4 K0-failing rows, of which at least 0.75 are in I with band_max <= g. Below 4 rows, A2 is untestable and counts as not met.
- A3: at least 0.95 of I rows have band_max <= g.
- A4: K1 fails strictly fewer passes than K0.
- A5: |W| is at least half of the scored rows.

The 0.05 comparison is the float comparison verify makes. The g and S* comparisons are exact Fraction comparisons of the float64 values.

### Hypotheses (reported only)

- H1, conditioning: supported when A1 and A2 hold.
- H2, mask (ramsar-13): the same-pixel pipeline median is within 0.05 of DEA on both seen ramsar-13 rows while abs_diff is not.
- H3, tile: on at least 10 confirmatory tile pairs with equal n_compared, the median between-tile |delta ndvi_stored| is at least 2 times the median DEA delta and at least 0.005.
- H4, maturity: re-score against a non-nrt 2026-11-11 item if DEA holds one, otherwise untestable. The K0 failing share by maturity is reported.

Reading rule: the decision depends on A0 to A5 only, and the recorded cause names the supported hypotheses only.

### Outcome lines

- `NDVI row rule: K0` or `NDVI row rule: K1`, plus `NDVI row parameters: g = <g>, S* = <S*>` for K1.
- ADR 0013 status line: "Status: decided by the pre-registered rule on <date> under Jarrod's request to complete the outstanding work; not yet approved by Jarrod."

## Steps

Batches run in order. The orchestrator commits after each one.

1. **b1, pre-registration.**
   - Insert `## Pre-registered hypotheses (st-da75, 2026-11-14)` into `LEARNINGS.md` after the st-2a78 section and before `## Spike results`.
   - It holds the disclosure (a) to (g), the definitions, K0 and K1, the parameter rule, the reproduction gate, the 32 confirmatory ids, A0 to A5, H1 to H4, the reading rule and the status.
   - Commit it alone: "st-da75: Pre-register the NDVI row rule against DEA NBART".
2. **b2, script and pure tests (TDD).**
   - Write `tests/test_ndvi_rows_decision.py` first, then `docs/research/2026-11-12-ndvi-nbart-rows.py`.
   - The script's pure core covers: constants, the Row dataclass, CSV round trip, the K0 and K1 row verdicts, pass verdicts with the correlation, `nominate`, `reproduction`, `decide`, `hypotheses`, the two report builders and `nomination_ready`.
   - `measure()` uses lazy imports and the network. The CLI has the subcommands `nominate` and `confirm`.
   - There is no network access in tests.
   - Commit: "st-da75: Add the NDVI row research script and its decision tests".
3. **b3, live nomination.**
   - Run `nominate` once in the background.
   - On a reproduction pass:
     - Add the `data/SOURCES.md` row (the nomination CSV sha256).
     - Add a test that recomputes the committed nomination.
     - Commit: "st-da75: Record the NDVI row nomination read".
   - On a reproduction failure:
     - Fix only the reading code, and only for a script bug, then rerun and record every attempt.
     - If the data changed, stop. The orchestrator commits the evidence and parks st-da75 with the recorded message.
4. **b4, live confirmation.**
   - Run `confirm` once. It refuses unless the committed nomination reproduces.
   - One rerun is allowed for a network failure before results are written, and both attempts are recorded. Any other failure stops the batch and is reported.
   - Add the SOURCES row (the rows CSV sha256) and a test that recomputes the committed rows.
   - Commit: "st-da75: Record the NDVI row confirmatory read".
5. **b5, results and decision record.** Write:
   - The `LEARNINGS.md` Spike results entry `### NDVI row rule against DEA NBART (<run date>)`.
   - The Live run findings entry `### Issue #2 daily verify exit 3 (2026-11-12)` at the top of that section. It names run 43072355326, the layer finding with a pointer to ADR 0012, and the NDVI finding.
   - `docs/decisions/0013-ndvi-row-rule-against-dea-nbart.md` with the evidence sha256 lines and the status line.
   - The ADR 0013 and Live-run-finding tests in `tests/test_config.py`.
   - Commit: "st-da75: Record the NDVI row rule in ADR 0013 and LEARNINGS".
6. **Orchestrator board step.**
   - Record the touches expansion with `story note st-da75`: tests/test_ndvi_rows_decision.py and docs/research/2026-11-12-ndvi-nbart-{nomination,rows}.{csv,txt}.
   - If K1: run `story create --discovered-from st-da75 --depends-on st-a32a --type feature --complexity hard` with the b5 report's spec, then run kit:verify and kit:finish-branch as usual.
   - If K0 or inconclusive: run `story park st-da75 --question "..."` with the measured rates.
   - Merging or pushing needs Jarrod's ask.

## Tests and what each proves

`tests/test_ndvi_rows_decision.py` (b2, pure, no network):
- Constants equal src and config: 0.05, 0.95, 5 rows, min_pixels 100 and the collection. The script cannot drift from verify.
- The g grid is 0.002 to 0.010 and S* is exactly 40g, so the conditioning bound is as pre-registered.
- The K0 row verdict equals `ndvi_median_check(...).passed` on synthetic arrays, including abs_diff exactly 0.05 and the three skip cases. The status quo is modelled exactly.
- The K1 W/I split is at s_dea >= S*, and the band limit is exact at g. W rows keep 0.05. The set of scored rows under K1 equals the set under K0, so no row becomes unscored.
- A grid or CRS difference fails a pass under every candidate.
- The pass verdict fails when r <= 0.95 over at least 5 rows and does not fail below 5 rows. r equals `ndvi_correlation_check`.
- `nominate` picks the smallest admissible g. It returns None when N1, N2 or N3 fails at every g, and N2 rejects an empty I.
- `decide` adopts K1 only when A0 to A5 all hold. Flipping each criterion alone gives K0 and names that criterion. A0 failing gives an inconclusive K0. Three K0-failing rows make A2 untestable and not met. g None gives K0.
- Reproduction: a 2e-6 deviation fails, n_compared off by 1 fails, a missing final item fails, a missing nrt item is allowed, and exact matches pass.
- SEEN_FAILING equals the 8 failing ramsar rows of the two committed JSONs, and SEEN_SAMPLE equals their 8 scene-tiles.
- CONFIRM_SAMPLE equals the 32 ids parsed from the committed pre-registration. This proves the sample is fixed before any read.
- The CSV round trip preserves floats, NaN and None. The reports are deterministic and contain the outcome line.
- H2, H3 and H4 are computed on synthetic rows, including the untestable paths.
- `nomination_ready` refuses when a seen row did not reproduce or when the committed TXT disagrees with recomputation.
- The parser requires `--ramsar` for both subcommands. Importing the script does no network or file I/O.

b3 and b4 add tests that the committed nomination and rows CSVs recompute to the committed TXTs byte for byte. The b4 test also checks that every pre-registered id appears as read or dropped.

`tests/test_config.py` (b5):
- ADR 0013 sha256 lines match the committed files (the script, the 4 outputs and the 2 JSONs).
- The outcome recomputed from the committed CSVs equals the `NDVI row rule:` line in LEARNINGS and in the ADR, and the parameters line if K1.
- The status line says "decided by the pre-registered rule" and "not yet approved by Jarrod".
- The issue #2 Live run findings entry names 43072355326, ADR 0012 and ndvi_vs_dea_nbart.

## Gates

Run each batch's gates in order, judged by exit code:
1. `uv run ruff check src tests scripts`
2. `uv run ruff format --check src tests scripts`
3. `uv run mypy src scripts`
4. `uv run pytest -q`

The script should also pass `uv run ruff check` and `uv run ruff format --check` on its own path. `-m live` tests are not part of this story; no src change.

## Constraints restated in every batch

- Agents commit nothing.
- Never edit stories/** or .agents/shousper-stories/local/**.
- No src change.
- Never touch the project's S3 bucket, AWS credentials, terraform or compaction; all reads are anonymous.
- Write nothing under swan-wetland-change-data (reading the AOI file is allowed).
- Flat factual prose with no em dashes.
- No scratch/*.py or *.sh paths in LEARNINGS.md or docs/research/*.md.
- kit:debugging before any fix.

## Implementation Notes

- 2026-11-14T11:12:30.658Z: 2026-11-14: work is on branch story/st-da75 at e230d78 (098fb14 pre-registration, fe0cf3c script and tests, 47233f0 hardening batch, 3b82198 nomination read, cd5af57 confirmatory read, e230d78 ADR 0013 and LEARNINGS entries). Outcome by the pre-registered rule: NDVI row rule: K0. No g on the grid is admissible (N2 fails at every g), so K1 is not nominated and A0 to A5 are not computed. Each live read ran once: nomination 04:45:16Z to 04:51:07Z, confirmatory 05:03:18Z to 05:25:43Z, both exit 0. Measured on the current rule: 8 of 8 confirmatory passes and 87 of 292 scored rows fail; nomination 2 of 2 passes and 9 of 78 rows. H1 not supported, H2 not supported, H3 supported, H4 untestable. Touches beyond the story's list: tests/test_ndvi_rows_decision.py and docs/research/2026-11-12-ndvi-nbart-nomination.csv, .txt and 2026-11-12-ndvi-nbart-rows.csv, .txt. The pre-registration text was amended in review before it was committed (no threshold, sample id, candidate or criterion changed), and a hardening batch was added to the plan before the live reads. Gates passed on e230d78 in the build's final verification. The branch is not merged: the pre-registered Status rule parks the story on a K0 outcome.
- 2026-11-14T12:09:55.011Z: 2026-11-14: Jarrod replied 'push & approved recommended' to the park question. The orchestrator's reading: ADR 0013 is approved and the status quo (NDVI row rule: K0) is kept, as ADR 0013 decides; the branch story/st-da75 is merged and the story closed. No other rule was named, so ndvi_vs_dea_nbart stays blocking on ramsar rows.

## Questions

- 2026-11-14T11:12:30.738Z: The st-da75 pre-registered rule kept the status quo (NDVI row rule: K0; K1 was not nominated because no g on the grid is admissible, N2 fails at every g). ndvi_vs_dea_nbart fails 8 of 8 confirmatory passes and 87 of 292 scored ramsar rows (nomination passes: 2 of 2 and 9 of 78), so verify keeps exiting 3 on most daily runs. Hypotheses: H3 (the same polygon differs between two tiles of one pass) supported; H1 and H2 not supported; H4 untestable. ADR 0013 records this on branch story/st-da75 (e230d78) and is not yet approved. Approve ADR 0013 and choose: (1) keep the status quo, (2) make ndvi_vs_dea_nbart advisory pending a new pre-registered spike, or (3) name another rule to test? Also say whether story/st-da75 is merged to main while the story stays parked.
