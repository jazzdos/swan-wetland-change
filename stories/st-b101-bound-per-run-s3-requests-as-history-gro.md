---
id: st-b101
title: Bound per-run S3 requests as history grows
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [.github/workflows/pipeline.yml, README.md, docs/decisions/0003-fixed-schema-ledger.md, src/wetland_change/cli.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/outputs/geoparquet.py, src/wetland_change/pipeline.py, src/wetland_change/stac/catalogue.py, tests/test_catalogue.py, tests/test_change_outputs.py, tests/test_cli.py, tests/test_ledger.py, tests/test_pipeline.py, tests/test_workflows.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

read_ledger makes a HEAD and a GET per ledger part (src/wetland_change/ledger.py:186) and a backfill-seeded bucket holds about 1172 parts. A daily run reads the ledger three or more times, GETs every observation in scoring and rewrites every catalogue object, about 30k sequential requests on a processed day and growing. Verdict PLAUSIBLE: counts were measured on a fake S3 and runner-to-bucket latency is unknown. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 7.

## Acceptance Criteria

- [ ] A daily run reads the ledger once and passes the table to scoring and catalogue building
- [ ] Ledger parts are compacted so read_ledger needs a bounded number of requests
- [ ] The pipeline workflow builds the catalogue once per run
- [ ] The catalogue writes only items added or changed since the previous run

## Implementation Plan

# st-b101: Bound per-run S3 requests as history grows

Verified against the worktree (HEAD 3488070). The finding's line numbers are stale but the problem is real. Facts that shape the plan:

- `read_ledger` (src/wetland_change/ledger.py) lists `ledger/` and does one `read_bytes` per `.parquet` part. The backfill writes one part per scene, and `run_once` writes one per scene plus one for rejects.
- `run_once` (src/wetland_change/pipeline.py ~L316) reads the ledger at the start and again at ~L384 (`final`). Then `build_and_write` (stac/catalogue.py L297) reads it a third time. `backfill_once` reads it twice and `requeue_once` twice. `verify` (verify/run.py L71) and `freshness` read it once each, which is acceptable.
- `score_changes` does not read the ledger. It lists `observations/` and GETs every `obs_*.parquet`. The tests seed observation files directly with no ledger rows, so scoring must stay store-driven. AC1 is therefore met by reading the ledger once in `run_once` and passing the table to catalogue building. There is nothing to pass to scoring, and that is stated in the PR.
- `write_catalogue` rewrites every item JSON, the collection, the catalog and items.parquet on every run, at roughly 5 S3 requests per object.
- `.github/workflows/pipeline.yml` builds the catalogue inside `wetland-change run` (`run_once`) and again in the `build-catalogue` step after `verify`. The second build exists so the new run's verification report is linked.
- tests/test_workflows.py pins the step order fetch < run < verify < build-catalogue < commit, the `RUN_PATTERN` regex `wetland-change run --output-root s3://`, and the condition `!cancelled() && steps.manifest.outputs.processed > 0` on the catalogue step.

## Design

1. **Single ledger read per run.** Add `read_ledger_parts(store) -> tuple[pa.Table, list[str]]` (the table plus the part paths it came from) and make `read_ledger` a wrapper. Add `ledger_with(ledger, entries) -> pa.Table` (concat with `entries_to_table`). `run_once`, `backfill_once` and `requeue_once` read once at the start, keep the list of `LedgerEntry` they write, and compute `final = ledger_with(ledger, new_entries)` in memory instead of calling `read_ledger` again. `build_and_write(store, *, base_url, ledger=None)` uses the passed table and reads from the store only when `ledger` is None. `run_once` passes `final`.
2. **Compaction.** Add `compact_ledger(store, ledger, paths, *, run_id, min_parts=COMPACT_MIN_PARTS) -> list[str]` to ledger.py.
   - Below `min_parts` paths it does nothing.
   - Otherwise it writes the complete table, with all rows kept so watermark, attempts and history are unchanged, to `ledger/compacted/ledger_compact_<run_id>.parquet`, then deletes every path in `paths` (including older compacted files) except the new one.
   - The write comes first, so a crash between write and delete leaves duplicate rows rather than lost rows. `read_ledger_parts` therefore drops exact duplicate rows, keyed on (item_id, run_id, processed_at), via a pyarrow `filter` built from a Python set. This only matters when a compacted file coexists with other parts.
   - The filename does not start with `ledger_<run_id>_`, so `_refuse_reused_run_id` is unaffected. The `run_id` is unique per run, so the name cannot collide with a part.
   - Result: `read_ledger` costs 1 list plus (1 compacted file + fewer than `COMPACT_MIN_PARTS` fresh parts) GETs, bounded.
   - `run_once` and `backfill_once` call it last, after the manifest and catalogue, passing the in-memory `final` and `paths + parts written this run`. A compaction failure is logged with `logger.exception` and does not fail the run, because the ledger stays valid.
   - A new CLI command `compact-ledger` runs it on demand (`min_parts=1`) to migrate a backfill-seeded bucket of about 1172 parts. `COMPACT_MIN_PARTS = 25`.
   - `RunManifest.ledger_files` keeps naming the parts written by the run. A later compaction can merge them, so say so in the docstring and ADR 0003.
3. **Incremental catalogue writes.** `write_catalogue` computes the serialized bytes of every object (catalog, collection, items, items.parquet) in memory as now. It loads a small index `stac/write-index.json`, `{"base_url": ..., "objects": {key: sha256}}`, and does one `store.list_files("stac")`. It writes an object only if the index base_url differs, the key is not in the listing, or the sha256 differs from the index. It writes the index last, so a crash leaves a stale index that causes a rewrite and never a skipped object. The returned list is the sorted list of objects actually written; the index file is excluded. A no-op rerun writes nothing, and an added or changed item writes that item plus collection, catalog and items.parquet. Changed means "the item JSON bytes differ", which covers a new `changes` or `verification` asset. The index is not linked from the catalogue, so `validate_all` is unaffected.
4. **Catalogue built once per workflow run.**
   - `run_once` gets a `build_catalogue: bool = True` parameter and the CLI `run` gets `--catalogue/--no-catalogue` (default on, so library and test behaviour is unchanged).
   - `ensure_publishable_base_url` still runs at the start of `run_once` either way.
   - pipeline.yml passes `--no-catalogue` to `run` and keeps the single `build-catalogue` step after `verify`, which links this run's verification report. Rename the step and fix the comments ("Build the catalogue once, after verify, so it links this run's report").
   - Update tests/test_workflows.py: the run step has `--no-catalogue`, `RUN_PATTERN` still matches (the flag goes after `--output-root`; the regex needs the literal `run --output-root s3://`, so put `--no-catalogue` after the root), and exactly one step invokes a catalogue build.
5. **Docs.** Add an addendum to docs/decisions/0003-fixed-schema-ledger.md on compaction, in-memory final table and the dedupe rule. Add the `compact-ledger` command and `--no-catalogue` to README.md wherever the CLI is listed (grep for `build-catalogue`). tests/test_readme.py may check the CLI docs, so run it.

## Tests (each proves one behaviour)

- tests/test_ledger.py
  - `read_ledger_parts` returns the paths read.
  - `ledger_with` equals a fresh `read_ledger` after `write_ledger` of the same entries.
  - `compact_ledger` with N small parts leaves one file, the read table is row-equal (same `latest_entries`, `watermark`, `seen_keys`), and it is a no-op below the threshold.
  - A crash-simulated state (compacted file plus the original parts) reads without duplicates.
  - Requests are bounded: a counting `OutputStore` subclass shows `read_ledger` makes at most 1 + `COMPACT_MIN_PARTS` `read_bytes` calls after 100 parts are compacted.
- tests/test_catalogue.py
  - Second `build_and_write` writes `[]` and leaves bytes identical.
  - Adding one ledger item writes only that item plus collection, catalog and items.parquet, and the other item JSONs are not rewritten (assert via a store that records `write_bytes` keys).
  - A changed `available` set (a new changes or verification file) rewrites only the affected item.
  - A deleted catalogue object is restored.
  - A changed base_url rewrites everything.
  - `build_and_write(store, base_url, ledger=table)` makes zero ledger `read_bytes` calls.
  - Update `test_rebuild_is_byte_identical` and `test_written_files_are_exactly_the_succeeded_items` for the new return semantics (first build lists everything, rebuild lists nothing).
- tests/test_pipeline.py or tests/test_run_catalogue.py
  - Wrap `OutputStore.read_bytes` or monkeypatch `wetland_change.pipeline.read_ledger` and `wetland_change.stac.catalogue.read_ledger` with a counter, and assert `run_once` reads the ledger exactly once, including when scenes are processed and when the day is a no-op.
  - `run_once(build_catalogue=False)` writes no `stac/` files.
  - The same check for `backfill_once` and `requeue_once`.
  - After enough runs with a patched low `COMPACT_MIN_PARTS`, `ledger/` holds one compacted file plus fresh parts, and the next run's `discover` result is unchanged.
- tests/test_cli.py: `run --no-catalogue` produces no `stac/` output and `run` by default still does; the `compact-ledger` command compacts and reports the counts.
- tests/test_workflows.py: as in design item 4.

## Verification (AGENTS.md order)

```
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src scripts
uv run pytest -q
```

## Orchestrator amendments (settled before build)

These override the plan text above where they differ.

1. Crash dedupe compares whole rows, not (item_id, run_id, processed_at). Rows in one run share `processed_at`, so a key dedupe could drop a legitimate later row and change `latest_entries`. Rows are keyed on `repr` of the row so null and NaN values compare equal.
2. `compact_ledger` reads the compacted file back and checks its row count before any delete, and returns [] without deleting when the table has no rows. The bucket is unversioned, so a delete is permanent.
3. `read_ledger_parts` re-lists once on FileNotFoundError, so an operator CLI read that races a compaction does not fail.
4. `_refuse_reused_run_id` also checks the `run_id` column of the ledger table, because compaction removes the part names of an interrupted run that has no manifest. It takes the already-read table and paths, which also removes a second ledger listing.
5. AC1 "to scoring": `score_changes` gains `ledger: pa.Table | None = None`. With `dates` and a ledger, it skips an observation file only when the ledger's `observation_path` and `datetime` show a UTC month outside the months of `dates`. Files with no ledger row are always read. `dates=None` reads everything. This is safe because `_with_later_dates` matches on polygon and month, and the history filter matches on month, so the months of `dates` are closed under both. `run_once` passes `final`; `backfill_once` keeps its full read.
6. The workflow's catalogue step moves to `if: !cancelled()`. No other workflow builds the catalogue, and today `run` builds it every day, which is how a zero-processed day picks up reports from `verify.yml` and any CLI backfill. Incremental writes make a no-op build cheap. Verify and commit keep the processed condition.
7. `run_once` and `backfill_once` pass `min_parts=COMPACT_MIN_PARTS` explicitly from the pipeline namespace, because a default argument binds at definition and a monkeypatch would not reach it.

The in-process single read holds per `run_once`. With `--no-catalogue`, the workflow's `run`, `verify` and `build-catalogue` steps are separate processes that each read the ledger once, bounded by compaction.

## Implementation Notes

- 2026-11-05T12:56:04.395Z: Built and verified offline at this commit: ruff, format, mypy, pytest exit 0, default and GITHUB_ACTIONS=true. Live tests not run. Nothing ran against AWS, so compaction has only run on local stores.

Per process: run_once, backfill_once and requeue_once list ledger/ once and read each part once. Scoring, build_and_write and compaction reuse the table. Compaction reads back only the file it wrote. The workflow's run, verify and build-catalogue steps are separate processes that each read the ledger once, bounded by compaction: at most one compacted file plus fewer than 25 parts between compactions, plus the current run's.

Compaction deletes ledger parts from a public, unversioned bucket. The first run against a backfill-seeded bucket merges about 1172 parts and deletes them with no operator step. A compaction failure is logged and does not fail the run, so a repeated failure would show only in logs while part count grows.

Deviations from the plan: the catalogue step moved from the processed condition to !cancelled(), because no other workflow builds the catalogue and a zero-processed day needs to pick up verify.yml reports. A run that crashes now still attempts a catalogue build. AC1 'to scoring' is met by a month filter: scoring skips observation files the ledger places outside the months of the scored dates and always reads files with no ledger row. Observation GETs still grow with history, at about one twelfth of the store. backfill_once keeps a full observation read. If AOI polygon geometry changed between scenes, the geometry in a change file could come from a different item than under a full read; the AOI is fixed today.

Added beyond the ACs: read-back row count check before deletes, re-list on a vanished part, whole-row crash dedupe, and _refuse_reused_run_id also checking the run_id column.

## Questions
