---
id: st-1b87
title: Add the provenance footer to observation files written before st-2bfd
type: chore
priority: P2
depends_on: []
discovered_from: st-2bfd
touches: [README.md, docs/handoffs/2026-11-06-milestone-2.md, src/wetland_change/cli.py, src/wetland_change/outputs/footer_backfill.py, src/wetland_change/outputs/geoparquet.py, src/wetland_change/outputs/provenance.py, tests/test_cli.py, tests/test_footer_backfill.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---
## Description

The 2026-11-02 backfill (commit 114459b; see docs/research/2026-11-03-backfill-evidence.json) wrote 1,147 observation files under observations/ before st-2bfd added provenance footers. They lack the keys that src/wetland_change/outputs/provenance.py footer_metadata now writes: source_epsg, operation_epsg, geometry_epsg, units, scl_classes_dropped, scl_classes_clear, clear_pixel_rule, water_settings and water_units_note. AGENTS.md requires the source CRS, operation CRS and units with every output. That copy is the seed for s3://swan-wetland-change-outputs-263051716913/ (infra applied 2026-11-06), so the bucket holds the same files. `wetland-change score` already rewrites change files with the footer; nothing rewrites observation files.

A seed-compatibility check on 2026-11-06 found the old files have the same schema and row data as current main writes (6 scenes reprocessed, identical bar run_id and footer) and that the water methods and site overrides in config/pipeline.toml are unchanged since 114459b. Jarrod chose a one-off footer addition over a 13-hour reprocess.

Out of scope: the 36 old run manifests that lack git_commit, operation_epsg, runtime and uv_lock_sha256. They record what happened at the time and stay as written; the story only documents that.

Agents run everything on local stores and local copies. They make no AWS calls and do not touch /Users/jarrodbaker/Documents/swan-wetland-change-data, which is read only. The orchestrator runs the command against the bucket after the merge.

## Acceptance Criteria

- [ ] A command adds the footer keys to every observation file under an output root that lacks them and works on local and s3:// roots through the existing store layer.
- [ ] Each rewritten file has the same Arrow schema and row data as before and keeps its geo key; a test compares them.
- [ ] Footer values equal footer_metadata for the same frame and the configured water settings; a test checks this.
- [ ] Each rewritten file also gets a footer key that names the date and commit that added the footer after the fact.
- [ ] A file that already has every footer key is not rewritten; a second run rewrites nothing; a test shows this.
- [ ] A dry-run option lists the files it would rewrite and writes nothing.
- [ ] The command prints counts of files scanned and rewritten and skipped and exits non-zero if any file fails.
- [ ] LEARNINGS.md or the milestone 2 handoff says the old run manifests keep their original fields and where the producing commit is recorded.
- [ ] The four verification gates pass.

## Implementation Plan

# st-1b87 plan: add provenance footers to old observation files

All paths are relative to `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-1b87`. Agents commit nothing, make no AWS calls, run no `-m live` tests, and do not touch `/Users/jarrodbaker/Documents/swan-wetland-change-data`. No em dashes in docs.

## Verified against the worktree

- `src/wetland_change/outputs/provenance.py::footer_metadata(frame, *, kind, water, operation_epsg)` returns nine keys: source_epsg, operation_epsg, geometry_epsg, units, scl_classes_dropped, scl_classes_clear, clear_pixel_rule, water_settings, water_units_note. Values depend only on the frame, the water config and the operation EPSG.
- `src/wetland_change/outputs/geoparquet.py::to_geoparquet_bytes(frame, metadata)` writes GeoParquet 1.1 with a covering bbox, snappy, and merges `metadata` into the existing footer, keeping the `geo` and `pandas` keys. `read_observations` filters `store.list_files("observations")` to `obs_*.parquet`.
- `src/wetland_change/store.py::OutputStore.write_bytes(relpath, data, *, content_type=None)`; `CONTENT_TYPES[".parquet"]` is `application/vnd.apache.parquet`. `list_files` and `read_bytes` exist. There is no S3 object-serving stub or moto in the repo: `tests/test_store.py::_StubS3` only answers writes, and its GET returns an empty listing.
- `src/wetland_change/runtime.py::capture_environment().git_commit` is the commit the run manifests record (None outside a checkout).
- I ran the round trip on an old-style file (plain `to_parquet` with `schema_version="1.1.0", write_covering_bbox=True`, as `tests/test_geoparquet.py` builds one): `gpd.read_parquet` then `to_geoparquet_bytes(frame, footer_metadata(...))` gives a pyarrow table that is `equals` the original, the same schema, byte-equal `geo` and `pandas` metadata, snappy. So the geopandas path is safe, and the command still checks this per file before writing (step 3).
- No prerequisite has merged since the story was written that changes this: `cli.py` has no command for it, nothing rewrites observation files.

## Planner choices (recorded here as the story asks)

- Command: `wetland-change add-observation-footers`, options `--config`, `--output-root`, `--dry-run`, `--now` (same NOW_HELP, only the UTC date is used). It uses `load_config`, not `_load`, so it needs no AOI files.
- After-the-fact key: `footer_added_after_the_fact`. Value: `json.dumps({"commit": <git HEAD sha of the checkout running the command>, "date": "YYYY-MM-DD"}, sort_keys=True)`, the date being the UTC date of `--now` (default today). The commit comes from `capture_environment().git_commit`, as the run manifests record it. If it is None the command refuses with `typer.BadParameter` and writes nothing.
- The file-has-footer test is "all nine footer_metadata keys present". The after-the-fact key is not required, so files written natively by current main are skipped.
- A file with some but not all keys is rewritten; all nine are set from `footer_metadata`.
- A rewritten file is verified before it is written: pyarrow table schema (ignoring metadata) equal, table `equals`, `geo` and `pandas` metadata values equal, and each of the nine keys equals `footer_metadata` for the frame. Any mismatch counts the file as failed and nothing is written for it.
- Failures are per file: caught, listed on stderr as `path<TAB>message`, counted; remaining files are still processed. Exit code 1 if any failed, else 0. Dry run writes nothing and exits 0 unless a file fails the same checks (it runs the full compute and verify, skipping only the write).
- Output: one line per rewritten (or would-be rewritten) path, then `scanned N, rewritten M, skipped K, failed F` (dry run: `would rewrite M`).
- Docs: a new section in `docs/handoffs/2026-11-06-milestone-2.md` and a bullet plus command line in `README.md`.

## Steps

1. `src/wetland_change/outputs/provenance.py`: add `FOOTER_KEYS: Final[tuple[str, ...]]` listing the nine keys in the order `footer_metadata` returns them. Test `test_footer_keys_match_footer_metadata` in `tests/test_footer_backfill.py` proves the constant cannot drift from the function.
2. `src/wetland_change/outputs/geoparquet.py`: extract `observation_paths(store, exclude=()) -> list[str]` (the `obs_*.parquet` filter) and use it in `read_observations`. Existing `tests/test_geoparquet.py` keeps passing.
3. New `src/wetland_change/outputs/footer_backfill.py` with `ADDED_KEY`, `added_footer_value(commit, on)`, a frozen dataclass `FooterBackfillResult(scanned, rewritten, skipped, failed, dry_run)` and `add_missing_footers(store, *, water, operation_epsg, commit, on, dry_run=False)`. It implements the rules above and writes through `store.write_bytes(path, data, content_type=CONTENT_TYPES[".parquet"])`.
4. `src/wetland_change/cli.py`: the `add-observation-footers` command; update the module docstring command list.
5. Tests, new `tests/test_footer_backfill.py` (core) and additions to `tests/test_cli.py`. What each proves:
   - rewrite_keeps_schema_rows_and_geo: old-style file in a tmp_path store becomes a file whose pyarrow table equals the original, whose `geo` and `pandas` values are byte-equal, and `gpd.read_parquet` frames pass `assert_geodataframe_equal`. (AC 2)
   - footer_values_equal_footer_metadata: with a `WaterConfig` that has an override, every one of the nine values equals `footer_metadata(frame, kind="observation", water=..., operation_epsg=32750)`. (AC 3)
   - added_key_names_date_and_commit: the value parses to the given commit and date. (AC 4)
   - file_with_all_keys_is_skipped_and_second_run_rewrites_nothing: a `write_observations` file is skipped with unchanged bytes; after run 1 on old files, run 2 has rewritten == 0 and every byte unchanged. A spy on `store.write_bytes` shows no calls. (AC 5)
   - partial_footer_is_rewritten: a file with only `units` gets all nine keys.
   - dry_run_lists_and_writes_nothing: rewritten lists the old paths, bytes unchanged, spy not called. (AC 6)
   - one_failure_does_not_stop_the_rest: a corrupt `obs_*.parquet` is in `failed`, left unchanged, and the good files are rewritten. (AC 7)
   - mismatch_is_refused: monkeypatching `to_geoparquet_bytes` to drop a row marks the file failed and writes nothing.
   - only_obs_files_are_scanned: a non-obs file under `observations/` and files under `changes/` are untouched and uncounted.
   - write_goes_through_the_store_with_the_parquet_content_type: a spy store records `content_type="application/vnd.apache.parquet"`.
   - s3_write_keeps_the_parquet_content_type: an S3 `OutputStore` aimed at `tests/test_store.py`'s `_StubS3` (import `stub_s3` and `_s3_store` from there), with `list_files` and `read_bytes` monkeypatched to serve one old file from memory, shows the stub received Content-Type `application/vnd.apache.parquet` on the PUT or multipart create for that key and created no directory marker. This covers the s3:// path without any AWS call. (AC 1)
   - CLI: help lists the command and `--dry-run`, `--output-root`; exit 0 and the `scanned N, rewritten M, skipped K, failed F` line on a tmp store; second invocation prints `rewritten 0`; `--dry-run` writes nothing; exit 1 when a file is corrupt; BadParameter exit 2 when the commit is None (monkeypatch `cli.capture_environment`). (AC 7)
   - Update `test_help_lists_commands` and `test_output_root_listed_on_every_command` in `tests/test_cli.py` for the new command.
6. Docs. `docs/handoffs/2026-11-06-milestone-2.md`: new section "Old observation files and old run manifests" stating: the 1,147 observation files from the 2026-11-02 backfill were written before st-2bfd; `add-observation-footers` adds the nine keys plus `footer_added_after_the_fact` (date and commit of the run that added it); the 36 old run manifests lack git_commit, operation_epsg, runtime and uv_lock_sha256, keep their original fields and are not rewritten; the producing commit of that backfill is `114459b6b5cfa507f853574e62b8ddec0da6d223`, recorded as `git_head` in `docs/research/2026-11-03-backfill-evidence.json`. Also note the command is run by the orchestrator against the bucket after merge. `README.md`: add `uv run wetland-change add-observation-footers --dry-run` to the command block and a bullet beside `compact-ledger`. (AC 8)
7. Gates, one command per line, each judged by exit code: `uv run ruff check src tests scripts`; `uv run ruff format --check src tests scripts`; `uv run mypy src scripts`; `uv run pytest -q`; `GITHUB_ACTIONS=true uv run pytest -q`. (AC 9)

## Implementation Notes

- 2026-11-06T13:02:06.049Z: Committed on story/st-1b87. Gates green in the worktree: ruff check, ruff format, mypy, pytest default and GITHUB_ACTIONS=true; 991 passed, 10 deselected. No AWS calls by agents. The orchestrator runs add-observation-footers against s3://swan-wetland-change-outputs-263051716913/ after the merge.
