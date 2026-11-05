---
id: st-357a
title: Complete the failed-scene retry path
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [README.md, docs/decisions/0004-baseline-uses-earlier-observations.md, src/wetland_change/cli.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/verify/freshness.py, tests/test_backfill.py, tests/test_cli.py, tests/test_ledger.py, tests/test_manifest.py, tests/test_pipeline.py, tests/test_verify_freshness.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

After three failed attempts exhausted_keys (src/wetland_change/ledger.py:238) drops a scene and the daily run reports nothing, with no requeue command. One DNS failure failed 25 scenes in a single backfill pass, so the trigger is real. Separately run_once rescores only dates written in that run, so a retried scene on an earlier date leaves later change files stale against a full rescore. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 6.

## Acceptance Criteria

- [ ] An exhausted item can be requeued by a CLI command without editing the ledger
- [ ] Exhausted items are counted in the run manifest and fail the freshness check while unresolved
- [ ] Storing a scene with an earlier acquisition date rescores later stored dates of the same polygon and month
- [ ] A test retries a failed scene and shows the stored change files equal a full rescore

## Implementation Plan

## Findings from the worktree (verified against code at 73f4de0)

- All story pointers hold. `exhausted_keys` is at `src/wetland_change/ledger.py:238`. `run_once` (`src/wetland_change/pipeline.py:~262`) scores only `written_dates`, the UTC dates of scenes written in that run. `score_changes` (`pipeline.py:~175`) builds each date's baseline from the same polygon, the same month of year and strictly earlier dates (ADR 0004).
- `cli.py` has no requeue command. `RunManifest` (`src/wetland_change/manifest.py`) has no exhausted count. `freshness_checks` (`src/wetland_change/verify/freshness.py`) returns `[newest, ES per tile, CDSE per tile]` and ignores failed rows.
- No prerequisite is missing. The change touches `ledger.py`, `manifest.py`, `pipeline.py`, `verify/freshness.py` and `cli.py`, plus docs.

## Design

- **Requeue is an append-only ledger row.** The `requeue` command writes, for each exhausted item, a copy of its latest failed row with `attempts=0`, a new `run_id`, `processed_at=now` and `error="requeued; previous error: ..."`. The status stays `failed` and `run_kind` is kept. `retry_ids` then picks the item up, because `attempts < MAX_ATTEMPTS`. `attempts_so_far` returns 0, so the item gets three fresh attempts. The ledger is never edited, only appended to, which keeps ADR 0003 intact.
- **Exhausted means unresolved.** An exhausted item is one whose latest row is `failed` with `attempts >= MAX_ATTEMPTS`. Any later succeeded row or requeue row resolves it. A new helper, `exhausted_ids`, lists them.
- **Manifest.** `RunManifest` gains `exhausted: int` and `exhausted_items: list[str]`. `run_once` and `backfill_once` fill them from the final ledger read that already computes `watermark_after`, so no extra S3 reads are added. A scene that fails its third attempt in this run counts in both `failed` and `exhausted`. `RunManifest` also gains `requeued_items: list[str]`, filled by the requeue command.
- **Freshness.** A new check, `freshness_exhausted_items`, passes only when the exhausted count is 0. It is not windowed, since an exhausted item stays unresolved until requeued and succeeded. Its detail lists the ids. It sits second in `freshness_checks`: `[newest, exhausted, ES..., CDSE...]`.
- **Rescore.** `score_changes` gains `rescore_later: bool = False`. When it is true and `dates` is given, `wanted` is widened to every stored date `d'` that has a row for polygon P and month M such that some date in `dates` has a row for (P, M) and is earlier than `d'`. M is the same month-of-year expression the history filter uses, and the match crosses years because the baseline does. `run_once` passes `rescore_later=True`. `score_once` and `backfill_once` are unchanged.

## Steps

1. **Rescore later dates (`src/wetland_change/pipeline.py`).**
   - Add `rescore_later` to `score_changes` and pass it from `run_once`.
   - Tests in `tests/test_pipeline.py`:
     - A pure-function test of the date expansion (an earlier stored date adds later same polygon and month dates, and not other months or polygons).
     - The retry regression test required by AC4. Run 1 has A (earlier date) broken and B (later date, flagged against a 6-value October baseline). Run 2 has A fixed. After run 2, snapshot the bytes of every `changes/**` file, run a full `score_changes(store, min_valid_fraction=...)` with no `dates` argument, and assert the same file set and identical bytes. Run it red first, with `rescore_later` off, to prove it fails.
2. **Exhausted accounting and the freshness check.**
   - `ledger.py`: add `exhausted_ids(ledger, *, max_attempts=MAX_ATTEMPTS) -> list[str]`.
   - `manifest.py`: add `exhausted: int = 0`, `exhausted_items: list[str]` and `requeued_items: list[str]`, plus a `KIND_REQUEUE = "requeue"` constant.
   - `pipeline.py`: in `run_once` and `backfill_once`, read the final ledger once and reuse it for `watermark_after` and the exhausted fields.
   - `verify/freshness.py`: add `CHECK_EXHAUSTED` and `exhausted_items_check(ledger)`, and wire it into `freshness_checks`.
   - Tests:
     - `tests/test_ledger.py`: `exhausted_ids` returns items at attempts >= 3 and drops them once a success supersedes them.
     - `tests/test_pipeline.py`: extend `test_failed_scene_is_recorded_and_retried_three_times` so the third failure sets `manifest.exhausted == 1` and `exhausted_items == [id]`, and the fourth run, which discovers 0 and fails 0, still reports `exhausted == 1`.
     - `tests/test_verify_freshness.py`: the check fails with the ids in its detail and passes when none are exhausted. Update the ordering test.
     - `tests/test_cli.py`: `freshness` exits 3 with `FAIL freshness_exhausted_items` when the ledger holds an exhausted item.
3. **Requeue command.**
   - `ledger.py`: add `requeue_entries(ledger, item_ids, *, run_id, processed_at) -> list[LedgerEntry]`. It raises `ValueError` for an id that is not currently exhausted, and when `processed_at` is not after the item's latest `processed_at`, because the append would otherwise be silently ignored.
   - `pipeline.py`: add `requeue_once(cfg, *, item_ids, all_exhausted, store, now, config_path, output_root_override)`. It writes the ledger parts and a manifest of kind `requeue` with `requeued_items`. It refuses a run id that is already used.
   - `cli.py`: add `requeue [ITEM_ID ...] [--all]` with `--config`, `--output-root` and `--now`. It prints the manifest JSON. It raises `BadParameter` for no ids and no `--all`, for an unknown or non-exhausted id, and for an empty `--all`.
   - Tests:
     - `tests/test_ledger.py`: the round trip makes `retry_ids` contain the item, `exhausted_keys` empty and `attempts_so_far` 0, and a non-exhausted id is rejected.
     - `tests/test_pipeline.py`: after three failures, `requeue_once` followed by `run_once` with the scene fixed (the same `FakeClient` with a corrected href) processes it, the ledger ends succeeded, and `exhausted` is 0.
     - `tests/test_cli.py`: `requeue --help` lists options, the command works end to end, error paths exit 2, and `requeue` appears in the help command list and in `test_output_root_listed_on_every_command`.
4. **Docs.**
   - Update the `README.md` command list and freshness description (~line 173-200). Check `tests/test_readme.py` for any command-list assertions.
   - Add an addendum to `docs/decisions/0004-baseline-uses-earlier-observations.md` saying that `run_once` also rescores later stored dates of the same polygon and month.
   - Update the `cli.py` module docstring.

## Verification (the order from AGENTS.md)

```
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src scripts
uv run pytest -q
```

## Notes

- If a retried item has been unpublished from Earth Search, `retry_ids` finds nothing and the item stays failed with `attempts=0`, not exhausted. This is out of scope, and the plan does not change it.
- The code makes 3 attempts in total, where the design says 3 retries. The story does not ask to change that.

## Implementation Notes

- 2026-11-05T11:34:20.000Z: Commit 140fa20. Gates on the branch: ruff, format and mypy exit 0; pytest exit 0 in default mode and with GITHUB_ACTIONS=true. Behaviour to know: freshness_exhausted_items does not consult run_kind, so an item exhausted during backfill_once also fails the freshness check and retry_ids never retries it until someone runs requeue. The check is not windowed, so one exhausted item keeps freshness exiting 3 until it succeeds or is requeued. A requeued item that Earth Search has since unpublished stays failed with attempts=0 and does not count as exhausted. The code makes 3 attempts in total where the design says 3 retries; left unchanged. Requeue --now accepts zone-less values only, matching the other commands.

## Questions
