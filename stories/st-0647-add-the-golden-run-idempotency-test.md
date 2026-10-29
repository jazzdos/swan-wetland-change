---
id: st-0647
title: Add the golden-run idempotency test
type: feature
epic: st-1d45
priority: P2
depends_on: []
touches: [tests/test_idempotency.py, tests/test_idempotency/**, pyproject.toml, uv.lock]
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

## Implementation Notes

## Questions
