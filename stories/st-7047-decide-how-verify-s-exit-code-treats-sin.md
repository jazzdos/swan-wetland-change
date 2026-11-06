---
id: st-7047
title: Decide how verify's exit code treats single failures on the live water check
type: task
priority: P2
depends_on: [st-9aff]
discovered_from: st-9aff
touches: [LEARNINGS.md, README.md, docs/decisions/0006-wet-area-within-5pp-on-live-water-check.md, docs/decisions/0008-exit-code-for-live-water-check-failures.md, docs/research/2026-11-06-exit-rule-shares.csv, docs/research/2026-11-06-exit-rule-shares.py, docs/research/2026-11-06-exit-rule-shares.txt, docs/research/2026-11-06-ramsar-12-gap.csv, docs/research/2026-11-06-ramsar-12-gap.py, docs/research/2026-11-06-ramsar-12-gap.txt, src/wetland_change/cli.py, src/wetland_change/verify/checks.py, src/wetland_change/verify/matrix.py, src/wetland_change/verify/run.py, src/wetland_change/verify/wo.py, tests/test_cli.py, tests/test_config.py, tests/test_verify.py, tests/test_verify_matrix.py, tests/test_verify_wet_area_gate.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-06
---

## Description

With the wet area clause from st-9aff (ADR 0006), verify exits 3 if any water_vs_dea_s2_wo check fails, and a date has 29 to 45 polygon-scene checks. On the 6 dates with every polygon measured (docs/research/2026-11-05-wet-area-gap.csv), dates with a failing row go from 2 to 6, so the daily pipeline job would end red on most days, which is the same problem st-b602 raises for the Spearman check. ramsar-12 is 5 of the 9 rows that fail only the clause, with the pipeline wetter than WO by 5.38 to 6.82 pp on those rows, cause not investigated. The markdown report and CLI line show only agreement and its threshold, so a wet-area-only failure appears as a failure with measured above threshold. Out of scope for st-9aff, whose pre-registered rule put the clause in Check.passed without changing the exit logic.

## Acceptance Criteria

- [ ] An ADR states whether one polygon failing the live water check on one scene fails the run
- [ ] and gives the share of the measured dates that would fail under that choice
- [ ] The markdown report and CLI line show the wet area gap when a live water check fails on wet area alone
- [ ] LEARNINGS.md records the cause of the ramsar-12 gap
- [ ] or what was checked if no cause was found

## Implementation Plan

# st-7047 plan: exit-code policy for single failures on the live water check

Verified in the worktree `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-7047` (main 02f372a). All pointers in the story are correct: `src/wetland_change/verify/wo.py` sets `Check.passed` from agreement and `abs(wet_area_diff_pp) <= 5.0` and stores `wet_area_passed`, `wet_area_diff_pp`, `wet_area_max_pp` in `detail`; `src/wetland_change/cli.py` `verify` (about lines 293-353) exits 3 on `any(check.passed is False)`, then 6 (errored), then 4 (nothing scored); `checks._markdown` prints only measured and threshold; `matrix.py` counts every `passed is False` as fail. ADR 0006 and 0007 exist, next ADR is 0008, and `tests/test_config.py` already pins ADR 0007's sha256 lines (pattern to copy). `docs/research/2026-11-05-wet-area-gap.csv` has 255 rows (253 with n >= 100). No scipy is installed, so any edge-ring work uses numpy only. Stored observations carry `water_ha_index` and `water_ha_scl` per polygon-scene, which gives a cheap whole-history check for ramsar-12.

Data already in hand (from the CSV, n >= 100, 6 newest dates, which are the dates with every polygon measured):

| date | rows | fail agreement | fail clause only | polygons failing clause only |
|---|---|---|---|---|
| 2026-10-29 | 34 | 0 | 2 | ramsar-12 on both tiles |
| 2026-10-27 | 45 | 0 | 2 | ramsar-12 on both tiles |
| 2026-10-12 | 45 | 0 | 1 | ramsar-12 (1 of 2 tiles) |
| 2026-10-02 | 45 | 0 | 1 | ramsar-13 |
| 2026-09-17 | 45 | 1 | 1 | ramsar-22 (ramsar-15 fails agreement) |
| 2026-09-12 | 29 | 1 | 1 | ramsar-52 (ramsar-16 fails agreement) |

Candidate rules and their expected date counts: K1 any single failing check fails the run (6 of 6 dates); K2 agreement alone fails the run, wet-area-only failures are advisory (2 of 6); K3 wet area fails the run only when a polygon fails the clause on every one of its scenes in the run (4 of 6); K4 wet area fails the run only on a pooled run-level gap above 5 pp (2 of 6, pooled gaps are 0.43 to 1.99 pp). The pre-registered rule (step 1) picks the strictest candidate that adds at most 1 failing date over the agreement-only count, ties to the first listed. That selects K2. The plan does not assume it: the implementation batch starts by reading the script's `chosen:` line and stops if it is not K2.

## Steps

1. Batch 1, pre-registration. Write `## Pre-registered hypotheses (st-7047, 2026-11-06)` into `LEARNINGS.md` (after the st-9aff section, before `## Spike results`): candidates K1 to K4, the decision rule, and ramsar-12 hypotheses G1 to G5. Nothing is measured yet, as AGENTS.md requires. Proof: `uv run pytest -q tests/test_config.py` still passes (it parses LEARNINGS.md).
2. Batch 2a, `docs/research/2026-11-06-exit-rule-shares.py`, with outputs `2026-11-06-exit-rule-shares.csv` and `.txt`. Pure stdlib, reads only the committed CSV, exposes `load_rows`, `date_outcomes`, `choose` so a test can recompute. Writes the share of the 6 measured dates that fail under K1 to K4, the admissible set, and a `chosen:` line.
3. Batch 2b, `docs/research/2026-11-06-ramsar-12-gap.py`, with outputs `2026-11-06-ramsar-12-gap.csv` and `.txt`. Re-reads the 12 ramsar-12 scene-tiles (anonymous Earth Search and DEA reads, same code path as `wo_check`), checks it reproduces the CSV gap, then scores G1 to G5 (MNDWI threshold sweep, SCL class 6, 20 m edge ring, SCL class of the pipeline-wet-only pixels, whole stored history of `water_ha_index` against `water_ha_scl` from the read-only backfill). Output is the evidence for the LEARNINGS cause or the list of what was checked.
4. Batch 3a, code (TDD), only if step 2a chose K2:
   - `src/wetland_change/verify/checks.py`: `Check.wet_area_only_failure` and `Check.blocking` properties; markdown table gets a `note` column and a `warn` status for wet-only failures, the note naming polygon, item, signed gap and limit; JSON payload gains `n_warned`; `all_passed` stays strict.
   - `src/wetland_change/verify/matrix.py`: new `warn` row and end-to-end status, `n_warn` count, `n_fail` counts blocking failures only.
   - `src/wetland_change/cli.py` `verify`: exit 3 only on blocking failures, `warn` line with the gap as a fifth tab field, order 3 then 6 then 4 unchanged.
   - `README.md` verify paragraph, `wo.py` module docstring sentence.
   - Tests: `tests/test_verify_wet_area_gate.py` (property truth table, markdown, JSON, matrix) and new CLI tests in `tests/test_cli.py` (wet-only alone exits 0 with a `warn` line showing the gap; wet-only plus agreement failure exits 3; wet-only plus errored exits 6; only wet-only scored is not exit 4). Each proves one branch of the exit logic and the report requirement.
5. Batch 3b, records: results into `LEARNINGS.md` (decision outcome with the shares, and the ramsar-12 cause or what was checked), `docs/decisions/0008-wet-area-failures-do-not-fail-the-run.md` (decision, share of measured dates, rejected alternatives, evidence with sha256 pins, limits, consequences), a one-line status note on ADR 0006, and two tests in `tests/test_config.py`: the ADR 0008 sha256 values match the committed research files, and recomputing the shares from the committed CSV gives the numbers the ADR states.
6. Batch 4, gates: ruff check, ruff format --check, mypy, pytest, `GITHUB_ACTIONS=true` pytest, one command each, plus a `git status` check that only intended files changed and nothing was committed.

Not done here: a ramsar-12 override or limit change (a separate decision under ADR 0005 if G1 or G2 is supported), editing `stories/**`, live tests, AWS calls, commits.
## Orchestrator amendments

These override the text above wherever they differ.

1. Tie-break. Ties in the decision rule go to the candidate whose failing condition includes the other's for every possible run: K4 and K3 each include K2 (they fail every run K2 fails, and possibly more), and K1 includes K2, K3 and K4. If neither of two tied candidates includes the other, the one listed first wins. On this data K2 and K4 are expected to tie, so the expected choice is K4, but the script decides. Reason, recorded in LEARNINGS.md and the ADR: when two rules fail the same measured dates, keep the one under which the wet area clause can still fail a run, so a run-wide wet bias against WO is not reduced to warnings.
2. Disclosure. The LEARNINGS.md pre-registration and the ADR say plainly that the per-date counts were readable in the committed CSV when the rule was written, and that the st-9aff section already gives 2 and 6 for K2 and K1. The rule is a policy choice recorded before the script runs, not a blind test.
3. ADR file name, in every task: docs/decisions/0008-exit-code-for-live-water-check-failures.md, with heading `# 0008 Exit code for live water check failures`. It replaces 0008-wet-area-failures-do-not-fail-the-run.md everywhere, including the CLI stderr message, README.md and tests.
4. Exit-rule script (b2a): `choose` implements the tie-break in item 1, for example with a fixed includes relation {K1: {K2, K3, K4}, K3: {K2}, K4: {K2}}. The tests/test_config.py recomputation test asserts that `chosen` equals the chosen candidate stated in the ADR (a line `Chosen rule: K4`, parsed), not a literal 'K2'. The script's K4 uses counts recovered as round(share * n); the code below uses share * n. The ADR notes that the two differ only by rounding.
5. Code (b3a). The precondition accepts `chosen: K4` or `chosen: K2` and stops on anything else. Implement all of the K2 behaviour as written: a per-row wet-only failure is `warn`, does not block, and carries the gap in the markdown note and in the CLI's fifth field. If chosen is K4, also add a pooled run-level check:
   - In src/wetland_change/verify/wo.py, add `POOLED_WET_AREA_CHECK = "water_vs_dea_s2_wo_pooled_wet_area"` and `pooled_wet_area_check(checks: Iterable[Check]) -> Check | None`, modelled on `pooled_agreement`.
     - Contributors: the `water_vs_dea_s2_wo` checks with passed not None, n_mutually_clear > 0, and wet_area_pipeline and wet_area_wo both not None. Errored and skipped checks do not contribute.
     - Signed gap in pp: 100 * (sum(wet_area_pipeline * n) - sum(wet_area_wo * n)) / sum(n). Positive means the pipeline is wetter.
     - measured is the gap. threshold is WET_AREA_MAX_PP. passed is abs(gap) <= WET_AREA_MAX_PP, so exactly 5.0 passes, as with the per-row clause. reference is the WO checks' reference string.
     - detail holds n_checks, n_mutually_clear, the pooled wet_area_pipeline and wet_area_wo shares, wet_area_max_pp, and rule 'pooled over every scored live water check in the run, ADR 0008'.
     - Return None when no check contributes.
   - In src/wetland_change/verify/run.py, after verify_run has built all the per-scene checks, append the pooled check when it is not None.
   - In src/wetland_change/verify/matrix.py, add POOLED_WET_AREA_CHECK to the 'Water extent, live' row. A failed pooled check has no wet_area_passed detail, so it blocks: the row and End to end become `fail`.
   - In the markdown report and the CLI, the pooled row's note reads `pooled wet area gap +X.XX pp over N checks, limit 5.0 pp`, whether the check passed or failed.
   - Write these tests first:
     - Helper arithmetic from hand-computed values: two checks with different n, the sign of the gap, exactly 5.0 passes, 5.01 fails, None when nothing is scored, and skipping of passed None, n 0 and missing shares.
     - verify_run appends the pooled check. Use the existing verify_run harness in tests/test_verify.py if there is one; otherwise write a small assembly test.
     - The matrix row includes the pooled check.
     - CLI: wet-only failures with a passing pooled check exit 0. A failing pooled check exits 3 and prints a FAIL line for water_vs_dea_s2_wo_pooled_wet_area.
   - The wo.py module docstring and the README verify bullet describe both the per-row warn and the pooled run-level gate. They state that the pooled check covers the run, so a backfill run pools across all its dates.
6. Records (b3b), when K4 is chosen:
   - Decision: one polygon failing the live water check on one scene fails the run only when it fails agreement. A failure on wet area alone is a `warn` row showing its gap. The run fails on wet area when the gap pooled over every scored live water check in the run exceeds 5.0 pp (the new check water_vs_dea_s2_wo_pooled_wet_area).
   - State the share of measured dates that fail under the chosen rule and under each candidate, taken from the txt. Include one line per candidate in the form `Measured dates failing under K1: 6 of 6`, and the line `Chosen rule: K4`.
   - Rejected alternatives:
     - K1.
     - K2: it ties K4 on the measured dates but leaves no wet-area condition that can fail a run.
     - K3.
     - Widening the limit.
     - Dropping the clause.
   - Limits: pooling dilutes one small polygon's gap, and the per-row warn lines carry those gaps. Also give the ramsar-12 finding.
   - Status line: `accepted, 2026-11-06, pending Jarrod's review of the epic. Amends the Consequences of 0006; does not change the 5.0 pp limit or the per-row Check.passed.`
   - LEARNINGS.md results name the chosen rule and the shares.
7. If the script chooses K2, implement and record K2 as planned. Do not force K4.
8. Commit nothing; the orchestrator commits. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**. Never call AWS for the project's own bucket. Never run terraform. No live tests (-m live). Judge pytest by exit code and never clear addopts; for a count use -o addopts="-m 'not live'". Also run GITHUB_ACTIONS=true uv run pytest -q. Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data. Docs and comments are flat factual prose with no em dashes.

## Implementation Notes

- 2026-11-06T01:48:15.799Z: Built via build-flow run wf_9310e176-43c, committed 6eaee43. Pre-registered rule (LEARNINGS.md, st-7047 section) chose K4: measured dates failing K1 6/6, K2 2/6, K3 4/6, K4 2/6; K2 and K4 tie and K4 wins the includes tie-break. A check failing only the 5 pp wet area clause is now a warn row with its gap (markdown note, CLI fifth field) and does not change the exit code; the new run-level check water_vs_dea_s2_wo_pooled_wet_area fails the run when the pooled gap exceeds 5.0 pp. ADR 0008 records it, pending Jarrod's review of the epic; 0006 carries a pointer. ramsar-12 investigation: reproduction passed; G1, G3, G4, G5 supported, G2 not; follow-up filed as st-2a78. Gates: ruff, format, mypy, pytest, GITHUB_ACTIONS pytest all exit 0; 784 passed, 9 deselected.

## Questions
