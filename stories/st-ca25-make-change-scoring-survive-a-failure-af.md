---
id: st-ca25
title: Make change scoring survive a failure after the ledger write
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [README.md, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, tests/test_ledger.py, tests/test_manifest.py, tests/test_pipeline.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

write_ledger (src/wetland_change/pipeline.py:319) marks scenes succeeded before score_changes, write_manifest and build_and_write run. If one raises, the next run skips those scenes through seen_keys, so their change files and manifest are never written and later days stay green. Recovery needs a manual score. This contradicts the design statement that reruns are safe. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 2.

## Acceptance Criteria

- [ ] A failure in score_changes or write_manifest leaves the run's scenes eligible for scoring on the next run
- [ ] The next run writes the change files and a manifest that the crashed run left unwritten
- [ ] A test forces score_changes to raise once and shows the change file exists after the following run

## Implementation Plan

# st-ca25: Make change scoring survive a failure after the ledger write

## Verification of the story against the worktree

The bug is real, but the line pointer is stale. Since st-5241, `run_once` checkpoints the ledger after every scene in the scene loop, then calls `score_changes`, `write_manifest` and `build_and_write`. `seen_keys` hides succeeded scenes from the next run, and `written_dates` holds only scenes processed in the current run, so a later run never scores a crashed run's dates and never writes its manifest.

## Design

The orchestrator replaced the planner's `pending/score_<run_id>.json` marker before build. The marker is written after the scene loop, so it misses a raise inside the loop (for example `write_ledger` after credentials expire) and a killed process (the 120 minute job timeout). The review's finding 2 names both as causes. The marker also needs a new public-readable prefix and a corrupt-marker failure path.

The ledger and `runs/` already hold the fact the marker would record: a daily run with ledger rows and no `runs/<run_id>.json` did not finish.

1. `run_once` lists `runs/` once and finds every run with non-backfill ledger rows and no manifest. A null `run_kind` counts as daily, as in `watermark`.
2. After the scene loop, one `score_changes` call covers the current run's dates plus the UTC dates of those runs' succeeded rows.
3. A manifest rebuilt from the ledger is written for each unfinished run, with `recovered_by` set. The current manifest is then written with `recovered_runs`. A failure anywhere leaves a run without a manifest, so the next run picks it up.
4. Scoring is deterministic (ADR 0004), so rescoring after a `write_manifest`-only failure is byte-identical.

A recovered manifest holds what the ledger knows: processed, failed and rejected counts, observation files, ledger parts, start time. `skipped_seen`, `skipped_filter` and both watermarks stay empty, because only the crashed process knew them. Its change fields come from the combined scoring call, so with several recovered runs they can list files of other dates; `rescore_later` already means a run's list can include later dates.

## Steps

Batch 1: `recovered_by` and `recovered_runs` on `RunManifest`; `unfinished_runs` and `scored_dates` in `ledger.py`.
Batch 2: wire into `run_once`, crash tests, README.

## Out of scope

A recovered run is not verified by the daily job, because `pipeline.yml` keys verify on the current run's `processed`. Filed as discovered work. `verify --run-id` covers it by hand, and the weekly job picks it when it is the newest daily run with processed scenes.

## Verification

One command per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.

## Implementation Notes

- 2026-11-05T14:38:12.705Z: Design changed before build: the next run finds crashed runs from non-backfill ledger rows with no runs/<run_id>.json, instead of the planner's pending/ marker, which misses a raise inside the scene loop and a killed process. A normal run makes one extra S3 request, the listing of runs/. A recovered manifest holds what the ledger knows; skipped_seen, skipped_filter and both watermarks stay empty. test_run_once_scoring_skips_observation_files_from_other_months seeded a ledger row with no manifest, so its setup now sets run_kind backfill; its assertions are unchanged. Daily verification of a recovered run is filed as a separate story.
- 2026-11-05T23:20:18.813Z: touches-expansion: overlaps st-0248 (LEARNINGS.md, docs/decisions/0006-wet-area-within-5pp-on-live-water-check.md, docs/research/2026-11-05-wet-area-gap.csv, docs/research/2026-11-05-wet-area-measure.py, docs/research/2026-11-05-wet-area-summary.txt, src/wetland_change/verify/wo.py, stories/st-0248-alert-on-every-scheduled-run-that-does-n.md, stories/st-1a95-verify-a-run-that-a-later-run-recovered.md, stories/st-2cc2-stop-writing-s3-directory-markers-on-eve.md, stories/st-4fa1-add-bucket-lifecycle-and-object-content.md, stories/st-7047-decide-how-verify-s-exit-code-treats-sin.md, stories/st-9aff-implement-the-design-s-wet-area-clause-f.md, stories/st-b602-make-verify-s-verdict-reflect-the-verifi.md, stories/st-ca25-make-change-scoring-survive-a-failure-af.md, tests/test_verify.py) — coordinate or split
- 2026-11-05T23:20:18.815Z: touches-expansion: overlaps st-4fa1 (LEARNINGS.md, docs/decisions/0006-wet-area-within-5pp-on-live-water-check.md, docs/research/2026-11-05-wet-area-gap.csv, docs/research/2026-11-05-wet-area-measure.py, docs/research/2026-11-05-wet-area-summary.txt, src/wetland_change/verify/wo.py, stories/st-0248-alert-on-every-scheduled-run-that-does-n.md, stories/st-1a95-verify-a-run-that-a-later-run-recovered.md, stories/st-2cc2-stop-writing-s3-directory-markers-on-eve.md, stories/st-4fa1-add-bucket-lifecycle-and-object-content.md, stories/st-7047-decide-how-verify-s-exit-code-treats-sin.md, stories/st-9aff-implement-the-design-s-wet-area-clause-f.md, stories/st-b602-make-verify-s-verdict-reflect-the-verifi.md, stories/st-ca25-make-change-scoring-survive-a-failure-af.md, tests/test_verify.py) — coordinate or split

## Questions
