---
id: st-0647
title: Add the golden-run idempotency test
type: feature
epic: st-1d45
priority: P2
depends_on: []
touches: [pyproject.toml, tests/test_golden_run.py, tests/test_golden_run/test_fixture_run_observation_rows_golden.yml, uv.lock]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Verification matrix row "Incremental and idempotent" (design): a pytest-regressions golden run, watermark replay, byte-identical outputs on rerun, and no duplicates after replay. Offline only. Use the fixture (`tests/conftest.py`, `tests/fixtures/thomsons_20261027`) and the fake-client pattern in `tests/test_pipeline.py`. `run_id` derives from `now` (`new_run_id` in `src/wetland_change/manifest.py`), so compare runs made with the same `now`.

## Acceptance Criteria

- [ ] pytest-regressions is a dev dependency and `uv sync --locked` succeeds.
- [ ] Offline test: two `run_once` calls with the same `now` into two fresh stores produce byte-identical observation and ledger files.
- [ ] Offline test: a second `run_once` into the same store processes 0 items and leaves every existing file's bytes unchanged.
- [ ] Offline test: after a run whose discovery window overlaps already-processed items (the one-day watermark overlap), no item id and `updated` pair appears twice among the ledger's processed rows.
- [ ] A golden file under `tests/` captures the fixture run's observation rows through pytest-regressions.

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-0647)

- `tests/conftest.py`, `tests/fixtures/thomsons_20261027/` and the fake-client pattern in `tests/test_pipeline.py` (`FakeClient`, `FakeSearch`, `_config`, `_polygons`, `_run`, `NOW`) all exist. `FakeClient.search` ignores filters and returns all its items, so it models a discovery window that overlaps processed items.
- `run_once` (`src/wetland_change/pipeline.py`) searches from `watermark - cfg.stac.watermark_overlap_days` (1 day, `config/*.toml`) and skips items whose `(item_id, updated)` is in the ledger's succeeded set. `run_id = new_run_id(now)` (`%Y%m%dT%H%M%SZ`). Observation files are `observations/year=YYYY/tile=T/obs_<item_id>.parquet`, ledger files `ledger/year=2026/ledger_<run_id>.parquet`. Observation bytes are deterministic (sorted rows, buffered write; `tests/test_geoparquet.py::test_rewrite_is_byte_identical`). Ledger `processed_at` is `now` and `source_item` is `json.dumps(sort_keys=True)`, so the same `now` gives the same bytes.
- Fixture item: id `S2C_T50HLK_20261027T022351_L2A`, created = updated = 2026-10-27T08:30:21.681Z.
- `pytest-regressions` is not yet in `pyproject.toml` or `uv.lock`. A scratch copy confirmed `uv lock` resolves it (pytest-regressions 2.11.0, plus pytest-datadir 1.8.0) offline-safely. `.gitignore` does not exclude `tests/` golden files. Ruff covers tests (E,F,I,B,UP, line length 88); mypy is `src` and `scripts` only.
- No prerequisite is missing, so the story is implementable as written.

## Steps

1. Add the dev dependency (`/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-0647/pyproject.toml`, `uv.lock`).
   - Add `"pytest-regressions>=2.5",` to `[dependency-groups].dev`, after `pytest>=8.0`.
   - Run `uv lock`, then `uv sync --locked`.
   - Proves AC1: the lockfile is consistent and sync succeeds.

2. Create `tests/test_golden_run.py`.
   - It imports the helpers from `tests.test_pipeline` (`FakeClient`, `_run`, `_polygons`, `NOW`). `tests.conftest` is already imported that way, so this works.
   - Use a store helper such as `OutputStore(str(root / "out"))` and a `_snapshot(store)` helper. `_snapshot` returns `{relpath: bytes}` over `store.list_files("observations") + store.list_files("ledger")`. It also asserts that both prefixes are non-empty.
   - `_run(tmp_path, ...)` puts output at `tmp_path/"out"`, so use distinct subdirectories (`tmp_path/"a"`, `tmp_path/"b"`) for fresh stores.

   Tests:
   - `test_same_now_gives_byte_identical_outputs`. Two `_run` calls with `NOW` into `tmp_path/"a"` and `tmp_path/"b"`, each with a deepcopy of `fixture_item`. Assert the sets of relative paths are equal and each file's bytes are equal. This proves AC2. Compare observation files and ledger files explicitly, not only the combined dict.
   - `test_second_run_same_store_processes_nothing_and_changes_no_bytes`. Run once at `NOW`, take a snapshot of the store, then run again into the same store at `NOW + 1 day`. Assert `(discovered, processed, failed) == (0, 0, 0)`, `skipped_seen == 1` and `observation_files == []`. Assert every file from the first snapshot is still present with identical bytes. A new ledger file for the second run may appear, so do not require the file set to be unchanged. Assert that files from the first snapshot are unchanged, and that no observation file was added. This proves AC3.
   - `test_watermark_overlap_does_not_duplicate_processed_rows`. Use a recording subclass or wrapper of `FakeClient` that stores the kwargs of each `search` call.
     - Run 1: `[A]` at `NOW`.
     - Run 2: `[A, B]` at `NOW + 1 day`, where B is a deepcopy of A with a new `id` (for example `..._B`) and later `created`/`updated`, for example `2026-10-28T08:30:21.681Z`.
     - Assert that run 2's main search had `query["created"]["gte"]` exactly one day before run 1's `watermark_after`. This shows the overlap window was really requested; derive the expected string from the watermark, formatted as isoformat with `+00:00` replaced by `Z`.
     - Assert run 2 has `discovered == 1` (B), `skipped_seen == 1` (A) and `processed == 1`.
     - Read the ledger with `read_ledger(store).to_pandas()`, keep rows with `status == "succeeded"`, and assert `df.duplicated(["item_id", "updated"]).sum() == 0` and that the item ids are `{A, B}`.
     - This proves AC4: A sits inside the overlap window but is not reprocessed or re-ledgered.
   - `test_fixture_run_observation_rows_golden(data_regression)`. Run once at `NOW`. Read the single observation file with `geopandas.read_parquet`. Build a list of dicts, one per row ordered by polygon_id, covering all `OBSERVATION_COLUMNS` plus `geometry.wkt`. Format values for a stable golden file: `datetime` as isoformat, floats rounded to 6 decimals, `NaN` as None, numpy scalars converted to Python types. Call `data_regression.check({"rows": rows})`. This proves AC5 and writes the golden file `tests/test_golden_run/test_fixture_run_observation_rows_golden.yml`.
     - Generate the golden once with `uv run pytest tests/test_golden_run.py --force-regen`.
     - Inspect it (one row, `polygon_id: ramsar-52`, `valid_fraction > 0.9`, `run_id: 20261029T100000Z`).
     - Rerun without the flag and confirm it passes.
     - Commit the yml.

3. Verify with `uv sync --locked`, `uv run pytest -q`, `uv run ruff check .` and `uv run ruff format --check .` (if the repo uses it). Also run `uv run mypy` (it covers src and scripts only, so it should be unaffected).

## What each test proves

- Byte-identical rerun (AC2), no-op second run (AC3), overlap with no duplicates (AC4), golden observation rows (AC5), lock and sync (AC1).

## Implementation Notes

## Questions
