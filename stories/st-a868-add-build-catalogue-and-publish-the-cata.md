---
id: st-a868
title: Add build-catalogue and publish the catalogue each run
type: feature
epic: st-93a8
priority: P1
depends_on: [st-1990, st-c8ca]
touches: [README.md, src/wetland_change/cli.py, src/wetland_change/pipeline.py, src/wetland_change/stac/catalogue.py, tests/test_catalogue.py, tests/test_cli.py, tests/test_run_catalogue.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-30
---
## Description

Add `wetland-change build-catalogue` (design CLI list) to rebuild the catalogue from the ledger in the configured store or the `--output-root` override, and call the catalogue stage from `run_once` after observations and changes are written.

- Items gain a `changes` asset for their change file when one exists (`changes/year=YYYY/tile=<MGRS>/chg_<item_id>.parquet`).
- Items gain an asset for the run's verification report, `verification/<run_id>.json`, written by `write_report` in `src/wetland_change/verify/checks.py`, when it exists.
- The collection gains an `items.parquet` asset written with stac-geoparquet 0.8 from the ledger items (decision 0003).

## Acceptance Criteria

- [ ] `uv run wetland-change build-catalogue --help` exits 0.
- [ ] Offline test: after `run_once` on the fixture, `stac/catalog.json` exists in the store and pystac `validate_all` passes.
- [ ] Offline test: an item with change rows has a `changes` asset pointing at its change file, and an item without change rows has none.
- [ ] Offline test: `items.parquet` is written, DuckDB reads it, and its row count equals the number of catalogue items.
- [ ] Offline test: an item processed in a run with a verification report has an asset pointing at `verification/<run_id>.json`.

## Implementation Plan

## Findings from the worktree (branch story/st-a868)

- The catalogue module already exists: `src/wetland_change/stac/catalogue.py` has `processed_entries`, `_item`, `build_catalogue(ledger, *, base_url)`, `validate_catalogue`, `write_catalogue`, `build_and_write(store, *, base_url)`. `src/wetland_change/stac/__init__.py` re-exports them and `StoreStacIO`.
- `PipelineConfig.catalogue.base_url` already exists (`config/pipeline.toml` `[catalogue]`, default `https://example.invalid/swan-wetland-change`). Use it; add no config.
- Change files are `change_path(year, tile, item_id)` in `src/wetland_change/outputs/changes.py`. The year is the UTC year of the observation datetime, which equals the ledger entry's `datetime.year`. The ledger entry also has `tile` and `run_id`.
- `report_path(run_id)` in `src/wetland_change/verify/checks.py` gives `verification/<run_id>.json`; `write_report(checks, *, store, run_id, docs_dir, generated_at)` writes it. It is written by the separate `verify` command, after `run_once`, so a catalogue built inside `run_once` will not see that run's report. The assets therefore must be decided by whether the file exists in the store at build time, and `build-catalogue` after `verify` picks the report up. Do not auto-hook verify into `run_once`.
- stac-geoparquet is 0.8.3. `stac_geoparquet.arrow.parse_stac_items_to_arrow(list_of_item_dicts)` returns a RecordBatchReader; `stac_geoparquet.arrow.to_parquet(table, output_path)` needs a real path (a BytesIO silently writes 0 bytes). An empty item list raises ValueError. Output was byte-identical across two writes, and DuckDB reads it.
- The existing tests in `tests/test_catalogue.py` assert exact `stac/` file lists (`test_written_files_are_exactly_the_succeeded_items`), so they must be updated for the new `items.parquet`. The empty-ledger test must still produce only the two JSON files, so no `items.parquet` and no collection asset when there are no items.

## Steps

Batch 1 (catalogue module; independent of the CLI and pipeline)

1. `src/wetland_change/stac/catalogue.py`:
   - Add `ITEMS_PARQUET_KEY = f"stac/{COLLECTION_ID}/items.parquet"`.
   - `build_catalogue(ledger, *, base_url, available: Collection[str] = frozenset())`. `available` is the set of store-relative paths that exist. `_item` gets `available`. Existing callers pass nothing, so nothing changes for them.
   - In `_item`, after the `observations` asset, add `changes` (href `{base_url}/{change_path(year, tile, item_id)}`, parquet media type, roles `["data"]`) when that path is in `available`. The year is `entry["datetime"].astimezone(UTC).year`; skip if the datetime or tile is None. Then add `verification` (href `{base_url}/{report_path(entry['run_id'])}`, media type `application/json`, roles `["metadata"]`) when that path is in `available` and run_id is not None.
   - In `build_catalogue`, when `items` is non-empty, add a collection asset `items` (href `{base_url}/{ITEMS_PARQUET_KEY}`, parquet media type, roles `["data"]`, title "Catalogue items (stac-geoparquet)"). Add it before `catalog.normalize_hrefs`.
   - Add `items_parquet_bytes(items: list[dict]) -> bytes`. Write `parse_stac_items_to_arrow(items)` with `to_parquet` into a `tempfile.TemporaryDirectory()` path and return the bytes.
   - In `write_catalogue`, when the collection has an `items` asset, build the item dicts as `item.to_dict(include_self_link=True, transform_hrefs=False)` for all items sorted by id, and write the bytes with `store.write_bytes(key, ...)`. The key is the asset href with the `base_url/` prefix removed, using the same mismatch check as the JSON files. Include the key in the returned sorted list.
   - In `build_and_write`, compute `available = set(store.list_files("changes")) | set(store.list_files("verification"))` and pass it to `build_catalogue`.
   - Import `report_path` from `wetland_change.verify.checks` and `change_path` from `wetland_change.outputs.changes`. Check there is no import cycle; if `verify/__init__.py` causes one, import from the submodule directly.
2. `tests/test_catalogue.py`, with the existing `store` fixture and `BASE_URL`:
   - Update the exact-file-list test and the `set(item["assets"]) == {"observations"}` assertion for the new behaviour.
   - Add `test_changes_asset_only_for_items_with_change_file`. Write a change file with `store.write_bytes(change_path(2026, tile, SUCCEEDED_IDS[0]), b"x")`, where tile is that ledger entry's `tile`. Build and write. Assert that item has a `changes` asset with href `BASE_URL/<change path>` and media type parquet, and that every other item has no `changes` key. This proves the asset follows change-file existence.
   - Add `test_verification_asset_points_at_run_report`. Call `write_report([], store=store, run_id="r2", docs_dir=None)`, then build and write. Items whose latest ledger run_id is `r2` (the retried item and the 20261026 item) get a `verification` asset with href `BASE_URL/verification/r2.json`. Items from `r1` have none.
   - Add `test_items_parquet_written_and_readable_by_duckdb`. `stac/swan-wetland-change/items.parquet` is in the written list. `duckdb.sql("select count(*) from read_parquet(...)")` on a temp copy of the store bytes equals `len(SUCCEEDED_IDS)`. The collection JSON has an `items` asset with href `BASE_URL/stac/swan-wetland-change/items.parquet`.
   - `test_rebuild_is_byte_identical` must still pass, which covers parquet determinism.
   - The validate_all test must still pass, so the collection asset is schema-valid.
   - `test_empty_ledger_gives_valid_catalogue` must still expect exactly two files.

Batch 2 (CLI, pipeline integration, run-level tests; depends on Batch 1)

3. `src/wetland_change/cli.py`: add the command `build-catalogue`:
   ```
   @app.command("build-catalogue")
   def build_catalogue_command(config: ConfigOption = Path("config/pipeline.toml"), output_root: OutputRootOption = None) -> None
   ```
   Docstring: "Rebuild the STAC catalogue and items.parquet from the ledger." Use `cfg = load_config(config)` (no AOI needed, as in `score`) and `store = _store(cfg, output_root)`. Call `build_and_write(store, base_url=cfg.catalogue.base_url)` and echo one written path per line followed by a count. Import `build_and_write` from `wetland_change.stac`. Update the module docstring.
4. `src/wetland_change/pipeline.py`: in `run_once`, after `write_manifest(manifest, store)`, call `build_and_write(store, base_url=cfg.catalogue.base_url)`. It runs after the manifest write so a catalogue failure cannot lose the run record; the exception still propagates. It runs on every run, including runs that processed nothing, because the output is deterministic. Do not touch `backfill_once` or `score_once`. Do not add a manifest field.
5. `README.md`: add a short note on `wetland-change build-catalogue` and on the order run, then verify, then build-catalogue, so the report asset appears.
6. `tests/test_cli.py`: add `build-catalogue` to the commands in `test_help_lists_commands`, and add it to the `--output-root` parametrize list. Add `test_build_catalogue_help_exits_zero` (invoke `["build-catalogue", "--help"]`, exit 0). Add a test that monkeypatches `cli.load_config` to return `_config(tmp_path / "configured")`, seeds a store at `--output-root` via a `run_once` fixture run (`tests.test_pipeline._run` into that root), deletes `stac/` from that store, invokes `build-catalogue --config <file> --output-root <root>`, and asserts exit 0 and `stac/catalog.json` re-exists in the override root and not in the configured root.
7. New `tests/test_run_catalogue.py`, offline, importing `FakeClient`, `_polygons`, `_run`, `_probe`, `_seed_october_baseline`, `NOW`, `_config` from `tests.test_pipeline`, and `StoreStacIO` / `build_and_write` from `wetland_change.stac`. The base URL is `DEFAULT_CATALOGUE_BASE_URL` from `wetland_change.config`.
   - `test_run_once_publishes_valid_catalogue`: after `_run` on the fixture, `stac/catalog.json` exists in the store. Load it with `pystac.Catalog.from_file(f"{base}/stac/catalog.json", stac_io=StoreStacIO(store, base))` and assert `pystac.validation.validate_all(catalog, stac_io=io) is None`. There is one item. This covers the "catalog.json exists and validate_all passes" criterion.
   - `test_item_with_change_rows_has_changes_asset`: seed the baseline as in `test_run_once_writes_change_file_for_flagged_item`, then run. The item JSON has a `changes` asset pointing at `{base}/{change_path(2026, tile, item_id)}`.
   - `test_item_without_change_rows_has_no_changes_asset`: run without a baseline. The item JSON has no `changes` asset.
   - `test_items_parquet_row_count_matches_items`: after the run, DuckDB reads `items.parquet` (copy the store bytes to a temp file or use `store.root` path). The row count equals the number of items in the catalogue (1).
   - `test_verification_report_asset`: after the run, call `write_report([], store=store, run_id=manifest.run_id, docs_dir=None)` and then `build_and_write(store, base_url=base)`. The item has a `verification` asset with href `{base}/verification/{run_id}.json`. Also assert that the catalogue written inside `run_once` (before the report existed) had no such asset.
8. Run the verification commands from AGENTS.md in order: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. Also run `uv run wetland-change build-catalogue --help` and confirm exit 0. If an existing test fails because `run_once` now writes `stac/` files (for example tests that list all store files), fix the test expectation. The idempotency tests in `tests/test_golden_run.py` should hold because the catalogue output is byte-identical on a rerun.

## Implementation Notes

## Questions
