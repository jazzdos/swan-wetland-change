---
id: st-747e
title: "Record the first trial week: runner timings for spike 5 and the README status after deployment"
type: chore
priority: P3
depends_on: []
touches: [LEARNINGS.md, README.md]
exclusive: false
created: 2026-11-12
updated: 2026-11-14
---

## Description

Spike 5 (runner dry run) was blocked on a throwaway repository with an OIDC role. The production pipeline workflow has since run through OIDC, so the figure it was meant to give is available from real runs. Pipeline run 43072355326 (scheduled, 2026-11-11, started 17:52:40 UTC) is the only run so far that processed scenes: step 'Run the incremental pipeline' took 336 s for 5 scenes (about 67 s per scene, against 139 to 152 s locally), step 'Verify the run' took 1174 s, 'Build the catalogue' 28 s, and the job took 26 minutes against the 120 minute limit. The four scheduled runs of 2026-11-07 to 2026-11-10 processed no new scene and took about 1 minute each. The five scheduled runs started at 16:24, 16:39, 20:42, 17:47 and 17:52 UTC, 6 to 10 hours after the 10:17 UTC cron. Each processed day also commits a verification Markdown of about 730 KB to docs/research. The README section 'As of this commit' (around lines 373 to 431) still describes the state before deployment: infrastructure not applied, workflows disabled, no scheduled run, runner access to the DEA hosts untested, nothing run against S3, catalogue.base_url a placeholder, the credentialed DuckDB read not run, and spikes 5 to 7 not run. The 2026-11-06 deployment (see docs/handoffs/2026-11-06-milestone-2.md and git log) changed all of these. Spike 6 (stac-browser) and the anonymous half of spike 7 stay blocked while the bucket is private (ADR 0011). Figures must be re-read from the run with gh before they are written, and the single processed run must be stated as n = 1.

## Acceptance Criteria

- [ ] LEARNINGS.md Spike results gains an S5 runner timing entry with the per-step seconds of run 43072355326
- [ ] seconds per scene
- [ ] the count of processed runs (1)
- [ ] the start delay of each scheduled run against the cron
- [ ] and how many scenes fit in the 120 minute job at the measured pipeline and verify rates
- [ ] The entry states what spike 5 planned and did not measure (peak memory on the runner) and that spike 6 and the anonymous read of spike 7 remain blocked while the bucket is private
- [ ] Every bullet of the README section 'As of this commit' that the deployment made false is corrected or removed
- [ ] each checked against the repository
- [ ] the workflow runs or the handoff
- [ ] and no bullet that is still true is dropped
- [ ] The README names the two open trial failures (GitHub issues #1 and #2) or their fixing stories as the current state of the four-week trial
- [ ] ruff check
- [ ] ruff format --check
- [ ] mypy and pytest all exit 0

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-747e, main 2db25a1, 2026-11-14)

- The story is implementable. Two story premises are out of date and the entry and README must say so:
  1. Run 43072355326 did not succeed. Its job conclusion is `failure`: step 'Verify the run' failed (FAIL rows on water_vs_dea_s2_wo and ndvi_vs_dea_nbart), the commit step still ran (commit 37af4e4). The story says only 'processed'; the entry must record the conclusion and that the verify duration is for a failing verify.
  2. More runs now exist: scheduled pipeline runs 42391137737 (2026-11-07), 42500964092 (11-08), 42695477540 (11-09), 42868562753 (11-10), 43072355326 (11-11), 43278279989 (11-12), 43475454140 (11-13), plus workflow_dispatch 42227866026 (2026-11-06, 45 s, no verify). Only 43072355326 ran 'Verify the run' (all others skipped it), so processed runs = 1 as of the 2026-11-13 run; the implementer re-lists on the day and also checks for a 2026-11-14 run. n = 1 therefore still holds; if a new run processed scenes the entry reports each run and says n as measured.
- Figures from `gh run view 43072355326 --json jobs` (step start/complete times): Run the incremental pipeline 17:53:00 to 17:58:36 = 336 s; Verify the run 17:58:36 to 18:18:10 = 1174 s; Build the catalogue 18:18:10 to 18:18:38 = 28 s; job 17:52:44 to 18:18:43 = 1559 s (25 min 59 s) against timeout-minutes 120. Manifest in the log: processed 5, failed 0. Per scene: 336/5 = 67.2 s pipeline, 1174/5 = 234.8 s verify, 302.0 s together. Fixed overhead = 1559 - 336 - 1174 = 49 s. Scenes fitting 7200 s: (7200 - 49) / 302.0 = 23.7, so 23 (pipeline alone: 7200 / 67.2 = 107). Assumes linear scaling from n = 1; verify also reads the whole stored history for Spearman, so its per-scene share is not separable at n = 1.
- Start delay against the 10:17 UTC cron (run createdAt): 11-07 16:24:29 = 6h07m29s; 11-08 16:39:02 = 6h22m02s; 11-09 20:42:14 = 10h25m14s; 11-10 17:47:39 = 7h30m39s; 11-11 17:52:40 = 7h35m40s; 11-12 18:17:29 = 8h00m29s; 11-13 17:42:32 = 7h25m32s. The story lists five runs; seven scheduled runs exist now.
- Issues #1 and #2 are CLOSED (2026-11-14T02:16:58Z and 02:17:00Z) per `gh issue view`. #1 = weekly verify run 42548248931, fixed by st-9812. #2 = pipeline run 43072355326: first cause (DEA Waterbodies rows) fixed by st-a32a (ADR 0012, approved 2026-11-14); second cause (ramsar NDVI rows vs ndvi_vs_dea_nbart) measured in st-da75, rule K0 keeps status quo, ADR 0013 unapproved, branch story/st-da75 not merged, so on main the daily verify can still exit 3 on those rows. Related open stories: st-b6bf (ramsar-21 water agreement), st-dd0d (waterbody layer limit), st-b49e (DuckDB aws login profiles; its text records that on 2026-11-14 both tests in tests/test_live_private_outputs.py passed against the bucket with credentials exported to the environment, so the credentialed read has run).
- README 'Limitations > As of this commit' (lines 375 to 431) bullets made false: infra not applied (applied 2026-11-06; handoff 'Update, 2026-11-06, deploy'); workflows disabled (`gh workflow list --all`: alert, pipeline, tests, verify all active); no scheduled run; DEA host reachability untested (Fetch the AOI step succeeded in all 8 runs, verify read DEA WO and explorer STAC from the runner on 43072355326); credentialed DuckDB read not run (st-b49e); catalogue.base_url placeholder (config/pipeline.toml line 52 holds the bucket URL, commit 2b8d582) and output root not seeded (seeded from the 2026-11-02 backfill copy per handoff); 'Nothing has run against S3' and 'spikes 5 to 7 not run'. Deployment section paragraph 'Two more steps come before the first scheduled run ... still holds the .invalid placeholder' is also false and is fixed.
- Tests that read README: tests/test_readme.py (required headings incl. 'Limitations', 'Deployment', 'Querying with DuckDB'; keep all headings), tests/test_infra.py (README must still contain 'backfill', 'initial_lookback_days', '--output-root s3://', 'catalogue.base_url', 'bucket_url', 'config/pipeline.toml', 'multipart', 'github_repository=... ', and must not contain 'public-read', 'public bucket', 'cors', 'stac-browser', 'anonymous caller', 'intentionally public' case-insensitively: the existing README says 'stac-browser' only... the implementer runs the tests to confirm, and must not add any forbidden string), tests/test_verify_matrix.py (matrix table rows), tests/test_licence.py. tests/test_config.py pins only the '### S9 historical tolerance' heading and Outcome lines in LEARNINGS.md. tests/test_repo_hygiene.py scans LEARNINGS.md for scratch/ paths (do not name scratch/ paths).
- README line 326 to 330 (Querying with DuckDB) is owned by st-b49e, which touches README.md: do not edit that section.

## Steps

1. LEARNINGS.md: append `### S5 runner timing (2026-11-14)` as the last entry of '## Spike results' (after '### ramsar-12 setting confirmation (2026-11-06)', before '## Live run findings'). Content: run table with ids, conclusion, per-step seconds of 43072355326, seconds per scene, count of processed runs (1, n = 1) with every run id, start delay per scheduled run against the cron, scenes that fit in 120 minutes at the measured rates with formula and caveats, what spike 5 planned (design 'Pre-start spikes' item 5: uv sync time, rasterio import, OIDC assumption, minutes per run, free Actions minutes for public repos; the design's risk table lines for runner time and memory) and what this does not measure (peak memory on the runner; rasterio import and uv sync only as the 'Install the project' step; per-request S3 latency), that spike 6 (stac-browser) and the anonymous read of spike 7 stay blocked while the bucket is private (ADR 0011), the 730 KB per processed day verification Markdown (docs/research/verification-20261111T175303Z.md is 730856 bytes), and the observation that actual starts (6.1 to 10.4 h after the cron) exceed the 21-minute smallest margin of the 'DEA WO availability at first processing' entry. Flat prose, no em dashes. A test is not needed for prose; the gates prove nothing regressed (test_repo_hygiene, test_config).
2. README.md: correct every bullet in 'As of this commit' per the list above, each checked against the repository or runs, and drop no true bullet (keep: scheduled-job-alive row note if `src/wetland_change/verify/matrix.py` and the latest report still show it not-run; water thresholds; hypotheses H2 to H4; Spearman note adjusted only where the S3 read time is now partly measured; dea_wo_agreement; Peel Inlet and Harvey Estuary; Earth Search history; directory marker st-c667; ramsar-12 and ADR 0010; st-2bfd/st-2bc1 bullet only if still open, check the board; reproducibility bullet likewise). Add a first bullet stating the trial state: scheduled runs since 2026-11-07, the single processed run and its failure, GitHub issues #1 and #2 (closed 2026-11-14 after st-9812 and st-a32a) and what remains open (ramsar NDVI rows, st-da75; ramsar-21, st-b6bf; waterbody layer limit, st-dd0d), pointing to LEARNINGS 'S5 runner timing (2026-11-14)'. Fix the Deployment paragraph. Update the closing paragraph to also point to docs/handoffs/2026-11-06-milestone-2.md deployment update (already referenced) without duplicating.
3. Gates (one command per line, judged by exit code): `uv sync` if needed, `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`, all exit 0. These prove the README and LEARNINGS edits kept the headings, tables and strings that tests/test_readme.py, tests/test_infra.py, tests/test_verify_matrix.py, tests/test_licence.py, tests/test_config.py and tests/test_repo_hygiene.py pin.

No commit, push, AWS call, terraform, S3 write, or write under /Users/jarrodbaker/Documents/swan-wetland-change-data. Network use is read-only `gh`. Do not edit stories/**.

## Implementation Notes

## Questions
