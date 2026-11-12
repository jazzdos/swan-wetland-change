---
id: st-747e
title: "Record the first trial week: runner timings for spike 5 and the README status after deployment"
type: chore
priority: P3
depends_on: []
touches: [README.md, LEARNINGS.md]
exclusive: false
created: 2026-11-12
updated: 2026-11-12
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

## Implementation Notes

## Questions
