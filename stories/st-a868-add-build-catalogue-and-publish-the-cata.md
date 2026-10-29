---
id: st-a868
title: Add build-catalogue and publish the catalogue each run
type: feature
epic: st-93a8
priority: P1
depends_on: [st-1990, st-c8ca]
touches: [src/wetland_change/cli.py, src/wetland_change/pipeline.py, src/wetland_change/stac/**, tests/test_cli.py, tests/test_pipeline.py, tests/test_catalogue.py, pyproject.toml, uv.lock]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
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

## Implementation Notes

## Questions
