---
id: st-b6bf
title: Decide whether ramsar-21 needs its own water setting after its agreement failure on 2026-11-11
type: spike
priority: P3
complexity: hard
depends_on: []
discovered_from: st-a32a
touches: [LEARNINGS.md, config/pipeline.toml, docs/decisions/0014-ramsar-21-water-setting.md, docs/research/2026-11-12-ramsar-21-confirm.py, tests/test_config.py]
exclusive: false
created: 2026-11-12
updated: 2026-11-14
parked_complexity: hard
---

## Description

GitHub issue #2, the one ramsar water failure. On the 2026-11-11 pass ramsar-21 on tile 50HLJ scored agreement 0.8539 against its agreement_min of 0.91 on 3,299 mutually clear pixels (global setting MNDWI above -0.1). The pipeline calls 0.7051 of those pixels wet and DEA WO calls 0.5608 wet, a gap of +14.43 pp, and SCL class 6 agrees with WO at 0.8369. Under ADR 0008 an agreement failure on a ramsar polygon fails the run, so this row is a legitimate alert and stays one after st-a32a.

Context. ramsar-21 passed agreement on all six measured dates from 2026-09-12 to 2026-10-29 (docs/research/2026-11-05-wet-area-gap.csv). Its NDVI median moved from -0.808 on 2026-10-29 to -0.052 on 2026-11-11, so the polygon is drying, and the over-call against WO appeared as it dried. This is the pattern found for ramsar-12 (LEARNINGS.md 'ramsar-12 wet area gap': the extra wet pixels sit on the polygon edge and are mostly SCL class 4 or 5). The st-2a78 pre-registration notes that the dry end of the season was covered only by seen rows. Evidence file: /Users/jarrodbaker/Documents/swan-wetland-change/scratch/issue-2-repro/verification-20261111-scenes-20261112T032325Z.json (untracked, absolute path).

What this story decides, with the ADR 0005 mechanism and the st-2a78 method: whether ramsar-21 gets a per-polygon override in config/pipeline.toml. The seen row and the six seen dates only nominate candidates. The decision is made on a confirmatory sample of passes not yet seen for ramsar-21, by rules written into LEARNINGS.md before the script exists: a minimum sample (at least 6 confirmatory rows on at least 3 acquisition dates after 2026-11-01, inside DEA's WO retention), the clause (absolute wet gap of 5.0 pp or less at the chosen setting on every confirmatory row), a gain over the global setting, no over-correction, and an agreement_min by the ADR 0005 convention that is at least 0.91. If the minimum sample does not exist yet when the story is planned, park it with the count of passes available and the date by which three are expected, because the drying season has only begun. DEA WO is unvalidated, so the result measures consistency with WO and not accuracy.

No limit is loosened without the confirmatory sample. The outcome is recorded in an ADR as decided by the pre-registered rule under Jarrod's request to complete the outstanding work and not yet approved by Jarrod.

## Acceptance Criteria

- [ ] LEARNINGS.md holds a pre-registration section for this story committed before the research script: disclosure of the seen rows and the candidate settings and the confirmatory sample and the numbered decision rules
- [ ] The confirmatory sample has at least 6 ramsar-21 rows on at least 3 acquisition dates after 2026-11-01 or the story is parked with the count available
- [ ] docs/research holds the script and its CSV and text summary with gap and agreement per row at the global setting and at each candidate and at SCL class 6
- [ ] An override for ramsar-21 is added to config/pipeline.toml only if every pre-registered rule holds and otherwise the global setting stays and the failed rule ids are recorded
- [ ] An ADR records the outcome with evidence files and sha256 values and a status line saying it is not yet approved by Jarrod
- [ ] ruff check and ruff format --check and mypy and pytest all exit 0

## Implementation Plan

## st-b6bf execution plan (this pass: pre-registration only)

Scope, per the orchestrator note of 2026-11-14T12:51Z: write the LEARNINGS.md pre-registration, the README Limitations clause and a test that pins the section. Nothing is measured. No script, CSV or ADR is written, and no override goes into config or code. The orchestrator commits on story/st-b6bf, merges to local main and re-parks the story.

### Facts checked in the worktree (2026-11-14, metadata only, no pixel read)
- Branch story/st-b6bf at e835310 is clean. LEARNINGS.md has `## Pre-registered hypotheses (st-dd0d, 2026-11-14)`, which ends with "st-dd0d stays parked until the sample closes.", followed by `## Spike results`. The pattern test is `tests/test_waterbody_limit_preregistration.py`.
- ramsar-21 is Peel-Yalgorup System, 59.94 ha. It intersects only T50HLJ (Earth Search intersects search, 2026-09-01 to 2026-11-14).
- After 2026-11-01 there are three 50HLJ items: 11-01 at 42.4% cloud, 11-06 at 34.1% and 11-11 at 12.1% (the seen row). At about 12:55 UTC there was no item after 11-11, so the sample has 0 rows. `discover` keeps cloud cover strictly below 20.0 (`>=` rejects).
- Last season (2025-11-01 to 2025-12-31), 9 of 16 dates were under 20% cloud. Two of those dates (12-21 and 12-31) had two 50HLJ items each. `discover` does not dedupe, so one date can give two rows.
- WO retention: the DEA STAC lists `ga_s2_wo_provisional_3` 50HLJ items back to 2025-01-05, and a HEAD request on that water asset returned 200. The "about three months" retention recorded in st-5f74 and ADR 0009 does not hold for 50HLJ. As a result the seen Sept to Oct rows can be re-read, so R6 can pool them as st-2a78 did. The rule does not depend on this: rows DEA no longer serves are listed and left out.
- The seen evidence `scratch/issue-2-repro/verification-20261111-scenes-20261112T032325Z.json` is byte-identical to the committed `docs/research/2026-11-12-issue-2-repro-20261111.json` (sha256 9b53bbd3...). The six seen global-setting rows are in `docs/research/2026-11-05-wet-area-gap.csv`. No ramsar-21 row exists at any other threshold, so the candidates cannot be nominated from ramsar-21 data.
- Lines the new section must not start with, to avoid collisions: `tests/test_config.py` reads the first `^Outcome: (override|keep-global)$` and `^Outcome: (populate|amend)$` lines in LEARNINGS.md. `tests/test_repo_hygiene.py` rejects gitignored scratch `.py`/`.sh` paths named in LEARNINGS (a scratch `.json` path is fine).
- Script and ADR names follow the story's `touches`: `docs/research/2026-11-12-ramsar-21-confirm.py` and `docs/decisions/0014-ramsar-21-water-setting.md`.

### Steps
1. **RED.** Create `tests/test_ramsar21_preregistration.py`. Its tests should fail until the section exists. The tests prove:
   - the section is recorded once, between the st-dd0d heading and `## Spike results`;
   - every fixed parameter phrase is present (window, cloud rule, close minimum, candidate grid, tie rule, gate tolerance, R1 to R6 limits, override form, outcome format, file paths, ADR status wording, who-set-the-terms wording, evidence sha256, blindness bans);
   - the `Seen rows.` paragraph lists exactly the 7 seen 50HLJ item ids in date order;
   - the section never says Jarrod approved the terms;
   - no line in the section starts with `ramsar-21 water setting:`, `Failed rules:` or `Outcome:`, so the outcome lines stay with the later Spike results entry and ADR 0014 and do not collide with test_config;
   - config/pipeline.toml has no `ramsar-21` override while ADR 0014 does not exist, so no limit is loosened without the confirmatory sample. This is a guard and is green from the start.
2. **GREEN.** Insert the section `## Pre-registered hypotheses (st-b6bf, 2026-11-14)` into `LEARNINGS.md`, after the st-dd0d section and before `## Spike results`. Each paragraph and bullet goes on one line, as in the rest of the file. The section holds:
   - disclosure (a) to (i): the seen rows; other seen values; the catalogue facts; the WO retention finding; who set each term (option (b) and its window were the orchestrator's recommendation, taken as approved under 'push & approved recommended', and the question labelled no recommendation); the daily-run routes to the result; season; WO unvalidated; small sample;
   - definitions;
   - candidates: MNDWI above {-0.05, 0.00, +0.05, +0.10, +0.15, +0.20}, with scl6 reported only;
   - the 7 seen rows;
   - the reproduction gate;
   - the confirmatory sample: `discover` items from 2026-11-12 to 2026-12-31 that have a WO item, an equal grid and n of at least 100;
   - the close, at the end of the first date with at least 6 rows on at least 3 dates, else at 2026-12-31;
   - the status mode, which reads masks only and computes no index;
   - the decision run;
   - selection (lowest mean absolute gap, ties to the lower threshold);
   - R1 to R6 (st-2a78 limits, with R6 pooling the gated seen rows plus the confirmatory rows);
   - the override form, the reported values, how the script runs, the outcome-line format (inline only), blindness, and a status line for ADR 0014 saying it is not yet approved by Jarrod.
3. Edit the README.md Limitations bullet "Verify findings still open" so the st-b6bf clause points at the pre-registration, mirroring the st-dd0d clause.
4. Verify, one command per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. All must exit 0.

### Deferred (not this pass; the story stays parked)
- The script `docs/research/2026-11-12-ramsar-21-confirm.py` with decision tests, written and committed before the decision run.
- Status-mode counts for re-parking.
- After the close: one decision run writing the `.csv` and `.txt`.
- ADR 0014 `docs/decisions/0014-ramsar-21-water-setting.md`, with evidence sha256 values and the status "not yet approved by Jarrod".
- A `[water.overrides.ramsar-21]` table only if R1 to R6 all hold.
- Expected re-plan dates: the sample can close on about 2026-12-01 if every pass is clear, or about 2026-12-26 at last season's clear share, and no later than 2026-12-31. The decision run comes no earlier than the second UTC day after the closing date.

Suggested commit (orchestrator): `st-b6bf: Pre-register the ramsar-21 water setting rule`.

## Implementation Notes

- 2026-11-14T12:09:55.295Z: 2026-11-14: Jarrod replied 'push & approved recommended' to the park question. The question did not label a recommendation. The orchestrator's recommendation, taken as approved, is option (b): commit the LEARNINGS.md pre-registration now (candidates, rules R1 to R6 and a forward-looking sample of eligible 50HLJ passes from 2026-11-12 to 2026-12-31), then park the measurement until six eligible passes exist.
- 2026-11-14T12:51:59.044Z: 2026-11-14, scope of this pass (orchestrator): plan the pre-registration only. Deliverables are a LEARNINGS.md section placed after the st-dd0d pre-registration and before '## Spike results', a README Limitations clause if one is needed, and a test that pins the section's place and fixed parameters, in the pattern of tests/test_waterbody_limit_preregistration.py. Nothing is measured; no script, CSV or ADR is written; no override is added to config or code. The outcome ADR is 0014. The section must disclose who set each term exactly: option (b) and its sample window (eligible 50HLJ passes from 2026-11-12 to 2026-12-31) were the orchestrator's recommendation, taken as approved under Jarrod's reply 'push & approved recommended'; the question labelled no recommendation. Do not write that Jarrod approved the terms directly. Blindness: nobody opens any docs/research/verification-*.md other than verification-20261029T131944Z.md and verification-20261111T175303Z.md, any run log of a pipeline run newer than 43475454140, or any verification/ object in the output store; only commit metadata, gh run list JSON fields and catalogue item metadata (no pixel read) may be read. Build agents do not run git add or git commit, do not merge or push, do not edit stories/, and use no AWS credentials, aws CLI, S3 output store or terraform; the orchestrator commits on story/st-b6bf, merges to local main and re-parks the story until six eligible passes exist. The push to GitHub needs Jarrod's ask.

## Questions

- 2026-11-14T11:59:54.874Z: The st-b6bf minimum confirmatory sample does not exist yet, so the story parks under its own rule. Facts checked on 2026-11-14 against Earth Search, the DEA STAC and the AOI file:

- ramsar-21 (Peel-Yalgorup System, 59.9 ha) lies only on tile 50HLJ. That gives one row per acquisition date, so the minimum of 6 rows means 6 dates, not 3.
- After 2026-11-01 the catalogue holds three 50HLJ items:
  - 2026-11-01, cloud 42.4 percent, above cloud_cover_max 20, never processed.
  - 2026-11-06, cloud 34.1 percent, above cloud_cover_max 20, never processed.
  - 2026-11-11, cloud 12.1 percent. This is the seen row.
- Eligible confirmatory passes today: 0 rows on 0 dates.
- The next 50HLJ acquisitions are 11-16, 11-18, 11-21, 11-26, 12-01, 12-06 and so on. Last season, 9 of 16 50HLJ acquisition dates from 2025-11-01 to 2025-12-31 were under 20 percent cloud.
- If every pass is clear, three eligible dates arrive by 2026-11-21 and six by 2026-12-01.
- At last season's clear share, three arrive by about 2026-12-06 and six by about 2026-12-26.

In the meantime the daily pipeline scores ramsar-21 against WO on each new pass, commits the verification report (agreement values without polygon ids) and alerts if the pass fails. Which do you want?

(a) Park with nothing committed and re-plan on or after 2026-12-26.
(b) Commit the LEARNINGS.md pre-registration now, while no confirmatory pass exists. It would hold the candidates, rules R1 to R6 and a forward-looking sample: eligible 50HLJ passes from 2026-11-12 to a fixed end date, such as 2026-12-31. Then park the measurement until six eligible passes exist.
- 2026-11-14T13:25:00.665Z: Pre-registration committed on story/st-b6bf (6cd8c66) and merged to local main (8ad1c09) on 2026-11-14; nothing is measured and no override is added. The confirmatory sample holds 0 rows on 0 dates (no 50HLJ item after 2026-11-11 existed at about 12:55 UTC). It takes ramsar-21 passes acquired from 2026-11-12 to 2026-12-31 under the 20 percent cloud limit and closes at the end of the first acquisition date holding at least 6 rows on at least 3 dates, and no later than 2026-12-31. Expected close: about 2026-12-01 if every pass is clear, about 2026-12-26 at last season's clear share. Resume (unpark and plan the script, then its status mode) on or after 2026-12-03, or earlier when Earth Search lists six 50HLJ items under 20 percent cloud acquired from 2026-11-12, judged by catalogue metadata only. Until the decision files are committed, no verification report other than the two seen, no run log of a run newer than 43475454140 and no output-store object may be opened. For Jarrod: push main so the pre-registration is on GitHub before the 2026-11-16 pass of tile 50HLJ is processed. Option (b) and the window were chosen by the orchestrator under 'push & approved recommended'; the earlier question labelled no recommendation. The candidates (MNDWI above -0.05 to +0.20 in steps of 0.05) and the wording of R1 to R6 are the planner's; say so before 2026-11-16 if any term should change.
