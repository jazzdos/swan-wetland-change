---
id: st-1b50
title: Stop re-logging unchanged rejected items
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [src/wetland_change/catalogue/search.py, src/wetland_change/cli.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, tests/test_ledger.py, tests/test_pipeline.py, tests/test_search.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-06
---

## Description

A guard-rejected item stays in the created window while it is the newest item, so each run writes another rejected row and ledger part (src/wetland_change/pipeline.py:309-318). Growth is bounded and adds to the S3 request growth. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md L8.

## Acceptance Criteria

- [ ] An item rejected with the same updated timestamp is not written to the ledger again

## Implementation Plan

## Findings (verified in /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-1b50 at bde363d)

- The rejected write is in `src/wetland_change/pipeline.py`, twice: `run_once` (about L388-403) and `backfill_once` (about L612-627). Both build `rejected_entry(item_id, reason, ...)` for every `discovery.rejected` pair, call `write_ledger(..., part=next_part)`, and add to `new_entries`.
- `discover()` in `src/wetland_change/catalogue/search.py` is where items are rejected (the `except (ItemGuardError, KeyError, TypeError, ValueError)` branch). `Discovery.rejected` is `list[tuple[str, str]]` (id, reason), and `tests/test_search.py` relies on that shape, so it must stay.
- `rejected_entry` in `src/wetland_change/ledger.py` stores `updated=None`, so the ledger cannot currently tell whether a rejection is unchanged. The reason is stored in the `error` column.
- `latest_entries(ledger)` gives the newest row per item (sorted by processed_at, run_id). `seen_keys` and `exhausted_keys` are the model for a new `rejected_keys`.
- Rejected rows have null `created`, so `watermark` is unaffected. Storing `updated` on rejected rows has no other consumer: `seen_keys` filters on `succeeded`, `exhausted_keys` on `failed`.
- The ledger is already read once per run (`read_ledger_parts`). The new set is derived from that table, so there is no second read.

## Design

1. `ledger.py`: `rejected_entry` gains optional `updated: dt.datetime | None = None` and stores it. New `rejected_keys(ledger) -> set[tuple[str, datetime, str]]` returns (item_id, updated, error) for items whose newest row is status `rejected` with non-null `updated` and non-null `error`. Old rejected rows (null `updated`) never match, so each is re-logged exactly once with `updated` populated, then deduped. This is the migration path.
2. `search.py`: `discover()` gets `rejected_seen: Collection[tuple[str, datetime, str]] = frozenset()`. In the rejection branch it best-effort parses `props["updated"]` (helper `_updated_or_none`, never raises, returns None if missing or unparseable). If `(item_id, updated, reason)` is in `rejected_seen`, it increments `result.skipped_seen`, logs at debug, and does not append to `rejected`. Otherwise it appends as today and records `result.rejected_updated[item_id] = updated` on a new `Discovery.rejected_updated: dict[str, datetime | None]` field (default empty dict). A changed `updated` or a changed reason does not match, so the item is re-evaluated and logged.
3. `pipeline.py`: a small helper `_rejected_entries(discovery, *, run_id, now, run_kind)` replaces both inline list comprehensions and passes `updated=discovery.rejected_updated.get(item_id)`. Both `run_once` and `backfill_once` pass `rejected_seen=rejected_keys(ledger)` to `discover`. The existing `if discovery.rejected:` guard means that when every candidate was an unchanged rejection, no part is written, `next_part` stays 0, and no empty ledger file appears.
4. Reporting: no manifest schema change. Skipped unchanged rejections are counted in the existing `skipped_seen`. `manifest.rejected` (from `len(discovery.rejected)`) then means rejections newly written to the ledger this run, which equals the rows appended. Document this in the `discover` docstring and the `RunManifest` field comment. `discovered`, `ledger_files` and the recovered-manifest fields are unchanged.

## Steps (TDD)

1. Tests first, in `tests/test_ledger.py`:
   - `rejected_entry(..., updated=T)` stores `updated`.
   - `rejected_keys` returns the key when the newest row is a matching rejection.
   - `rejected_keys` excludes the item when a later row is `succeeded` or `failed`.
   - `rejected_keys` excludes rows with null `updated`.
   - `rejected_keys` returns an empty set for an empty ledger.
2. Tests, in `tests/test_search.py`:
   - A rejected item whose (id, updated, reason) is in `rejected_seen` is not in `result.rejected`, is counted in `skipped_seen`, and `rejected_updated` has no entry for it.
   - The same item with a different `updated` is still rejected, and `rejected_updated[id]` equals the parsed `updated`.
   - The same `updated` with a different reason is still rejected.
   - An item with a missing or invalid `updated` is still rejected, with `rejected_updated[id]` None.
   - The existing tuple-shape assertions still pass.
3. Tests, in `tests/test_pipeline.py`, using `_run`, `_wrong_collection`, `FakeClient` and `_counting_store`:
   - Run twice with a wrong-collection item and a later `now`. The second run has `manifest.rejected == 0`, `skipped_seen == 1`, `ledger_files == []`, and no new ledger parquet file. The ledger still has exactly one rejected row for the item, and that row has the item's `updated` set.
   - Rejected plus a new good scene on run 2: only the scene part is written, as `_00000` (the rejected part is absent), and `ledger_files` has one entry.
   - Same item id with a changed `properties.updated` on run 2: a second rejected row is written with the new `updated`, `manifest.rejected == 1`.
   - A legacy rejected row (written via `rejected_entry` without `updated`) is re-logged once on the next run, then skipped on the run after.
   - Ledger read and list count stays one (reuse `_assert_one_ledger_read`) on a run that skips an unchanged rejection.
   - Backfill: `backfill_once` twice with an unchanged rejected item writes no second rejected row.
   - Update `test_run_once_lists_and_reads_the_ledger_once_with_a_rejected_item` only if its expectations change. It should not, because that item is first-seen.
   - Confirm that the tests in steps 1-3 fail before implementation.
4. Implement `ledger.py`, then `search.py`, then `pipeline.py` as in the design. Keep `Discovery.rejected` as `list[tuple[str, str]]`.
5. Update comments and docs: the `rejected_entry` docstring (it currently says "re-logged while it is in range", which becomes "logged once per updated timestamp and reason"), the `discover` docstring, and the `RunManifest.skipped_seen` comment. Add a one-line note to `LEARNINGS.md` only if an existing section already covers ledger behaviour. Do not edit `stories/**`.
6. Run the gates, one per line: `uv run ruff check src tests scripts`; `uv run ruff format --check src tests scripts`; `uv run mypy src scripts`; `uv run pytest -q`; `GITHUB_ACTIONS=true uv run pytest -q`; and `uv run pytest -q -o addopts="-m 'not live'"` for a count. No live tests. Commit nothing.

## What the tests prove

- The same (id, updated, reason) never produces a second row or part: the acceptance criterion.
- A changed `updated` or reason is still logged: nothing is silently suppressed.
- No empty ledger part is written.
- One ledger read per run is preserved.
- Existing manifest fields keep their names and meaning, and old ledgers migrate with a single re-log.
## Orchestrator amendments (2026-11-06, settled before build)

1. Commit nothing; the orchestrator commits after the review gate. No AWS, no terraform, no live tests; pytest judged by exit code with addopts kept; GITHUB_ACTIONS=true run as well.
2. Timestamp equality is the crux: the key compares the ledger's stored `updated` with the parsed STAC `updated`. The two-run pipeline test must go through the real store write and read so that a precision or timezone mismatch (ns against us, naive against aware) would fail it rather than silently re-log every run.
3. If README.md or the design describe the manifest's `rejected` or `skipped_seen` fields, update them to the new meaning (`rejected` counts rows newly written; `skipped_seen` also counts unchanged rejections). The recovered-manifest path already counts rejected rows written by the run, which matches.

## Implementation Notes

- 2026-11-06T00:18:18.065Z: Committed 7b6c5e2. Unchanged rejections keyed on (item_id, updated, reason) are skipped and counted in skipped_seen; rejected counts rows newly written. rejected_entry stores updated; rejected_keys added; Discovery.rejected_updated added; the discover CLI also passes rejected_seen. One ledger read per run kept; no empty part written; no manifest schema change. Legacy null-updated rows are re-logged once. Gates: ruff check, ruff format --check, mypy, pytest -q and GITHUB_ACTIONS=true pytest -q all exit 0; 737 passed, 9 deselected. Filed a bug for a null updated or created crashing discover with AttributeError (preexisting).

## Questions
