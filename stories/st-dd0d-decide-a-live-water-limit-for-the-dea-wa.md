---
id: st-dd0d
title: Decide a live water limit for the DEA Waterbodies layer from the trial's advisory summaries
type: spike
priority: P3
complexity: hard
depends_on: [st-a32a]
discovered_from: st-a32a
touches: [LEARNINGS.md, docs/decisions/0015-waterbody-layer-live-water-limit.md, docs/research/2026-12-05-waterbody-layer-agreement.py]
exclusive: false
created: 2026-11-12
updated: 2026-11-14
parked_complexity: hard
---

## Description

Follow-up to st-a32a and ADR 0012. From st-a32a on, the live water and NDVI measurements on the 1,404 dea_waterbody polygons are advisory: each run stores them and reports one summary per check (rows scored, rows outside the ramsar limit, pooled agreement, pooled wet gap, NDVI median absolute difference). On the two passes measured before that change the pooled agreement with DEA WO on this layer was 0.9237 (2026-10-29) and 0.9054 (2026-11-11) against 0.9878 and 0.9616 on the ramsar layer, and about 45 percent of scored waterbody rows fell under 0.91 on both. No limit has ever been calibrated for this layer.

What this story decides: whether the dea_waterbody layer gets its own blocking run-level limit for the live water check, set from data that had not been seen when the rule was written. The rule is written into LEARNINGS.md first: the sample is the advisory summaries of every scheduled run with scored waterbody rows from the day st-a32a reaches main until the end of the four-week trial (2026-12-05); the two passes above are disclosed as seen and are not part of the sample; a minimum of 8 runs on at least 6 acquisition dates; the candidate limit is the floor to 0.01 of the lowest pooled agreement in the sample minus 0.02 (the ADR 0005 and ADR 0007 convention); it is adopted only if that value is at least 0.85 and the pooled wet gap stays within 5.0 pp on at least 90 percent of the runs; otherwise the layer stays advisory and the measured rates are recorded. The outcome goes in an ADR for Jarrod's approval. Whether a waterbody polygon is ever scored one by one is not part of this story.

This story cannot start before st-a32a is on main and the trial has produced the minimum sample. If it is claimed earlier, park it with the count of runs available.

## Acceptance Criteria

- [ ] LEARNINGS.md holds the pre-registered rule for this story committed before any advisory summary of the sample is read
- [ ] The sample has at least 8 scheduled runs on at least 6 acquisition dates after st-a32a reached main or the story is parked with the count available
- [ ] docs/research holds the script and its CSV and text summary with one row per run giving rows scored and pooled agreement and pooled wet gap for the dea_waterbody layer
- [ ] An ADR records whether a run-level limit is adopted and its value and the measured rates and a status line saying it is not yet approved by Jarrod
- [ ] No limit is added to config or code by this story
- [ ] ruff check and ruff format --check and mypy and pytest all exit 0

## Implementation Plan

## st-dd0d plan of record (execution-time, 2026-11-14)

### What I checked in the worktree
- Worktree `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-dd0d` is on `story/st-dd0d` at 709a894 (same as local main) with a clean tree.
- st-a32a is on main: merge 08ec2ec on local main, and on GitHub main from 2db25a1956062302b11522308ac571a3ea0061b2. ADR 0012 is approved. The advisory summaries exist in code: `src/wetland_change/verify/layers.py` (`advisory_summaries`, `advisory_note`), `src/wetland_change/verify/checks.py` (markdown `## Advisory` table, JSON `advisory`).
- The sample is still empty. The last `pipeline` run is 43475454140 (schedule, 2026-11-13 17:42 UTC, head 37af4e4, before st-a32a). `git log 2db25a1..origin/main` shows no `Verification report for` commit (checked 12:22 UTC). Scheduled runs start late, at about 17:40 to 20:40 UTC. The first run that can score waterbody rows is on 2026-11-16.
- I found one fact the rule depends on. `.github/workflows/verify.yml` overwrites `verification/<run_id>.json` in the unversioned bucket for the run it checks. That leaves the committed markdown `docs/research/verification-<run_id>.md` as the only copy the scheduled run itself wrote, so the rule reads the printed values (agreement to 4 decimals, wet gap to 2).
- The markdown reports do not list scenes reliably (waterbody rows no longer print). Acquisition dates therefore come from the ledger through `scenes_for_run` (`src/wetland_change/verify/run.py`).
- Several tests parse LEARNINGS.md: `tests/test_config.py` (`^Outcome: ...$`, `^NDVI row rule: ...$`), `tests/test_ndvi_rows_decision.py` (slices from the st-da75 heading) and `tests/test_repo_hygiene.py` (scratch paths). The new section must not add a line matching those patterns and must not name scratch/ paths.
- Baseline `uv run pytest -q` exits 0.

### Approved direction
On 2026-11-14 Jarrod replied "push & approved recommended" to the park question. The question did not label a recommendation, so the orchestrator took option (b), its own recommendation, as approved. The pre-registration is committed now with these terms:
- the story's minimum of 8 scheduled runs on at least 6 acquisition dates;
- the sample closes at the eighth eligible run and no later than 2027-01-31;
- weekly verify.yml runs are excluded;
- a run counts only with at least 30 scored waterbody rows.

The story is then parked.

### Interpretations for the reviewer to confirm
1. "Closes at the 8th eligible run" is taken as closing at the first eligible run that meets the minimum. Normally that is the eighth; if those eight runs span fewer than 6 dates, the sample stays open until the next eligible run that brings it to 6. The literal reading would make an 8-run, 5-date sample fail the minimum outright.
2. The source of record is the committed markdown report, not the JSON in the bucket, because verify.yml overwrites the JSON (see above).
3. Reports of recovered runs, rerun attempts and workflow_dispatch runs are excluded. A run with a scene on a seen date (2026-10-29, 2026-11-11) is excluded.
4. The limit is a run-level floor on the layer's pooled agreement. The wet gap only gates adoption (D3), and no wet gap limit is set for the layer.
5. The research script's date prefix will be the UTC date of its decision run, not the 2026-12-05 named in the story's touches list.

### Phase 1 (this batch, now)
1. RED. Create `tests/test_waterbody_limit_preregistration.py`:
   - (i) the heading `## Pre-registered hypotheses (st-dd0d, 2026-11-14)` occurs once, between the st-da75 pre-registration heading and `## Spike results`;
   - (ii) the section contains each fixed parameter verbatim: the 2db25a1 sha, event `schedule`, the verify.yml exclusion, 30 scored rows, 8 runs on 6 dates, the end of 2027-01-31, the floor of (A_min minus 0.02) to 0.01, 5.00 pp, the 0.85 floor, the 0.9 share, the outcome-line format, the ADR 0015 path and "not yet approved by Jarrod";
   - (iii) no line in the section starts with `Waterbody layer water limit:`, because the outcome line belongs to the later Spike results entry and ADR.

   These tests prove the rule is recorded in the right place and that a later edit dropping a parameter fails.
2. GREEN. Insert the section, text fixed in the task, into `LEARNINGS.md` immediately before `## Spike results`. Disclosure (c) is filled from git and `gh run list` metadata at commit time. No verification report, run log or bucket object is opened.
3. Correct the stale st-dd0d clause in `README.md` (Limitations, "Verify findings still open"). It now says the decision uses the trial's summaries; it should give the pre-registered sample instead.
4. Run ruff check, ruff format --check, mypy and pytest, all exit 0. The build agents do not commit and use no AWS credentials; the orchestrator commits on `story/st-dd0d`.

### Phase 1 close-out (orchestrator, not an implementer task)
5. Merge `story/st-dd0d` into local main. The push to GitHub needs Jarrod's ask: the push he asked for on 2026-11-14 was made before this commit existed. It should land before the 2026-11-16 scheduled pipeline run (about 17:40 UTC), so GitHub timestamps show the rule predates every sample report.
6. Park st-dd0d with the count: 0 eligible scheduled runs on 0 acquisition dates as of the commit time. State the close condition: the first eligible run that brings the sample to 8 runs on 6 dates, no later than 2027-01-31 23:59:59 UTC. AC1 and the parked branch of AC2 are then met. The CSV, text summary, ADR and gate ACs wait for Phase 2.

### Phase 2 (when the story is resumed; not in these batches)
7. Resume once GitHub main holds at least 8 `Verification report for <id>` commits from scheduled `pipeline` runs after 2db25a1 (commit metadata only), or after 2027-01-31.
8. Write `docs/research/<date>-waterbody-layer-agreement.py` and `tests/test_waterbody_layer_decision.py` test-first on synthetic inputs. No sample report is opened.
   - Parse the `## Advisory` row; the tests build lines with the real `advisory_note`.
   - Select the run's own report: its run_id falls between the GitHub run's start and its last update.
   - Implement eligibility, the close rule, L in exact Decimal, W, D1 to D3 and the outcome and `Failed criteria:` lines.
   - Inject the adapters for `gh api`, `git show` and `scenes_for_run`.
   - Snapshot inputs to `<stem>-inputs.json` so tests recompute the CSV and text offline.
9. Run the status mode, which prints counts only. If the sample is open, re-park with the counts. Once it is closed, make one decision run (one rerun only after a network failure before files are written) and commit the CSV, text and inputs files.
10. Record the outcome:
    - Add a Spike results entry to LEARNINGS with the outcome line on its own.
    - Write `docs/decisions/0015-waterbody-layer-live-water-limit.md` with the status line "decided by the pre-registered rule ... not yet approved by Jarrod".
    - Update the README.
    - Add a test that the outcome line agrees across LEARNINGS, the ADR and the text summary.
11. Change nothing under `src/` or `config/` (AC5). Run the four gates.

## Implementation Notes

- 2026-11-14T12:09:55.157Z: 2026-11-14: Jarrod replied 'push & approved recommended' to the park question. The question did not label a recommendation. The orchestrator's recommendation, taken as approved, is option (b): commit the LEARNINGS.md pre-registration now with the story's minimum (8 scheduled runs on at least 6 acquisition dates); the sample closes at the 8th eligible run and no later than 2027-01-31; weekly verify.yml runs are excluded; a run counts only if it scores at least 30 waterbody rows. The story is then parked until the sample closes.

## Questions

- 2026-11-14T12:05:42.130Z: st-dd0d cannot start: its sample holds 0 scheduled runs on 0 acquisition dates, so it parks under its own rule. Facts checked on 2026-11-14 at 12:00 UTC. No advisory summary from the sample was read.

- st-a32a reached local main at 02:14 UTC (08ec2ec) and GitHub main at 04:11 UTC (2db25a1). The last scheduled pipeline run, 43475454140, started at 2026-11-13 17:42 UTC on 37af4e4, before st-a32a. No pipeline run has started since.
- Today's run should score no waterbody rows. Earth Search has no AOI acquisition on 11-14. The 11-13 T50HMK footprint (18.6 percent cloud) touches none of the 1,404 waterbody polygons, and 11-13 T50HMJ is at 74.5 percent cloud. The first run that can score waterbody rows is on 2026-11-16.
- The minimum of 8 runs on 6 acquisition dates probably cannot be reached by 2026-12-05. Earth Search shows full AOI passes every 5 days (11-01, 11-06, 11-11) and T50HMJ edge passes 2 days after each one (11-03, 11-08, 11-13). The edge footprint touches 32 waterbody polygons. Projected acquisition dates in the window are 11-16, 11-18, 11-21, 11-23, 11-26, 11-28, 12-01 and 12-03, which is at most 8, and 4 of them cover only about 32 polygons. One daily run normally processes one date, so 8 runs needs every pass under the 20 percent cloud limit. The same window in earlier years had 6 usable dates in 2025 (11-16, 11-21, 11-26, 11-28, 11-30, 12-01) and 6 in 2024 (11-16, 11-18, 11-23, 11-26, 11-28, 12-01), each likely about 6 runs. In the first trial week, 1 of 8 runs processed scenes.
- The story does not say whether weekly verify.yml runs count. They re-verify the latest daily run's scenes, so counting them would count the same rows twice. It also sets no minimum of scored rows per run, and an edge-pass run of at most 32 polygons could set the floor on its own.

Which do you want?

(a) Commit the LEARNINGS.md pre-registration now, before the 11-16 run, exactly as the story states (end 2026-12-05, minimum 8 runs on 6 dates). Then park until 2026-12-06. If the minimum is not met, the layer stays advisory and the ADR records the count.
(b) Commit the pre-registration now with a later fixed end date and the same minimum. The sample closes at the 8th eligible run, and no later than a date you name, such as 2027-01-31. Then park until it closes.
(c) Commit the pre-registration now with a minimum the window can meet, such as 6 runs on 6 dates, end 2026-12-05. Then park until 2026-12-06.
(d) Park with nothing committed and re-plan after 2026-12-05. This option has a cost: the daily workflow commits each run's verification report, with its ## Advisory table, to main, so later pre-registration would not be blind.

With (a), (b) or (c), the pre-registration would also exclude weekly verify.yml runs and count a run only if it scores at least 30 waterbody rows, unless you say otherwise.
- 2026-11-14T12:51:34.303Z: Pre-registration committed on story/st-dd0d (f33e562) and merged to local main (e835310) on 2026-11-14; nothing is measured. The sample holds 0 eligible scheduled runs on 0 acquisition dates (last scheduled pipeline run 43475454140 started 2026-11-13 17:42 UTC, before the rule). It closes at the first eligible run holding at least 8 runs on at least 6 acquisition dates, and no later than 2027-01-31 23:59:59 UTC. Resume (unpark and plan the measurement) when GitHub main holds at least 8 commits 'Verification report for <id>' from scheduled pipeline runs after 2db25a1, judged by commit metadata only, or after 2027-01-31. Until the decision files are committed, no report of the sample, run log of a sample run or verification/ object may be opened. For Jarrod before the first sample run: (1) push main so the pre-registration is on GitHub; the next scheduled run is 2026-11-14 at about 17:40 UTC. (2) The 30-row minimum admits a clear edge-pass run that scores 30 to 32 waterbody rows, and such a run can set A_min: keep 30, or raise it (for example to 100) before any sample run exists. Option (b) and its terms were chosen by the orchestrator under 'push & approved recommended'; the earlier question labelled no recommendation.
