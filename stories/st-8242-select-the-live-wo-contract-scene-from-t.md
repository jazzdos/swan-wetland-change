---
id: st-8242
title: Select the live WO contract scene from the current DEA window
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [src/wetland_change/verify/wo.py, tests/test_live_verify.py, tests/test_verify.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

remote_scene in tests/test_live_verify.py loads the 2026-10-27 fixture and asserts a matching ga_s2_wo_provisional_3 item, which DEA keeps for a rolling three months. From about late January 2027 the weekly live step would fail and open an issue every Sunday. Verdict PLAUSIBLE: DEA's expiry behaviour was not checked. Evidence: docs/research/2026-11-04-milestone-2-review.md L1.

## Acceptance Criteria

- [ ] The live WO test picks a recent Earth Search scene that has a matching DEA WO item
- [ ] The live WO test still passes when the 2026-10-27 DEA item no longer exists

## Implementation Plan

Verified in worktree /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-8242: the story pointers are correct. `tests/test_live_verify.py` has a module-scoped `remote_scene` fixture (fixture item.json, S2C_T50HLK_20261027T022351_L2A, hrefs remote) and `test_water_agrees_with_dea_wo` asserts `find_wo_href(remote_scene, THOMSONS_4326) is not None`. `find_wo_href` is in `src/wetland_change/verify/wo.py` and does a DEA STAC search by the scene's date and MGRS tile token. There is no NDVI 60-day live helper in this repo to reuse. `catalogue.search.discover(client, cfg, bbox=, polygons_4326=, created_from=None, seen=set(), datetime_range=(start,end))` already does an acquisition-date-bounded Earth Search search with cloud-cover and footprint re-checks. Only the WO test needs to change. `test_scl_shares_match_esa_percentages` and `test_pixels_match_planetary_computer` keep the pinned `remote_scene` (Earth Search COGs do not expire; out of scope).

Design: put a small pure selection helper in `src/wetland_change/verify/wo.py` so the "2026-10-27 DEA item no longer exists" behaviour is unit-testable offline. The live test then walks recent Earth Search scenes newest first, skips scenes with no DEA WO item, and uses the first scene that has one, is on the Thomsons footprint, and has more than 10000 mutually clear pixels (cloud over the polygon can make a recent scene unusable, so the loop continues to the next candidate).

Steps (TDD):
1. Add failing offline tests to `tests/test_verify.py`:
   - `test_wo_candidates_newest_first_skips_scenes_without_wo`: build three SceneItems from `fixture_scene` with `dataclasses.replace` at different `datetime`s (also distinct item_id); pass a fake `find` returning an href for two of them and None for the middle. Assert the yielded (scene, href) pairs are the two with an href, newest first, and that `find` is called with the Thomsons bbox. Proves recent selection and skipping.
   - `test_wo_candidates_pinned_fixture_date_gone`: scenes = [fixture_scene dated 2026-10-27, a newer one]; `find` returns None for the 2026-10-27 date and an href for the newer. Assert the result is only the newer scene and the fixture date is never required. Proves AC2 (the selection does not depend on the 2026-10-27 DEA item).
   - `test_wo_candidates_empty_when_no_wo_anywhere`: `find` always None gives an empty list (the live test turns this into a clear failure message, not a silent pass).
   - `test_wo_candidates_limit`: with `limit=2` and four scenes that all have WO, only two are yielded and `find` is called twice (lazy generator, bounds the DEA requests).
2. Implement in `src/wetland_change/verify/wo.py`: `def wo_candidates(scenes: Iterable[SceneItem], bbox_4326: tuple[float, float, float, float], *, find: Callable[[SceneItem, tuple[float, float, float, float]], str | None] = find_wo_href, limit: int | None = None) -> Iterator[tuple[SceneItem, str]]`. It sorts scenes by `scene.datetime` descending (tie-break item_id), calls `find` lazily, yields `(scene, href)` for non-None hrefs and stops after `limit` yields. Docstring: why (DEA keeps the provisional product about three months, docs/research/2026-11-04-milestone-2-review.md L1). Add `Callable, Iterable, Iterator` imports; `SceneItem` is already imported.
3. Edit `tests/test_live_verify.py`: add a constant `WO_LOOKBACK_DAYS = 60` and a module-level helper `_recent_scenes()` that loads `cfg = load_config(.../config/pipeline.toml)`, calls `discover(open_client(cfg.stac.endpoint), cfg.stac, bbox=THOMSONS_4326, polygons_4326=[box(*THOMSONS_4326)], created_from=None, seen=set(), datetime_range=(now - timedelta(days=WO_LOOKBACK_DAYS), now))` and returns `.scenes` (import `discover` from `wetland_change.catalogue.search`, `wo_candidates` from `wetland_change.verify.wo`). Rewrite `test_water_agrees_with_dea_wo` to take no `remote_scene`: for `scene, wo_href` in `wo_candidates(scenes, THOMSONS_4326, limit=6)`: open grid from `scene.bands["green"]`, `plan_window(THOMSONS_32750, grid)` (skip candidate if None), `read_stack`, `rasterise`, `wo_check(...)` as before; collect `(scene.item_id, n_mutually_clear)`; if `n_mutually_clear > 10000` then `assert check.passed, check.detail` and return. If the loop ends without a usable scene, `pytest.fail` with a message listing the number of Earth Search scenes found, the candidates tried and their n_mutually_clear values (distinguishes "no Earth Search scenes", "no DEA WO match", and "all cloudy"). Keep the existing `n_mutually_clear > 10000` bar and the existing agreement assertion. Update the module docstring or a comment to say the WO scene is chosen from the last 60 days because DEA expires the product.
4. Add a LEARNINGS.md note only if the file has a suitable running section (one line: the live WO test selects its scene from the last 60 days of Earth Search with a DEA WO match). Skip if no natural place.
5. Verify in order, one per command: `uv run ruff check src tests scripts`; `uv run ruff format --check src tests scripts`; `uv run mypy src scripts`; `uv run pytest -q`; then, once, `uv run pytest -q -m live tests/test_live_verify.py -k water_agrees` (network; confirms a real recent scene is found). Report the live result honestly if the network is unavailable.

What the tests prove: the offline tests show selection is newest-first, ignores scenes without WO, is independent of the pinned 2026-10-27 date, is bounded, and yields nothing (so a clear failure) when DEA has nothing. The live test shows a recent Earth Search scene with a real matching DEA WO item agrees with the pipeline water extent.

## Implementation Notes

- 2026-11-05T10:23:43.389Z: Gates on the story branch at 594a919: ruff check, ruff format --check and mypy pass; pytest exits 0 in default mode and with GITHUB_ACTIONS=true. The live test -m live -k water_agrees passed against Earth Search and DEA in the build-flow implementer's run; that result is the implementer's report, not re-run here. AC2 is proven offline by test_wo_candidates_pinned_fixture_date_gone; the live test no longer references the 2026-10-27 date. Beyond the planned touches: src/wetland_change/verify/wo.py gains wo_candidates and tests/test_verify.py its tests. wo_candidates also yields nothing for limit <= 0, which the plan did not ask for.

## Questions
