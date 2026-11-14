---
id: st-9812
title: Stop a catalogue footprint difference failing the Copernicus count and discovery checks
type: bug
priority: P2
depends_on: []
touches: [LEARNINGS.md, data/SOURCES.md, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/freshness.py, tests/fixtures/footprint_edge_50hmk_20261014/cdse_item.json, tests/fixtures/footprint_edge_50hmk_20261014/dea_qd4xhuft4_v3.geojson, tests/fixtures/footprint_edge_50hmk_20261014/es_item.json, tests/test_sources.py, tests/test_verify_copernicus.py, tests/test_verify_freshness.py]
exclusive: false
created: 2026-11-12
updated: 2026-11-14
---

## Description

The weekly verify of 2026-11-09 (run 42548248931, GitHub issue #1) failed freshness_count_vs_copernicus on tile 50HMK with measured 1.0. The one-sided scene is S2C_MSIL2A_20261014T020311_N0513_R017_T50HMK_20261014T062152 (Earth Search item S2C_T50HMK_20261014T021347_L2A, a swath-edge pass with 34.7 percent nodata). Both catalogues list the datatake. normalise_scenes in src/wetland_change/verify/copernicus.py filters each catalogue's listing by that catalogue's own item footprint against the AOI polygons. The CDSE footprint reaches further west than the Earth Search footprint (CDSE minus Earth Search is 68.8 km2) and covers 54 percent of one 0.27 ha polygon, dea-qd4xhuft4_v3; the Earth Search footprint ends 566 m short of it. The scene is therefore kept on the CDSE side only. The ledger rightly has no row: the Earth Search SCL is nodata on all 27 pixels of that polygon, so the pipeline had nothing to read. The check counted a missing scene that is a comparison artefact, and it will recur on other swath-edge passes. Fix: decide AOI membership once per datatake, not per catalogue footprint. A datatake that both catalogues list in the bbox and window under the cloud limit, and whose footprint intersects the AOI in only one of them, is a footprint-edge case: reported in the check detail and not counted as a mismatch. This applies to discovery_checks (copernicus.py) and to the ledger-versus-CDSE count check in count_checks (freshness.py). A datatake one catalogue does not list at all stays a mismatch. The cloud-cover straddle limit in the copernicus.py docstring is a separate known limit and is out of scope.

## Acceptance Criteria

- [ ] A test written first fails on main: one datatake listed by both catalogues
- [ ] with only the CDSE footprint intersecting an AOI polygon and no ledger row
- [ ] makes freshness_count_vs_copernicus pass with measured 0.0 and names the product under a footprint_edge key in the check detail
- [ ] The same case passes discovery_vs_copernicus
- [ ] with the scene under footprint_edge in the detail
- [ ] The mirrored case
- [ ] where only the Earth Search footprint intersects the AOI and the ledger holds the scene
- [ ] is treated the same way in both checks
- [ ] A datatake that CDSE lists inside the AOI and Earth Search does not list at all still fails both checks
- [ ] proven by a test
- [ ] freshness_count_vs_earth_search results are unchanged
- [ ] proven by the existing tests passing unmodified
- [ ] A regression test uses the real footprints of the 2026-10-14 50HMK items from both catalogues and the geometry of dea-qd4xhuft4_v3
- [ ] stored as a small fixture under tests/ with its sources named
- [ ] The copernicus.py module docstring states the footprint rule
- [ ] and LEARNINGS.md Live run findings records the 2026-10-14 50HMK case with its numbers
- [ ] ruff check
- [ ] ruff format --check
- [ ] mypy and pytest all exit 0

## Implementation Plan

# st-9812 plan: decide AOI membership once per datatake

Verified in the worktree `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-9812` (HEAD ad1fe76, no prerequisite changes since the story was written). All story pointers are correct. Reality check results:

- `normalise_scenes` in `src/wetland_change/verify/copernicus.py` drops an item when its own footprint misses every AOI polygon, then dedups by datatake key. This is the bug.
- `discovery_checks` (copernicus.py) and `count_checks` / `_scenes` / `_compare` (freshness.py) are the only consumers. `list_tile_counts` (freshness.py) is used only by `tests/test_live_verify.py` and `tests/test_verify_freshness.py`. No test calls `normalise_scenes` directly and nothing else constructs `Scene`.
- The live items are fetchable without an account, and I confirmed the numbers with shapely. The Earth Search 50HMK 2026-10-14 footprint does not intersect dea-qd4xhuft4_v3. The CDSE footprint does, covering 53.9 percent of the polygon. Cloud cover is 0.299191 (ES) and 0.3 (CDSE). The CDSE `grid:code` is MGRS-50HMK. The ES `s2:product_uri` is `S2C_MSIL2A_20261014T020311_N0513_R017_T50HMK_20261014T062152.SAFE`, and the CDSE id is the same name without `.SAFE`.
- The polygon is in `/Users/jarrodbaker/Documents/swan-wetland-change/data/external/dea_waterbodies_v3_swan.geojson` (EPSG:4326, MultiPolygon, uid `qd4xhuft4_v3`, area_m2 2700). The polygon_id in code is `dea-qd4xhuft4_v3`.
- `tests/test_sources.py` requires the sha256 of every file in `FIXTURE_DIRS` to appear in `data/SOURCES.md`, so the new fixture directory needs a SOURCES row and a FIXTURE_DIRS entry.

## Design

Semantics, applied identically to both checks:

1. `Scene` gains `in_aoi: bool = True`. `normalise_scenes` keeps the cloud filter and no longer drops on footprint. It sets `in_aoi` from the item's own footprint. Dedup within one catalogue sorts by `(not in_aoi, name)`, so a duplicate that intersects wins, which preserves today's result.
2. New `Reconciled` dataclass and `reconcile_footprints(es_all, cdse_all)` in copernicus.py, deciding per datatake key:
   - Listed by both and `in_aoi` agrees: both True keeps both scenes, both False drops both.
   - Listed by both and `in_aoi` differs: a footprint-edge case. Both scenes are dropped from the compared sides and recorded in `footprint_edge: dict[key, cdse Scene]`.
   - Listed by one catalogue only: kept only if its own footprint intersects, exactly as before, so it still fails as a mismatch.
3. `discovery_checks` reconciles, then compares as before. Detail gains `footprint_edge`, a sorted list of CDSE product names for that tile, always present.
4. `freshness.py`: `_scenes` returns every cloud- and window-filtered scene with its `in_aoi` flag. `list_tile_counts` keeps its behaviour by filtering `in_aoi` (the existing tests stay unmodified). In `count_checks`:
   - `freshness_count_vs_earth_search` keeps filtering ES by its own footprint. It must NOT use the reconciled set, or it would start failing on the CDSE-only case. Its detail gains no new key.
   - `freshness_count_vs_copernicus` uses the reconciled CDSE side when the ES listing succeeded. Edge keys are removed from both the ledger side and the CDSE side before comparing, so the check passes with measured 0.0 in both directions, and `footprint_edge` lists the CDSE names for that tile.
   - If the ES search raised, the CDSE check falls back to its own footprint filter with an empty `footprint_edge`, and the existing skip behaviour for ES stays.
5. Docs: the copernicus.py module docstring states the footprint rule. The freshness.py docstring gets one sentence. LEARNINGS.md "Live run findings" records the 2026-10-14 50HMK case.

## Steps

1. Batch 1, fixture: create `tests/fixtures/footprint_edge_50hmk_20261014/` with `es_item.json`, `cdse_item.json`, `dea_qd4xhuft4_v3.geojson`, and a SOURCES.md row with the file sha256s and named sources. Add the dir to `FIXTURE_DIRS` in `tests/test_sources.py`. Proves: the checksum and host tests stay green.
2. Batch 1, LEARNINGS.md entry (independent file).
3. Batch 2, copernicus.py, tests first. Write failing tests in `tests/test_verify_copernicus.py`: synthetic CDSE-only footprint, mirrored ES-only footprint, CDSE-listed with ES not listed at all (still fails), the real-footprint regression, and normalise dedup. Confirm they fail on main, then implement `Scene.in_aoi`, `reconcile_footprints` and the `discovery_checks` change, and update the module docstring.
4. Batch 3, freshness.py, tests first. Write failing tests in `tests/test_verify_freshness.py`: both directions for the CDSE count check, ES count check unchanged on the same inputs, one-sided still fails, ES search failing still gives CDSE checks, and the real-footprint regression. Then implement, update the docstring, and run the full verification order.

## What each test proves

- CDSE-only footprint, no ledger row: `freshness_count_vs_copernicus` passes, measured 0.0, `footprint_edge == [cdse name]`. `discovery_vs_copernicus` passes with the same key. This is the red test on main.
- Mirrored (ES footprint only, ledger holds the scene): the same pass in both checks.
- CDSE lists inside the AOI and ES does not list the datatake: both checks still fail, so the rule does not hide real misses.
- The ES count check on the CDSE-only case still passes with no `footprint_edge` key, and the existing ES tests pass unmodified.
- Real fixture: the true 2026-10-14 footprints plus the true polygon reproduce run 42548248931 on main (measured 1.0) and pass after the fix.
- Existing `test_list_tile_counts_*` and the over-cloud/outside-polygon test prove the filters are preserved.

## Implementation Notes

- 2026-11-12T04:10:45.897Z: Built via build-flow run wf_fdb63410-5ca in 3 batches, each reviewed clean. Scene gains in_aoi; normalise_scenes flags instead of dropping on footprint; reconcile_footprints decides membership per datatake; discovery_vs_copernicus and freshness_count_vs_copernicus report footprint_edge and do not count it; freshness_count_vs_earth_search keeps Earth Search's own footprint filter. Fixture tests/fixtures/footprint_edge_50hmk_20261014 holds the real footprints (re-measured: CDSE covers 0.5388 of dea-qd4xhuft4_v3, CDSE minus Earth Search 68.82 km2, Earth Search footprint 566.36 m from the polygon), rowed in data/SOURCES.md. Red first on unmodified code: measured 1.0 on the synthetic and real-footprint cases. Final verification: ruff check, ruff format --check, mypy and pytest all exit 0.
- 2026-11-14T02:10:32.462Z: touches-expansion: overlaps st-a32a (stories/st-747e-record-the-first-trial-week-runner-timin.md, stories/st-9812-stop-a-catalogue-footprint-difference-fa.md, stories/st-a32a-stop-uncalibrated-dea-waterbodies-rows-d.md, stories/st-b6bf-decide-whether-ramsar-21-needs-its-own-w.md, stories/st-da75-measure-why-ramsar-ndvi-rows-miss-the-de.md, stories/st-dd0d-decide-a-live-water-limit-for-the-dea-wa.md) — coordinate or split

## Questions
