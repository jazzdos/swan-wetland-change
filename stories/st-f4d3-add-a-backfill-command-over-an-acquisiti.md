---
id: st-f4d3
title: Add a backfill command over an acquisition date range
type: feature
epic: st-70d1
priority: P1
complexity: hard
depends_on: []
touches: [src/wetland_change/pipeline.py, src/wetland_change/cli.py, src/wetland_change/catalogue/**, src/wetland_change/ledger.py, src/wetland_change/manifest.py, tests/test_pipeline.py, tests/test_cli.py, tests/test_search.py, tests/test_ledger.py, tests/test_backfill.py]
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

## Implementation Notes

## Questions
