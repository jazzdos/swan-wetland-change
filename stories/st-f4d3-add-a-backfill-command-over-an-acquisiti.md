---
id: st-f4d3
title: Add a backfill command over an acquisition date range
type: feature
epic: st-70d1
priority: P1
complexity: hard
depends_on: []
touches: [src/wetland_change/catalogue/search.py, src/wetland_change/cli.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, tests/test_backfill.py, tests/test_cli.py, tests/test_ledger.py, tests/test_pipeline.py, tests/test_search.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Add `wetland-change backfill --start --end` (design, Run stages and CLI list): run stages 1 to 6 over an acquisition-date range. Milestone 1 seeded its first watermark with a hand-written ledger row because no backfill existed (handoff, Deviations).

Current code: `run_once` in `src/wetland_change/pipeline.py` discovers by `created` at or after the watermark minus the overlap. `build_search_kwargs` and `discover` in `src/wetland_change/catalogue/search.py` run the query plus client-side cloud and intersection re-checks. `src/wetland_change/ledger.py` holds `watermark`, `seen_keys` and `retry_ids`. The CLI is typer in `src/wetland_change/cli.py`.

Needed:

- Search by acquisition `datetime` in [start, end] and skip items already in the ledger (same id and `updated`). Process the rest through the same per-scene path as `run`, writing observation files, ledger rows and a run manifest.
- Resumable: rerunning an interrupted backfill continues where it stopped.
- The daily run's watermark (newest `created` in the ledger) must not jump past items the daily run has not processed, even though backfilled items can carry recent `created` timestamps.
- A global `--output-root` override on `run`, `backfill` and `verify`, so the backfill spike can write to an absolute path without editing `config/pipeline.toml`. The manifest keeps the config file's digest and records the override.

Out of scope: change scoring, the catalogue, S3.

## Acceptance Criteria

- [ ] `uv run wetland-change backfill --help` exits 0 and lists `--start`, `--end` and `--output-root`.
- [ ] Offline test: a backfill over a fake STAC client holding items inside and outside [start, end] processes exactly the in-range items and writes one observation file per processed item.
- [ ] Offline test: repeating the same backfill into the same store writes no observation files, and its manifest reports 0 processed.
- [ ] Offline test: after a backfill whose items have `created` later than the previous watermark, a daily `run_once` still processes an item whose `created` falls between the old watermark and the backfilled items' `created`.
- [ ] Offline test: `run --output-root <tmp_path>` writes its manifest under `<tmp_path>`, and the manifest records the override root.
- [ ] Live test marked `live`: a backfill from 2026-10-26 to 2026-10-28 over the configured AOI processes at least one item into a temporary output root.

## Implementation Plan

# st-f4d3 plan: `wetland-change backfill --start --end` and `--output-root`

Worktree: `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-f4d3`. I checked every pointer in the story against the code and all of them hold:
- `run_once` in `src/wetland_change/pipeline.py` searches with `created >= watermark - overlap`.
- `build_search_kwargs` and `discover` in `src/wetland_change/catalogue/search.py` use `query` plus `sortby`, then re-check client-side.
- `src/wetland_change/ledger.py` holds `watermark` (the max `created` over all rows), `seen_keys`, `retry_ids` and `exhausted_keys`.
- `src/wetland_change/cli.py` is typer with `discover`, `run` and `verify`.
- The handoff seed row is status `seed` in `ledger/year=2026/ledger_seed.parquet`.

No prerequisite is missing. The baseline is green: pytest, ruff and mypy all pass. A live check on 2026-10-30 showed that Earth Search accepts `datetime=2026-10-26T00:00:00Z/2026-10-28T23:59:59.999999Z` and returns 6 c1 items acquired 2026-10-27. pystac-client passes that string through unchanged.

## Design decisions

1. **Acquisition range.** The STAC core `datetime` parameter carries a closed interval `[start, end]`, with both bounds timezone-aware and converted to UTC. `discover` also re-checks each item's `properties.datetime` client-side, because Earth Search can silently ignore filters. Out-of-range items count as `skipped_filter`.
2. **Watermark safety.** The ledger gets a new column `run_kind` (`"run"` or `"backfill"`), appended last to `LEDGER_SCHEMA`.
   - `watermark()` takes the max `created` only over rows that are not backfill rows. A null `run_kind` counts as a daily row.
   - `read_ledger` fills columns that a file predates with nulls, so Milestone 1 files and the seed file still read and still count.
   - `seen_keys`, `retry_ids`, `exhausted_keys` and `attempts_so_far` stay shared across both kinds.
   - A daily run may retry a failed backfill item by id. This cannot move the watermark past unprocessed items, because the same daily run also searches every `created` from `watermark - 1d` up to now.
3. **Resumability.** The backfill skips every item in `seen_keys | exhausted_keys`, i.e. the same id and `updated`.
   - It checkpoints the ledger after every scene, writing `ledger/year=YYYY/ledger_<run_id>_<part:05d>.parquet`. Rejected entries go in part 0, before any scene.
   - The manifest is written once, at the end.
   - Failed items under `MAX_ATTEMPTS` are not "seen", so a rerun picks them up again through the range search.
   - The daily `run_once` still writes one `ledger_<run_id>.parquet` at the end, as before.
4. **Manifest.** `RunManifest` gets four new fields, all with defaults:
   - `kind` (`"run"` or `"backfill"`)
   - `datetime_start`
   - `datetime_end`
   - `output_root_override` (the raw CLI string, or None)

   `config_sha256` stays the digest of the config file.
5. **CLI.**
   - `--output-root` is a `str` option, not a `Path`, so `s3://` URIs survive. It goes on `run`, `backfill`, `verify` and `discover`.
   - `backfill --start/--end` take `%Y-%m-%d` UTC dates and the end date is inclusive. The command passes `[start 00:00Z, end+1d - 1µs]` to `backfill_once` and rejects end < start with BadParameter before loading anything.
   - Help strings avoid square brackets because typer renders them as rich markup.
6. **Shared per-scene path.** `pipeline.py` gets `_process_one` (stages 2 to 6 plus a ledger entry), `_tally` and `_new_manifest`. Both `run_once` and `backfill_once` use them, and `process_scene` keeps its signature.

Known behaviour, recorded only and not changed here:
- A store holding only backfill rows has no daily watermark, so its next daily run searches without a `created` filter and skips the seen items.
- A full backfill leaves about one small ledger file per scene.

## Steps

1. **Search (batch 1, T1).** Add `datetime_range` to `build_search_kwargs` and `discover` in `src/wetland_change/catalogue/search.py`. Tests go in `tests/test_search.py`:
   - The kwargs carry the exact `datetime` string, with no `created` key.
   - Non-UTC bounds are converted to UTC.
   - A naive or reversed range raises ValueError.
   - With no range, the kwargs have no `datetime` key.
   - The client-side re-check keeps both boundary items, filters items 1 s before the start and 1 µs after the end, and rejects a malformed datetime.
2. **Ledger (batch 1, T2).** In `src/wetland_change/ledger.py`: add the `run_kind` column and constants, `part` paths, legacy-tolerant `read_ledger`, and the watermark that excludes backfill rows. Tests go in `tests/test_ledger.py`:
   - The part path format.
   - `run_kind` round-trips with "run" as the default.
   - The watermark ignores backfill rows.
   - The watermark is None when the ledger holds only backfill rows.
   - A file without the `run_kind` column (a seed row) reads to the full schema and still sets the watermark.
3. **Pipeline (batch 2, T3).** Add the manifest fields in `src/wetland_change/manifest.py`. In `src/wetland_change/pipeline.py`, refactor and add `backfill_once`, plus `output_root_override` on `run_once`. Tests go in the new `tests/test_backfill.py` and in `tests/test_pipeline.py`:
   - **AC:** only in-range items are processed, with one observation file each, using a fake that ignores filters, so the client-side check is what is tested.
   - **AC:** a repeated backfill writes no observation file (mtimes unchanged), reports processed 0 and writes no ledger files.
   - **AC:** after a backfill of items with a recent `created`, a daily `run_once` still processes an item created between the old watermark and the backfill's `created`. This uses a fake that honours the `created` and `datetime` filters like Earth Search, so the test fails without the fix.
   - An interrupted backfill (a BaseException at the 2nd scene) leaves the 1st scene checkpointed, and the rerun processes only the remaining 2.
   - A failed backfill scene is retried on rerun with attempts 2.
   - Naive or reversed bounds raise ValueError.
   - `run_once` tags rows `run_kind="run"`, sets manifest `kind="run"`, records the override and still writes one `ledger_<run_id>.parquet`.
4. **CLI (batch 3, T4).** In `src/wetland_change/cli.py`, add the `backfill` command and `--output-root` on all four commands. Tests go in `tests/test_cli.py`:
   - **AC:** `backfill --help` lists `--start`, `--end` and `--output-root`.
   - The other three commands list `--output-root`.
   - **AC:** `run --output-root <tmp>` writes its manifest under `<tmp>`, nothing under the configured root, records the override and keeps the config digest.
   - `backfill --start D --end D` includes that whole day and records the range and the override.
   - end < start exits with code 2 before loading anything.
   - `verify --output-root` reads the run from the override root.

   **Live AC:** a test marked `live` in `tests/test_backfill.py` runs `backfill --start 2026-10-26 --end 2026-10-28` through the CLI into `tmp_path`, and the manifest shows processed >= 1 with existing observation files. It needs `uv run python scripts/fetch_aoi.py` first.

Verification after each task, from the worktree root:
```
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src scripts
uv run pytest -q
```
Also run `uv run wetland-change backfill --help` and `uv run pytest -q -m live tests/test_backfill.py`, the latter after `uv run python scripts/fetch_aoi.py`.

## Implementation Notes

- 2026-10-29T19:32:49.758Z: touches-expansion: overlaps st-1990 (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/change.py, src/wetland_change/config.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_catalogue.py, tests/test_change.py, tests/test_config.py, tests/test_infra.py, tests/test_live_verify.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.759Z: touches-expansion: overlaps st-8228 (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/change.py, src/wetland_change/config.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_catalogue.py, tests/test_change.py, tests/test_config.py, tests/test_infra.py, tests/test_live_verify.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.760Z: touches-expansion: overlaps st-ae6e (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/change.py, src/wetland_change/config.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_catalogue.py, tests/test_change.py, tests/test_config.py, tests/test_infra.py, tests/test_live_verify.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.761Z: touches-expansion: overlaps st-afcf (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/change.py, src/wetland_change/config.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_catalogue.py, tests/test_change.py, tests/test_config.py, tests/test_infra.py, tests/test_live_verify.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.762Z: touches-expansion: overlaps st-d4a8 (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/change.py, src/wetland_change/config.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_catalogue.py, tests/test_change.py, tests/test_config.py, tests/test_infra.py, tests/test_live_verify.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split

## Questions
