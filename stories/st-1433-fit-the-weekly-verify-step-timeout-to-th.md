---
id: st-1433
title: Fit the weekly verify step timeout to the measured verify runtime
type: bug
priority: P1
depends_on: []
touches: [.github/workflows/verify.yml, tests/test_workflows.py]
exclusive: false
created: 2026-11-16
updated: 2026-11-16
---
## Description

GitHub issue #3: scheduled verify.yml run 43791803460 (2026-11-16, 36bac3e) failed because the step 'Verify the latest daily run' reached its 20-minute step timeout (`##[error]The action 'Verify the latest daily run' has timed out after 20 minutes.`). No check failed and nothing hung.

The step verifies the newest daily run with processed scenes. That is pipeline run 43072355326 of 2026-11-11 (5 scene-tiles), the only scheduled pipeline run since 2026-11-07 that processed a scene. The same verify of that run inside the daily pipeline, which has no step timeout, took 19m34s: 10m17s of per-scene raster reads, then 9m17s of run-level checks that log nothing (pooled gate, NDVI correlation, discovery, and the waterbody phase, which reads every stored observation file and fetches the 1,404 DEA Waterbodies time series one at a time), then exit 3. On 2026-11-16 the per-scene reads took 11m07s and the step was killed 9m06s into the run-level phase.

The 20-minute limit was set in st-e766 on 2026-11-03, before any verify of a processed daily run had been timed on a runner. The first weekly run (42548248931, 2026-11-09) exited 2 after 16 seconds because no daily run had processed a scene yet, a consequence accepted in st-5bbc, so 2026-11-16 was the first weekly run to verify a run. Every weekly run re-verifies the 2026-11-11 run until a daily run processes a new scene, so the 2026-11-22 schedule times out the same way unless the limit changes.

Per-scene cost was about 2.1 minutes per scene-tile on 2026-11-11. A daily run holding two full passes (up to 12 scene-tiles) needs about 35 minutes, which a 40-minute step limit covers. The credential step in verify.yml requests no `role-duration-seconds`, so its session lasts the 1-hour default from minting; verify and freshness together must stay under 60 minutes.

Once the step completes it is expected to exit 3, not 0. ADR 0013 keeps `verify` exiting 3 when a ramsar row fails `ndvi_vs_dea_nbart`, and the 2026-11-11 run holds four such rows and the ramsar-21 water agreement row (issue #2, st-da75, st-b6bf). This story makes the failure name its checks instead of a timeout; it does not make the weekly run green.

The change reaches the scheduled workflow only when main is pushed, which needs Jarrod's ask. Speeding up verify (a shared HTTP session or parallel fetches for the DEA series, fewer COG opens per polygon) and logging the start of each run-level phase are separate work and not part of this story.

## Acceptance Criteria

- [ ] In .github/workflows/verify.yml the step 'Verify the latest daily run' has `timeout-minutes: 40`.
- [ ] The verify job has `timeout-minutes: 75`, so the four step timeouts (5 + 15 + 40 + 5 = 65) stay at least 10 minutes under the job limit.
- [ ] The 'Timeouts' header comment in verify.yml gives the new arithmetic and cites the 19m34s verify of run 43072355326 as the measured basis.
- [ ] tests/test_workflows.py asserts the verify step timeout is at least 40 minutes.
- [ ] tests/test_workflows.py replaces the `sum(timeouts) < 60` assertion with one that the verify and freshness step timeouts sum to under 60 minutes, with a comment naming the 1-hour default session of the credential step.
- [ ] The four gates pass: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
