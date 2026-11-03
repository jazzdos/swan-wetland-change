---
id: st-b983
title: Run the Collection 1 backfill and score hypotheses 1 to 4
type: spike
epic: st-70d1
priority: P1
complexity: hard
depends_on: [st-c8ca, st-2048, st-c6d5]
touches: [LEARNINGS.md, docs/research/2026-11-02-backfill-analysis.py, docs/research/2026-11-02-backfill-driver-test.sh, docs/research/2026-11-02-backfill-driver.sh, docs/research/2026-11-02-backfill-fake-cli, docs/research/2026-11-03-backfill-changes.csv, docs/research/2026-11-03-backfill-evidence.json, docs/research/2026-11-03-backfill-hypotheses.md, docs/research/2026-11-03-backfill-scores.csv]
exclusive: false
gates: [test]
created: 2026-10-29
updated: 2026-11-03
---
## Description

Spike. Decision at board approval: a worker runs the full Collection 1 backfill locally, then tests the pre-registered hypotheses (LEARNINGS.md, "Pre-registered hypotheses").

- Output root: `/Users/jarrodbaker/Documents/swan-wetland-change-data/outputs` via `--output-root`. Create it; it sits outside every worktree so it survives worktree teardown.
- Range: 2022-12-01 to the day of the run. Collection 1 has no earlier history for five of six tiles (LEARNINGS.md, S4).
- Size: about 996 items, roughly 7 hours at an assumed 25 s per scene (S4; S3 timed one polygon window only).
- Run `uv run python scripts/fetch_aoi.py` first. Run the backfill in chunks, for example one calendar quarter per invocation, in the background. The ledger makes each chunk resumable, so rerun an interrupted one.
- Then run `wetland-change score` over the whole range and the DEA Waterbodies history check over the backfill.

Hypotheses:

1. Forrestdale shows a low-water anomaly in December 2023 or January 2024.
2. February to April 2023 at Forrestdale raise no anomaly. The 2022 half is untestable because Collection 1 has no data; record it so.
3. Winter 2025 (June to August) at Forrestdale and Thomsons shows water at or above the baseline, with no dry-down flag.
4. Spearman correlation between pipeline water hectares and DEA Waterbodies wet fraction, on passes within three days, is at least 0.9.

Polygons: Forrestdale is ramsar-56 and DEA waterbody qd63n1ww5_v3. Thomsons is ramsar-52 and qd635epws_v3. Report each hypothesis as supported, not supported or untestable, with the numbers. Do not tune thresholds or config to make a hypothesis pass; they are pre-registered.

## Acceptance Criteria

- [ ] The ledger under the output root has entries for at least 95 % of the Earth Search Collection 1 items from 2022-12-01 to the run date under the cloud threshold, with the reference count taken from a fresh search and recorded in the report.
- [ ] `docs/research/<date>-backfill-hypotheses.md` records the range, items processed and failed, wall time, and for each of hypotheses 1 to 4 the verdict with measured values (dates, z scores, Spearman rho and n).
- [ ] LEARNINGS.md gains a dated "Backfill hypotheses" section linking that report, with the 2022 half of hypothesis 2 marked untestable.
- [ ] `docs/research/<date>-backfill-changes.csv` lists every change row produced for ramsar-56 and ramsar-52.
- [ ] No file under `config/` or `src/` changes in this story.

## Implementation Plan

## Implementation plan for st-b983 (spike): Collection 1 backfill and hypotheses 1 to 4

No file under `config/`, `src/`, `tests/` or `data/` changes. Deliverables go in `docs/research/` and `LEARNINGS.md`. Run outputs go to `/Users/jarrodbaker/Documents/swan-wetland-change-data/` (`outputs/`, `state/`, `logs/`, `aoi/`), outside every worktree.

### Measured facts that change the story's estimates (2026-11-02)

- A fresh search of 2022-12-01 to 2026-11-02 through the CLI's own polygon set (27 Ramsar plus 1404 DEA Waterbodies polygons) returns 1147 scenes, 0 rejected, 163 filtered because the footprint misses every polygon (raw 1310). The story's 996 is the older bbox count over Ramsar and four lakes; `_load` in `cli.py` has loaded all DEA polygons since st-c6d5, which adds tile 50HMJ.
- Measured scene time is 34 s to 351 s by tile, not 25 s. Sequential total is about 30 to 45 h. Three date-disjoint lanes bring that to an estimated 10 to 15 h. Peak RSS is 501 MiB per process on a 16 GB machine.
- Output projects to about 300 MB against 24 GiB free. The disk check stays in the driver anyway, after the first chunk and after every later chunk.
- Decision: run the CLI as written with no polygon subsetting and no `src` or `config` change. The report states the measured figures against the story's.

### Steps

1. **T1: pre-register and write the analysis script.** Insert `## Pre-registered hypotheses (st-b983, 2026-11-02)` into `LEARNINGS.md` directly before `## Spike results`. Write `docs/research/2026-11-02-backfill-analysis.py` with subcommands `selftest`, `reference` and `analyse`. Test: `selftest` runs each verdict rule on hand-built frames at its boundaries. It proves the pre-registered rules return the stated verdict (untestable when nothing is scored, exactly rho 0.9 supported, a high flag does not satisfy H1, one failing polygon fails H3) and that the change comparison detects missing and extra rows.
2. **T2: fetch, smoke, record, launch.** Run `scripts/fetch_aoi.py` once and copy the AOI to `aoi/` with hashes. Run backfill, score and `analyse` for one date on a throwaway root; this proves the script reads real outputs before the hypotheses are hashed. Write `state/end_date`, `state/reference_count` and `state/preregistration.txt` (hashes of the pre-registration section and analysis script, written before launch). Write `docs/research/2026-11-02-backfill-driver.sh`, run its stub test, then launch it detached with `setsid`, `nohup` and `caffeinate`. The stub test proves: 17 chunks with the last capped at the end date, no run id reused across lanes, a failed chunk retried, a sequential sweep, one score call, a park on systematic first-chunk failure, disk projection, missing AOI and score failure, a rerun after DONE is a no-op, and a relaunch after `kill -9` reaches DONE. The planner ran this test against the same driver text and all cases passed.
3. **T3: wait, analyse, report.** Wait on `state/DONE` or `state/PARK` and heartbeat the story lease every 30 minutes. On DONE, run `analyse` against the real root and write `docs/research/<date>-backfill-hypotheses.md`, `<date>-backfill-changes.csv`, `<date>-backfill-scores.csv`, `<date>-backfill-evidence.json`, and `### Backfill hypotheses (<date>)` at the end of `## Spike results`. Tests: `analyse` exits non-zero unless rescored flagged rows equal the change files for ramsar-56 and ramsar-52, which proves the verdicts rest on what `wetland-change score` wrote. `git diff main --stat -- config src tests data` must be empty, which proves the no-change criterion. The `uv run pytest` gate must pass; the planner confirmed it exits 0 with AOI files present in the worktree.

### Acceptance criteria mapping

- At least 95% ledger coverage: `analyse` computes latest ledger ids intersected with reference ids over reference ids, where reference is a fresh `discover` (scenes plus rejected). The report also gives the raw count (about 87.6% on that reading) and explains that footprint-missed items cannot enter the ledger under any configuration.
- Report contents, LEARNINGS section with the 2022 half of H2 marked untestable, and the change CSV: T3.
- Verdicts are mechanical functions fixed before launch; thresholds are not tuned.

### Orchestrator notes

- Batches are sequential because each needs the previous one's output. Implementers do not commit. Each task runs `git add -N` so reviewers see new files in `git diff main`.
- Pre-registration evidence is the hash file written before launch, because implementers cannot commit. The worker commits at close from the worktree, code and docs only, never `stories/**`.
- The driver outlives any agent. If T3 returns blocked with the driver alive, run `story park st-b983 --question "<T3 reason>"`; nothing is lost. To resume, rerun T3 once `state/DONE` exists. If the lease lapses and the story is re-planned, T2 and T3 are idempotent against `state/`.
- Discovered work for the worker to file with `--discovered-from st-b983`: (a) `data/SOURCES.md` records DEA sha f89e7b98 but `fetch_aoi.py` now returns af28cf9d; (b) the `--now` help text says UTC but a naive value is read as local time. Neither is fixed here because both are outside `touches` and the no-change criterion.
- `caffeinate -ims` holds the machine awake on AC power. Closing the laptop lid can still sleep it; the driver resumes when it wakes, and wall time in the report includes any such gap.

## Implementation Notes

- 2026-11-02T10:14:29.479Z: Claim-time context, 2026-11-02: the 20 GB download cap in the shared learnings expired 2026-10-30 13:19 AWST and no longer applies. Free disk on /Users/jarrodbaker/Documents is 24 GiB (89% used), so measure output size after the first quarter chunk and project it over the full range before running the rest; stop and park if the projection exceeds the free space. Sessions lose their lease after 1h with no heartbeat, so a multi-hour run must be detached from any agent's lifetime and resumable through the ledger.
- 2026-11-02T11:15:18.406Z: Planner measurements, 2026-11-02: the fresh search returns 1147 scenes plus 163 footprint-filtered items (raw 1310), not 996, because all 1404 DEA Waterbodies polygons load since st-c6d5. Scene time is 34 to 351 s, so about 10 to 15 h on three date-disjoint lanes rather than 7 h. The 95 % coverage criterion is computed against scenes plus rejected; on the raw count coverage tops out near 87.6 %, and the report states both. A human should confirm this reading at review.
- 2026-11-03T09:34:40.210Z: The Mac went into clamshell sleep on battery at 13:12 AWST on 2026-11-03 and stayed asleep apart from short maintenance wakes until 17:27. Chunk 2026-10-01..2026-11-02 pass 1 failed 25 of 26 scenes on DNS errors and logged rc=2 secs=15612, so that value is sleep, not processing. Pass 2 started on waking. For T3: report backfill_seconds_sum and seconds_per_processed_scene with and without that pass. caffeinate -ims does not hold through a lid close.
- 2026-11-03T14:49:00.251Z: 2026-11-03: the owner accepted 1147 (scenes plus rejected) as the reference for the 95% coverage criterion at review. Coverage is 1.0 against it and 0.8756 against the raw 1310. The other 163 items miss every polygon and cannot enter the ledger.

## Questions
