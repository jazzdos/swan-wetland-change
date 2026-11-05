---
id: st-5bbc
title: Make verify default to the latest daily run
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [.github/workflows/verify.yml, README.md, src/wetland_change/cli.py, src/wetland_change/verify/run.py, tests/test_verify.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

latest_run_id (src/wetland_change/verify/run.py:83-93) never reads kind, so on a backfill-seeded bucket the weekly verify can target a backfill chunk of tens of scenes and reach its 20 minute step timeout. Verdict PLAUSIBLE: time per scene on a runner is unknown. Evidence: docs/research/2026-11-04-milestone-2-review.md L4.

## Acceptance Criteria

- [ ] verify without --run-id selects the newest manifest of kind run with processed above zero
- [ ] A test with a newer backfill manifest shows the daily run is selected

## Implementation Plan

1. Verified pointers: `latest_run_id` is at src/wetland_change/verify/run.py:97-111 (story said 83-93; shifted but unchanged in logic). It reads only `processed`. `RunManifest.kind` defaults to "run" (src/wetland_change/manifest.py:49); `RUN_KIND_RUN = "run"` and `RUN_KIND_BACKFILL = "backfill"` live in src/wetland_change/ledger.py:32-33 (run.py already imports `read_ledger` from that module). The only caller is the `verify` command in src/wetland_change/cli.py:300; its `--run-id` override is untouched, so an explicit backfill id can still be verified.
2. RED, tests/test_verify.py (next to the other `latest_run_id` tests, ~line 540; `latest_run_id`, `OutputStore`, `Path` already imported):
   - `test_latest_run_id_skips_a_newer_backfill_manifest`: write runs/20261029T100000Z.json as `{"processed": 1, "kind": "run"}` and runs/20261030T100000Z.json as `{"processed": 40, "kind": "backfill"}`; assert result is "20261029T100000Z". Proves the daily run is chosen over a newer backfill chunk (AC 2). Fails today.
   - `test_latest_run_id_treats_a_manifest_without_kind_as_a_run`: runs/20261029T100000Z.json `{"processed": 1}` (legacy, no kind), newer runs/20261030T100000Z.json `{"processed": 5, "kind": "backfill"}`; assert "20261029T100000Z". Proves manifests written before `kind` existed still count as daily runs.
   - `test_latest_run_id_returns_none_when_only_backfills_processed`: single backfill manifest with processed 3; assert None. Proves the no-eligible-run path feeds the CLI "no run with processed scenes" error rather than selecting a backfill.
3. GREEN, src/wetland_change/verify/run.py: import `RUN_KIND_RUN` from `wetland_change.ledger` (extend the existing `from wetland_change.ledger import read_ledger`). In `latest_run_id`, after parsing JSON, take `manifest = json.loads(raw)`; compute `processed = int(manifest.get("processed", 0))` and `kind = manifest.get("kind", RUN_KIND_RUN)` inside the existing try; skip the manifest unless `kind == RUN_KIND_RUN and processed > 0`. Keep the ManifestReadError behaviour and the malformed-JSON skip unchanged. A non-dict JSON (e.g. a list) already raises AttributeError, so extend the except to `(ValueError, TypeError, AttributeError)` only if a test demonstrates it; otherwise leave as is. Update the docstring to say "Newest daily run (kind run) that processed at least one scene; backfill chunks and no-op runs are skipped."
4. cli.py: update the `--run-id` help to "Defaults to the latest daily run (kind run) with processed scenes" and the BadParameter text to "no daily run with processed scenes in the output root". Check `grep -rn "no run with processed" tests` and update any assertion that matches the old message.
5. Existing test `test_scenes_for_run_and_latest_run_id` must still pass (built run has kind "run").
6. Verification, in order: `uv run ruff check src tests scripts`; `uv run ruff format --check src tests scripts`; `uv run mypy src scripts`; `uv run pytest -q`. No data/SOURCES.md change (no new dataset). No LEARNINGS.md hypothesis needed.

## Orchestrator amendments

1. The docs that say "latest run" change to "latest daily run": README lines 94, 139 and 197, and the header comment and step name in `.github/workflows/verify.yml`.
2. The orchestrator commits after the review gate; the implementer commits nothing.
3. Known consequence, accepted by AC1: a bucket holding only backfill manifests now makes `verify` without `--run-id` exit with the bad-parameter error, so the weekly workflow goes red and files an issue until the first daily run processes a scene. An explicit `--run-id` still verifies a backfill chunk.

## Implementation Notes

- 2026-11-05T13:05:40.636Z: Built and verified offline: ruff, format, mypy, pytest exit 0, default and GITHUB_ACTIONS=true. Live tests not run. Consequence accepted by AC1: a bucket holding only backfill manifests makes verify without --run-id exit with the bad-parameter error, so the weekly workflow goes red and files an issue until the first daily run processes a scene. An explicit --run-id still verifies a backfill chunk. Touches README.md, cli.py and verify.yml beyond the story's list, for the help text and the 'latest daily run' wording. A non-object JSON manifest still raises AttributeError in latest_run_id, as it did before; not changed here.

## Questions
