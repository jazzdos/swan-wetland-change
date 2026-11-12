---
id: st-a32a
title: Stop uncalibrated DEA Waterbodies rows deciding the live water and NDVI verdict
type: bug
priority: P1
complexity: hard
depends_on: []
discovered_from: st-c6d5
touches: [README.md, data/SOURCES.md, docs/decisions/0006-wet-area-within-5pp-on-live-water-check.md, docs/decisions/0008-exit-code-for-live-water-check-failures.md, docs/decisions/0012-live-check-limits-apply-to-their-calibrated-layer.md, docs/research/2026-11-12-issue-2-repro-20261029.json, docs/research/2026-11-12-issue-2-repro-20261111.json, docs/research/2026-11-12-live-check-layers.csv, docs/research/2026-11-12-live-check-layers.py, docs/research/2026-11-12-live-check-layers.txt, src/wetland_change/cli.py, src/wetland_change/verify/checks.py, src/wetland_change/verify/layers.py, src/wetland_change/verify/matrix.py, src/wetland_change/verify/run.py, src/wetland_change/verify/wo.py, tests/test_cli.py, tests/test_config.py, tests/test_readme.py, tests/test_verify.py, tests/test_verify_layer_rule.py, tests/test_verify_layer_rule_run.py]
exclusive: false
created: 2026-11-12
updated: 2026-11-12
---

## Description

GitHub issue #2: the scheduled pipeline run 43072355326 (2026-11-11, the first scheduled run that processed scenes, 5 of them) exited 3 from verify with 'Water extent, live' 334 pass, 266 fail, 55 warn, 1162 skipped and 'NDVI' 522 pass, 158 fail, 1137 skipped (docs/research/verification-20261111T175303Z.md, 730 KB).

Root cause. Since st-c6d5 the polygon list given to verify holds both AOI layers: 27 ramsar polygons (the reporting unit) and 1,404 dea_waterbody polygons (added so the history check has lake rows). _verify_scene in src/wetland_change/verify/run.py runs the per-polygon live checks water_vs_dea_s2_wo and ndvi_vs_dea_nbart over every polygon in that list, so the waterbody layer is scored at the global agreement_min of 0.91, the 5.0 pp wet area limit and the 0.05 NDVI tolerance. Every one of those limits was calibrated or checked on ramsar polygons only (LEARNINGS.md 'S2 water calibration', 'Per-polygon water calibration', 'Wet area clause', 'Exit rule for the live water check', ADRs 0005, 0006, 0008). st-c6d5's story text asks for the history check only and never mentions live checks on waterbody polygons, so the widening was a side effect. The Milestone 2 review (docs/research/2026-11-04-milestone-2-review.md finding 5) flagged it and the only response was the 100 pixel floor.

Measured evidence, two local reproductions of verify at main ad1fe76 into a scratch output root (wetland-change backfill --start D --end D --output-root X, then wetland-change verify --output-root X --run-id R). The JSON reports, the commands (run-*.sh) and the exploratory splitter analyse.py are in /Users/jarrodbaker/Documents/swan-wetland-change/scratch/issue-2-repro/ (untracked, read them by absolute path):
- verification-20261111-scenes-20261112T032325Z.json, sha256 9b53bbd3a877fc721610b7ca5f25dcadfe431a9db0db58223da583da213ba26a. Scenes of 2026-11-11, DEA NBART maturity nrt. Water: dea_waterbody 290 pass, 262 fail, 47 warn, 1172 skipped; ramsar 34 pass, 1 fail (ramsar-21 on 50HLJ, 0.8539 against 0.91), 5 warn, 5 skipped. Pooled agreement 0.9054 over 1,199,591 px on dea_waterbody and 0.9616 over 2,263,040 px on ramsar. NDVI: dea_waterbody 468 pass, 150 fail, 1153 skipped; ramsar 38 pass, 4 fail, 3 skipped. Run-level pooled wet gap +4.33 pp over all rows and +3.701 pp over ramsar rows. NDVI Pearson 0.9917 over all rows and 0.9921 over the 42 ramsar rows. These counts match the CI report within the read errors of the reproduction.
- verification-20261029-scenes-20261112T032444Z.json, sha256 c579bed357ca58bf4ed6c1b2062accf71e3f7c626b5b174ae0712dd361f10db5. Scenes of 2026-10-29, the calibration date, DEA NBART maturity final on every scored row. Water: dea_waterbody 323 pass, 297 fail, 33 warn, 919 skipped; ramsar 30 pass, 0 fail, 2 warn, 2 errored, which matches the 2026-10-29 line of 'Exit rule for the live water check' (0 agreement failures, 2 clause-only), so the reproduction is valid. Pooled agreement 0.9237 over 1,666,006 px on dea_waterbody and 0.9878 over 1,898,815 px on ramsar. NDVI: dea_waterbody 395 pass, 310 fail; ramsar 27 pass, 4 fail. NDVI Pearson 0.9480 over all rows (below 0.95, with 123 rows lost to read errors) and 0.9983 over the 31 ramsar rows. Pooled wet gap -0.51 pp over all rows and +0.983 pp over ramsar rows.
- The waterbody failure share does not fall away with polygon size on 2026-10-29 (by mutually clear pixels: 119 of 236 under 200, 80 of 166 under 500, 70 of 165 under 2000, 24 of 60 under 10000, 4 of 26 above), and it is the same with final and with nrt references, so it is a property of the layer at these limits and not of reference maturity or of tiny polygons alone.

Decision to implement (recorded as ADR 0012, decided by the orchestrator on 2026-11-12 under Jarrod's request to complete the outstanding work, not yet approved by Jarrod). A limit applies only to the layer it was calibrated on. The per-polygon live checks stay blocking on the ramsar layer exactly as today, including the per-polygon overrides and the ADR 0008 warn rule. On the dea_waterbody layer the same measurements are still taken and stored, but they are advisory: they carry no verdict, cannot fail the run, and are reported as one summary per check instead of one line per polygon. The two run-level checks derived from the rows (water_vs_dea_s2_wo_pooled_wet_area and ndvi_correlation_vs_dea_nbart) use ramsar rows only, which is the population ADR 0008 measured. The waterbody layer keeps its designed verification, the history checks water_vs_dea_waterbodies and water_spearman_vs_dea_waterbodies, unchanged. No limit is loosened and no ramsar row changes status. A calibrated floor for the waterbody layer is a separate story.

Pointers. Check, Check.blocking and wet_area_only_failure and the markdown writer are in src/wetland_change/verify/checks.py; matrix rows in src/wetland_change/verify/matrix.py; the exit code and the printed lines in src/wetland_change/cli.py; AoiPolygon.layer in src/wetland_change/aoi.py; pooled_wet_area_check in src/wetland_change/verify/wo.py. The planner chooses the representation of an advisory row, within the acceptance criteria.

Out of scope, each has its own story: the NDVI tolerance on dark ramsar polygons (4 ramsar NDVI rows fail on each date, so a run will still exit 3 after this story), the ramsar-21 agreement failure of 2026-11-11, and any floor for the waterbody layer. Do not edit LEARNINGS.md in this story: the in-review story st-9812 holds that file, and the LEARNINGS entry for issue #2 is part of the NDVI story. Do not edit the 'As of this commit' section of README.md, which st-747e rewrites.

## Acceptance Criteria

- [ ] A test written first fails on main: a run whose only failing live water and NDVI rows are on dea_waterbody polygons makes verify exit 0
- [ ] A failing agreement row on a ramsar polygon still makes verify exit 3 and a failing NDVI row on a ramsar polygon still makes verify exit 3 and a wet-area-only failure on a ramsar polygon is still a warn row
- [ ] water_vs_dea_s2_wo_pooled_wet_area and ndvi_correlation_vs_dea_nbart are computed from ramsar rows only and each names the layer and its row count in its detail
- [ ] Every dea_waterbody live row stays in the verification JSON with its measured value and reference and detail and carries the layer name and an advisory marker
- [ ] An advisory row never makes all_passed false and never counts as pass or fail or warn in a matrix row and never prints its own line in the CLI output or in the markdown report
- [ ] The verification JSON and the markdown report and the CLI output each hold one advisory summary per live check for the dea_waterbody layer giving rows scored and rows skipped and rows outside the ramsar limit and for water the pooled agreement and pooled wet gap and for NDVI the median absolute difference
- [ ] The history checks water_vs_dea_waterbodies and water_spearman_vs_dea_waterbodies give the same results as before proven by their existing tests passing unmodified
- [ ] docs/decisions/0012 records the rule and the measured evidence of both reproductions and the rejected alternatives and a status line saying it was decided by the orchestrator on 2026-11-12 and is not yet approved by Jarrod
- [ ] docs/research holds a dated script with its CSV and text summary that recompute the per-layer counts from the two verification JSONs and ADR 0012 lists each file and each input JSON with its sha256
- [ ] The README verification table states the layer rule for the live water and NDVI rows and its 'As of this commit' section is unchanged
- [ ] LEARNINGS.md is unchanged by this story
- [ ] ruff check and ruff format --check and mypy and pytest all exit 0

## Implementation Plan

# st-a32a plan: live check limits apply only to the layer they were calibrated on (ADR 0012)

Checked in the worktree `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-a32a` (branch story/st-a32a, HEAD ad1fe76). Every pointer in the story matches the code.

## Pointers checked

- `src/wetland_change/verify/run.py`, `_verify_scene` (line 191), loops over every polygon on the scene, both ramsar and dea_waterbody.
  - Ramsar ids are `ramsar-<objectid>` with layer "ramsar". Waterbody ids are `dea-<uid>` with layer "dea_waterbody".
  - Per polygon it emits `water_vs_dea_s2_wo` through `_guard(..., polygon_id=...)`, which calls the module-global `wo_check`.
  - Per polygon it emits `ndvi_vs_dea_nbart` through the module-global `ndvi_scene_check`; run.py then sets `detail["polygon_id"]`.
  - Scene-level live rows carry no polygon_id. These are the WO or NBART lookup errors, "no DEA WO scene found" and "no DEA ARD item for this acquisition".
- `verify_run` (line 377) does these steps in order:
  1. `pooled_wet_area_check(checks)` over every scored row;
  2. the NDVI correlation over every scored NDVI row;
  3. discovery;
  4. the history checks, through `_waterbodies`;
  5. `write_report`.
- `src/wetland_change/verify/checks.py`: `Check.errored`, `wet_area_only_failure` and `blocking`; `check_note`; `write_report`, which writes all_passed, n_scored, n_skipped, n_errored, n_warned and the markdown.
- `src/wetland_change/verify/matrix.py`: `matrix_status`.
- `src/wetland_change/cli.py`: `verify` (lines 299-379) prints one line per check and exits 3, then 6, then 4.
- `src/wetland_change/verify/wo.py`: `pooled_agreement` and `pooled_wet_area_check` (integer counts, ADR 0008).
- Nothing in scripts/ or .github reads all_passed or the matrix.
- The two reproduction reports are in the main checkout under `scratch/issue-2-repro/`, untracked:
  - 2026-11-11: sha256 9b53bbd3a877fc721610b7ca5f25dcadfe431a9db0db58223da583da213ba26a, run 20261112T032325Z.
  - 2026-10-29: sha256 c579bed357ca58bf4ed6c1b2062accf71e3f7c626b5b174ae0712dd361f10db5, run 20261112T032444Z.
  - Both are from git ad1fe76 and contain no local paths. Git compresses them to about 130 KB each.
- A probe run of verify_run with fake live checks showed three things the tests must handle:
  - The fixture's SCL shares fail (`scl_share_water` False), so the exit-code tests must patch `run.scl_checks`.
  - `_discovery` evaluates `es_client or open_client(...)` before it calls `discovery_checks`. The tests must pass truthy clients and patch `run.discovery_checks`.
  - The default `docs_dir=Path("docs/research")` is relative to the cwd, so the CLI tests wrap verify_run with a tmp docs_dir.

## Measured (recomputed from the two JSONs; layer from the polygon_id prefix)

**2026-11-11, live water:**

| Layer | Pass | Fail | Warn | Skip | Pooled agreement | Pooled wet gap |
|---|---|---|---|---|---|---|
| ramsar | 34 | 1 | 5 | 5 | 0.9616 | +3.70 pp over 40 rows |
| dea_waterbody | 290 | 262 | 47 | 1,172 | 0.9054 | +5.51 pp over 599 rows |
| all rows | | | | | | +4.33 pp |

**2026-11-11, NDVI:**

| Layer | Pass | Fail | Skip | Pearson | Median abs diff |
|---|---|---|---|---|---|
| ramsar | 38 | 4 | 3 | 0.9921 over 42 | 0.0125 |
| dea_waterbody | 468 | 150 | 1,153 | 0.9914 over 618 | 0.0297 |
| all rows | | | | 0.9917 | |

**2026-10-29, live water:**

| Layer | Pass | Fail | Warn | Skip | Pooled agreement | Pooled wet gap |
|---|---|---|---|---|---|---|
| ramsar | 30 | 0 | 2 | 2 | 0.9878 | +0.98 pp |
| dea_waterbody | 323 | 297 | 33 | 919 (120 errored) | 0.9237 | -2.21 pp |

**2026-10-29, NDVI:**

| Layer | Pass | Fail | Skip | Pearson |
|---|---|---|---|---|
| ramsar | 27 | 4 | 3 | 0.9983 |
| dea_waterbody | 395 | 310 | 867 | 0.9456 |
| all rows | | | | 0.9480 (the run's correlation check failed) |

**Waterbody failure share by size, 2026-10-29.** It stays near half from 100 to 2,000 mutually clear pixels:

| Mutually clear pixels | Failing rows |
|---|---|
| 100-199 | 119 of 236 |
| 200-499 | 80 of 166 |
| 500-1999 | 70 of 165 |
| 2000-9999 | 24 of 60 |
| 10000+ | 4 of 26 |

**Ramsar blocking rows under the rule.** Both runs still exit 3, which the story puts out of scope:

| Run | Water | NDVI |
|---|---|---|
| 2026-11-11 | 1 (ramsar-21) | 4 (ramsar-13 twice, ramsar-20, ramsar-21) |
| 2026-10-29 | 0 | 4 (ramsar-15, ramsar-20, ramsar-21, ramsar-27) |

No non-live check blocks in either report.

## Design

1. **New module `src/wetland_change/verify/layers.py`.**
   - Constants: `BLOCKING_LAYER = "ramsar"`, `WO_CHECK`, `LIVE_CHECKS = (water_vs_dea_s2_wo, ndvi_vs_dea_nbart)`, `LAYER_RULE` (the ADR 0012 path).
   - `apply_layer_rule(checks, layers)` touches only live rows whose polygon_id is in the `{polygon_id: layer}` map:
     - Ramsar rows gain `detail["layer"]` and keep their verdict.
     - Rows on other layers become `passed=None`. Their detail gains `layer`, `advisory: True`, `within_ramsar_limit` (the original passed), `advisory_rule` and, for water rows, `wet_area_only`.
     - Measured, threshold, reference and the rest of the detail are kept. The input is not mutated.
   - `advisory_summaries(checks)` gives one dict for each advisory layer and live check, including checks with no rows. Each dict gives:
     - n_rows, n_scored, n_skipped, n_errored and n_outside_ramsar_limit;
     - for water: n_wet_area_only, pooled_agreement, n_mutually_clear, pooled_wet_gap_pp and wet_area_max_pp;
     - for NDVI: median_abs_diff and tolerance;
     - rule and units.
   - `advisory_note(summary)` gives one line of text, shared by the CLI and the markdown.
2. **`checks.py`.**
   - `Check.advisory` is True when `detail["advisory"] is True`.
   - `blocking` and `wet_area_only_failure` are False for advisory rows; `errored` is unchanged.
   - New `verdict_checks(checks)`.
   - The pooled `check_note` appends ", ramsar layer only" when the detail names a layer.
   - `write_report`:
     - computes n_scored, n_skipped, n_errored, n_warned and all_passed from verdict rows only;
     - adds `n_advisory` and `advisory` (the summaries) to the JSON;
     - keeps every row in `checks`;
     - writes no markdown row for an advisory check;
     - adds a `## Advisory` table (`| check | layer | summary |`) between Matrix and Runtime, only when summaries exist.
3. **`wo.py`.**
   - New `PooledWetArea` and `pooled_wet_area(checks)`, the integer-count pool over the rows given; it does not filter on passed.
   - `pooled_wet_area_check(checks, *, layer=None)`. Unchanged when `layer` is None. With a layer, the detail gains `layer` and the rule names ADR 0008 and ADR 0012.
4. **`matrix.py`.** Advisory rows are left out of status, the five counts and End to end. Each row gains `n_advisory`. The markdown header is unchanged.
5. **`run.py`.**
   - After the scene loop: `checks = apply_layer_rule(checks, {p.polygon_id: p.layer for p in polygons})`.
   - The pooled check is computed from ramsar rows with `layer="ramsar"`.
   - The correlation is computed from scored ramsar NDVI rows, with `"layer": "ramsar"` in its detail; `n_rows` is the ramsar count.
   - Discovery and history are untouched.
6. **`cli.py`.**
   - The printed lines and the exit codes use `verdict_checks`.
   - One line per summary: `advisory\t<check>\t<layer>\t<note>`.
   - The docstring states the rule.
7. **Docs.**
   - ADR 0012.
   - The dated research script, CSV and txt.
   - The two input JSONs copied into docs/research with the same sha256.
   - A data/SOURCES.md row.
   - README: the "Water extent, live" and "NDVI" table rows and the `verify` bullet in "Running locally". The Limitations section is not touched.

## Steps

1. **Batch 1, task T1, the library and its tests first.**
   - Files: `src/wetland_change/verify/layers.py`, `checks.py`, `wo.py`, `matrix.py`, and the new `tests/test_verify_layer_rule.py`.
   - Proves the row rule, the summaries, the matrix exclusion and the report contract on hand-built checks.
2. **Batch 1, task T2 (independent), the research artefacts.**
   - Copy the two JSONs into `docs/research/2026-11-12-issue-2-repro-20261111.json` and `docs/research/2026-11-12-issue-2-repro-20261029.json`.
   - Write the stdlib-only `docs/research/2026-11-12-live-check-layers.py`, which produces `2026-11-12-live-check-layers.csv` and `.txt`.
   - Add the data/SOURCES.md row.
   - Proves the counts above come from the committed files alone.
3. **Batch 2, task T3, wiring.**
   - Write `tests/test_verify_layer_rule_run.py` first. It imports nothing new on this branch.
   - Show the dea-only CLI test exiting 3 on a detached checkout of main.
   - Then change `run.py` and `cli.py`.
4. **Batch 3, task T4, records and final gates.**
   - Files: `docs/decisions/0012-live-check-limits-apply-to-their-calibrated-layer.md`, the README edits, the ADR 0012 tests in `tests/test_config.py` and one README test in `tests/test_readme.py`.
   - Run the four gates in order plus `GITHUB_ACTIONS=true uv run pytest -q`.
   - Confirm that LEARNINGS.md, the README Limitations section and stories/** are unchanged.

## What each test proves

- **`test_cli_verify_exits_0_when_only_waterbody_live_rows_fail`** (written first; exits 3 on main). The run has 5 ramsar and 5 dea polygons on the fixture scene. Every ramsar live row passes and every dea row fails water (agreement 0.70, wet gap +80 pp) and NDVI. verify exits 0.
- **Parametrized CLI tests on ramsar-52:**
  - an agreement failure exits 3 with a `FAIL` line;
  - an NDVI failure exits 3;
  - a wet-area-only failure is a `warn` line, writes the ADR 0008 stderr line and exits 0.
- **Report test.**
  - all_passed is True.
  - Each dea row stays in the JSON with its measured value, reference, detail, `layer` and `advisory`, plus `within_ramsar_limit` False.
  - The matrix live and NDVI rows pass with `n_advisory` 5 and n_fail 0.
  - There are two `advisory` summaries: water with pooled agreement 0.70 and gap +80.0 pp; NDVI with median abs diff 0.35.
- **Pooled and correlation test.**
  - The pooled check has `layer` "ramsar", `n_checks` 5 and measured 0.0.
  - The correlation has `layer` "ramsar", `n_rows` 5, only ramsar ids in `rows`, and r = 1.0.
  - On main, the same run pools 10 rows (gap 40 pp, failing).
- **Output-line test.** No CLI line and no markdown line contains a dea polygon id. There are exactly two `advisory\t` lines and two `## Advisory` table rows.
- **Twin-polygon test with the real `wo_check` and `ndvi_scene_check`.** A dea polygon with ramsar-52's geometry gets the same measured value and reference. Its `within_ramsar_limit` equals ramsar-52's passed. This proves the rule does not alter measurement.
- **Scene-level test.** An error row with no polygon_id stays a verdict row and still counts in n_errored.
- **Unit tests in `tests/test_verify_layer_rule.py`.**
  - The ramsar or advisory split, and untouched rows (scene-level, pooled, history rows with dea ids, unknown ids).
  - No input mutation.
  - A row with advisory True and passed False never blocks.
  - Hand-computed summaries: pooled agreement 0.868 over 5,000 px, gap +1.60 pp, NDVI median 0.04, and an NDVI summary with zero rows.
  - The note text.
  - `pooled_wet_area_check(layer=...)`, and unchanged behaviour without a layer.
  - The matrix exclusion and `n_advisory` on every row.
  - The write_report counts and markdown placement, and no Advisory section without advisory rows.
- **Unchanged files that must pass as they are:**
  - `tests/test_verify_waterbodies.py`;
  - the history and pooled tests in `tests/test_verify.py`;
  - `tests/test_verify_wet_area_gate.py`;
  - `tests/test_verify_matrix.py`;
  - `tests/test_cli.py`.
- **ADR tests in `tests/test_config.py`.**
  - The sha256 recorded for the script, CSV, txt and both JSONs matches the files.
  - Recomputing the CSV and txt with the script equals the committed files.
  - The key counts: 262 dea and 1 ramsar water failures on 2026-11-11; the 2026-10-29 Pearson over all rows below 0.95 and over ramsar rows at or above 0.95.
  - The script's all-rows values equal the reports' own pooled and correlation values.
  - The status line, and `LAYER_RULE` exists.
- **README test.** Both live rows name ADR 0012 and the ramsar layer.

## Not done here

- The NDVI tolerance on dark ramsar polygons (st-da75).
- ramsar-21 (st-b6bf).
- Any floor for the waterbody layer (st-dd0d).
- Edits to LEARNINGS.md or the README Limitations section.
- Commits (the orchestrator commits).
- Live tests.

## Implementation Notes

- 2026-11-12T05:49:01.366Z: Built by kit build-flow run wf_30ea62bb-4d1 (4 tasks, 3 batches, each reviewed clean) and committed as 6d4b53a on story/st-a32a. Fresh gates in the worktree before the commit: ruff check, ruff format --check, mypy and pytest -q all exit 0. Red shown on a detached checkout of main: 7 of 10 new end-to-end tests fail there (verify exits 3 and all_passed is False when only waterbody live rows fail). Research script reproduces the diagnosis numbers with no mismatch: 2026-11-11 dea_waterbody water 290 pass 262 fail 47 warn; 2026-10-29 323 pass 297 fail 33 warn. Deviations from the plan: the data/SOURCES.md row sits after the st-2a78 row and not at the table end (orchestrator change to avoid a merge conflict with story/st-9812); ADRs 0006 and 0008 each gained a one-line pointer to 0012; tests/test_cli.py and tests/test_verify.py each gained one test and lost none; ADR 0012 states measured line counts in place of the plan's 'about a thousand lines' and gives the size-bin failure share as 0.40 to 0.50 for 100 to 9999 pixels. Both reproduced runs still exit 3 under the rule on ramsar rows alone (st-da75 and st-b6bf). ADR 0012 is not yet approved by Jarrod.

## Questions
