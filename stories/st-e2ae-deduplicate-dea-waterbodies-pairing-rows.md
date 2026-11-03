---
id: st-e2ae
title: "Deduplicate DEA Waterbodies pairing rows by tile and date, not datetime alone"
type: bug
priority: P3
depends_on: []
discovered_from: st-b983
touches: [src/wetland_change/verify/waterbodies.py, tests/test_verify_waterbodies.py]
exclusive: false
created: 2026-11-03
updated: 2026-11-03
---

## Description

_lake_checks in src/wetland_change/verify/waterbodies.py keeps one row per datetime (highest scene_coverage), but observations of the same tile on the same date carry different datetimes, so the step does not fire. In the st-b983 backfill Forrestdale had 346 rows and 346 distinct datetimes. n_pairs includes same-tile same-date rows: 12 (Thomsons), 10 (Forrestdale), 6 (Lake Clifton), 4 (Lake Preston). Such rows can pair with the same DEA row, so the pairs are not independent. A one-row-per-tile-and-date sensitivity gave rho 0.8932, 0.8608, 0.8555 and 0.8568, same H4 verdict. Decide the intended dedup key, fix it, and test it. Out of scope in st-b983, which may not change src/.

## Acceptance Criteria

- [ ] Two rows of one polygon on the same tile and date with different datetimes yield one pair
- [ ] shown by a test
- [ ] The kept row rule is documented in the module docstring

## Implementation Plan

## Findings (verified in /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-e2ae)

- `_lake_checks` in `src/wetland_change/verify/waterbodies.py` (about line 190) does `rows.sort_values(["datetime","scene_coverage"], ascending=[True,False]).drop_duplicates("datetime")`. That only collapses a datatake seen on two tiles (identical datetime). Two scenes of one tile on the same UTC date with different datetimes both survive, and both pair to the same DEA row (pairing is by UTC calendar date), so the pairs are not independent.
- The stored observation parquet already has a `tile` column (`OBSERVATION_COLUMNS` in `src/wetland_change/outputs/geoparquet.py`), but the verify module's own `OBSERVATION_COLUMNS` list (waterbodies.py) does not read it. The only production caller is `src/wetland_change/verify/run.py` (~line 421), which calls `read_observations(store, paths)` then `waterbody_checks(...)`. It needs no change.
- `tests/test_verify_waterbodies.py` builds frames with the `_obs` helper (no `tile` column) and `test_read_observations_keeps_only_waterbodies` asserts the exact column list and builds a parquet with no `tile`. Both must be updated.
- The prerequisite check found nothing merged that changes this area (HEAD 728d505; touches are unchanged).

## Decision: dedup key

Two passes, in this order:
1. Existing rule, unchanged: one row per `datetime` (highest `scene_coverage`). This is the tile-seam rule: one datatake on two tiles is one pair.
2. New rule: one row per (`tile`, UTC calendar date). Kept row = highest `scene_coverage`, then highest `valid_fraction` (NaN last), then earliest `datetime`. The key is the story's title key, and it matches the one-row-per-tile-and-date sensitivity run (rho 0.8932, 0.8608, 0.8555, 0.8568, same H4 verdict). Rows of different tiles on the same date with different datetimes are deliberately NOT merged (the story scopes the key to tile and date). Note this in the docstring.

## Steps

1. Test first (red). Edit `tests/test_verify_waterbodies.py`:
   - `_obs(*rows)` gains a `tile` column, default `"T50HMK"` for every row (keeps all existing tests unchanged in behaviour). Add an optional `tiles: Sequence[str] | None = None` keyword so tests can set tiles per row.
   - Add `test_same_tile_same_date_different_datetimes_yield_one_pair`: two rows, same tile, same UTC date (e.g. `2026-10-12T02:26:00Z` and `2026-10-12T02:26:20Z`), both full coverage, valid_fraction 0.95, different wet fractions (0.85 and 0.80). Assert `len(_passes(checks)) == 1` and `_rho(checks).detail["n_pairs"] == 1` (n_pairs counts scored pairs; the single check is scored). Proves one pair per tile and date. Use a second assertion that the kept row is the higher-coverage one in a variant below.
   - Add `test_same_tile_same_date_keeps_highest_coverage_then_valid_fraction`: three rows on one tile/date at different datetimes: (coverage 0.5), (coverage 1.0, valid 0.90, wet 0.85), (coverage 1.0, valid 0.97, wet 0.80). Assert the single check has `detail["valid_fraction"] == 0.97` and `detail["scene_coverage"] == 1.0`. Proves the tie-break order. Add a case where coverage ties and valid_fraction ties, and assert the earliest datetime is kept (`detail["pipeline_date"]` startswith the earlier stamp).
   - Add `test_same_date_different_tiles_with_different_datetimes_kept_apart`: two rows, tiles `T50HMK` and `T50HLK`, same date, different datetimes, both full coverage. Assert two per-pass checks. Proves the key includes the tile and the rule does not collapse to date alone.
   - Add `test_same_tile_different_dates_not_merged`: two rows on one tile on dates 5 days apart (`2026-10-10` and `2026-10-15`, both within 3 days of a fixture/series date, or build a small series) give two checks. Proves different dates are not merged. Simplest: use the series from `_series()` (date 2026-10-10) plus a two-row custom series if needed; the implementer may build `pd.DataFrame({"date": ..., "wet_fraction": ...})` as `test_end_to_end_single_spearman_check` does.
   - Add `test_seam_datetime_rule_still_applies_with_tiles`: re-run of the existing seam test shape with two tiles and the same datetime (tiles `["T50HMK","T50HLK"]`, coverage `[0.363, 1.0]`); assert one check with coverage 1.0. Proves rule 1 still runs before rule 2.
   - Update `test_read_observations_keeps_only_waterbodies`: add `"tile": ["T50HMK","T50HMK"]` to the frame, and add `"tile"` to the expected column list (after `datetime`, matching the new constant order below).
   Run `uv run pytest -q tests/test_verify_waterbodies.py` and confirm the new dedup tests fail (and the read_observations test fails on the column list).

2. Implement in `src/wetland_change/verify/waterbodies.py`:
   - Add `"tile"` to `OBSERVATION_COLUMNS` after `"datetime"`.
   - In `_lake_checks`, keep the existing datetime dedup, then add the second pass. Skip it when `rows` is empty (`_day_numbers` on an empty object Series can fail). Sketch:
     ```python
     if len(rows):
         rows = rows.assign(_day=_day_numbers(rows["datetime"]))
         rows = (
             rows.sort_values(
                 ["tile", "_day", "scene_coverage", "valid_fraction", "datetime"],
                 ascending=[True, True, False, False, True],
                 na_position="last",
             )
             .drop_duplicates(["tile", "_day"], keep="first")
             .sort_values("datetime")
             .drop(columns="_day")
             .reset_index(drop=True)
         )
     ```
     Re-sort by `datetime` afterwards so check order stays chronological. Update the comment above the first dedup to say it is the seam rule and add one above the second saying why (same-date rows pair with the same DEA row).
   - Update the module docstring "Conventions" paragraph: after the existing sentence about rows sharing a datetime, add the rule: "Then, for each tile and UTC calendar date, only one row is kept (highest `scene_coverage`, then highest `valid_fraction`, then earliest `datetime`), because rows of one tile on one date pair with the same DEA row and are not independent pairs. Rows of different tiles with different datetimes on one date are not merged." Also state that `n_pairs` therefore counts one pair per tile and date. Keep the docstring flat prose, no em dashes.

3. Verify, in order, one command per line:
   - `uv run ruff check src tests scripts`
   - `uv run ruff format --check src tests scripts`
   - `uv run mypy src scripts`
   - `uv run pytest -q`
   All new tests must pass and no other test may change status. Also run `uv run pytest -q tests -k "verify"` if any run.py test constructs waterbody observations without a `tile` column (grep showed none outside tests/test_verify_waterbodies.py; confirm).

4. Commit on branch story/st-e2ae (message `st-e2ae: deduplicate DEA Waterbodies pairing rows by tile and date`) with the Co-Authored-By trailer from the session reminder.

## What each test proves

- same tile/same date different datetimes: one pair (acceptance criterion).
- highest-coverage, valid_fraction, earliest-datetime: the documented kept-row rule.
- different tiles kept apart / different dates kept apart: the key is exactly (tile, date).
- seam datetime test with tiles: the original rule still runs first.
- read_observations column test: `tile` is actually loaded from the store, so the rule works in production via `verify/run.py`.

## Implementation Notes

## Questions
