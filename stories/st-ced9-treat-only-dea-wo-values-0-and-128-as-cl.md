---
id: st-ced9
title: Treat only DEA WO values 0 and 128 as clear
type: bug
epic: st-1d45
priority: P3
depends_on: [st-2048]
discovered_from: st-2048
touches: [docs/plans/2026-10-29-swan-wetland-change-design.md, src/wetland_change/verify/wo.py, tests/test_verify.py]
exclusive: false
created: 2026-10-30
updated: 2026-10-30
---

## Description

src/wetland_change/verify/wo.py sets WO_EXCLUDE = 1 | 2 | 32 | 64, following the design's 'Water extent, live' row, so DEA Water Observations pixels with bit 4 (sea), 8 (terrain shadow or low sun) or 16 (high slope) set count as mutually clear. DEA's WO convention treats only 0 (clear dry) and 128 (clear wet) as clear observations. Found while independently checking the st-2048 calibration on 2026-10-30: the live 2026-10-12 ramsar-15 pass had 0 such pixels, so no current result changes, but a coastal or sloped polygon would be scored on pixels DEA itself does not call clear. Out of scope for st-2048, which applies per-polygon thresholds.

## Acceptance Criteria

- [ ] Offline test: wo_agreement counts a WO pixel as clear only when its value is 0 or 128; values 4
- [ ] 8
- [ ] 16 and 132 are excluded.
- [ ] The design's 'Water extent
- [ ] live' matrix row states that only WO values 0 and 128 are clear.
- [ ] The existing offline tests in tests/test_verify.py pass unchanged.

## Implementation Plan

## Findings (verified in the st-ced9 worktree, HEAD 5efa114)

- `src/wetland_change/verify/wo.py` line 31: `WO_EXCLUDE = 1 | 2 | 32 | 64`; `wo_agreement` (line 40) uses `wo_clear = (wo & WO_EXCLUDE) == 0`. The module docstring (lines 3-8) also says bits 1, 2, 32, 64 exclude a pixel. `wo_check` already takes polygon_id and uses `WaterConfig.for_polygon` and `water_pixels`; it is not touched.
- `tests/test_verify.py` line 17 imports `WO_EXCLUDE, WO_WET, wo_agreement`; the existing test `test_wo_agreement_on_mutually_clear_pixels` does `wo[0, 1] |= WO_EXCLUDE & 64`. To keep the existing tests unchanged, `WO_EXCLUDE` must stay exported and must still contain bit 64. `test_wo_check_branches` uses WO value 1 as "nothing clear" (still excluded) and 128 / 0 as clear.
- Design row: `docs/plans/2026-10-29-swan-wetland-change-design.md` line 226 ("Water extent, live"). The milestone-1 plan under docs/plans repeats the old constant inside historical code listings; leave it as a historical record.
- No other code references `WO_EXCLUDE`.

## Approach

Keep the name `WO_EXCLUDE` and widen it to every non-wet flag bit: `1 | 2 | 4 | 8 | 16 | 32 | 64` (= 127). Then `(wo & WO_EXCLUDE) == 0` is true only for WO values 0 and 128, which is DEA's clear convention. The expression in `wo_agreement` stays the same; wet detection (`wo & 128`) is unchanged. This satisfies the "existing tests pass unchanged" criterion with no edit to existing tests.

## Steps

1. TDD, test first. Add `test_wo_agreement_counts_only_wo_0_and_128_as_clear` to `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-ced9/tests/test_verify.py` directly after `test_wo_agreement_on_mutually_clear_pixels`. It proves: with all pipeline pixels clear, a WO array of `[0, 128, 4, 8, 16, 132]` yields n == 2, and each of 4, 8, 16, 132 is excluded individually (parametrised, or n == 0 for a one-pixel array). Also assert 1, 2, 32, 64 still excluded and that agreement for the two clear pixels is computed correctly (pipeline water True on the 128 pixel and False on the 0 pixel gives 1.0). It fails before the change (4, 8, 16, 132 are counted today).
2. Change `WO_EXCLUDE` in `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-ced9/src/wetland_change/verify/wo.py` to `1 | 2 | 4 | 8 | 16 | 32 | 64` with a one-line comment that only 0 and 128 are clear. Update the module docstring to say only values 0 (clear dry) and 128 (clear wet) are clear and every other flag bit excludes the pixel.
3. Update the "Water extent, live" row (line 226) of `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-ced9/docs/plans/2026-10-29-swan-wetland-change-design.md` so the reference column reads: DEA `ga_s2_wo_provisional_3`, same pass, same grid, bit 128 wet, only WO values 0 and 128 clear (any other flag bit excludes the pixel). Keep the rest of the row and table formatting intact.
4. Verification (final stage, not the implementer): ruff check, ruff format --check, mypy, pytest -q per AGENTS.md. No live tests.

## Implementation Notes

## Questions
