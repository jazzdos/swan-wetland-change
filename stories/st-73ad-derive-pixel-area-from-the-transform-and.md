---
id: st-73ad
title: Derive pixel area from the transform and pin the vector engine
type: chore
priority: P3
depends_on: []
discovered_from: st-ff89
touches: [src/wetland_change/aoi.py, src/wetland_change/stats.py, tests/test_aoi.py, tests/test_stats.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

src/wetland_change/stats.py:22 hard-codes PIXEL_AREA_HA = 0.01 and multiplies it into water_ha_index and water_ha_scl (stats.py:130-131); nothing checks the window transform against 10 m or the CRS for metric units. The value is right for today's 10 m EPSG:32750 inputs. src/wetland_change/aoi.py:42 calls gpd.read_file without an engine, so the reader follows whatever packages are installed. Found by the st-ff89 reproducibility audit, which fixes nothing.

## Acceptance Criteria

- [ ] Pixel area in hectares is computed from the window transform of the BandStack and the code raises when the CRS is not projected in metres or the pixel step is not 10 m.
- [ ] A test feeds a 20 m transform and asserts the error.
- [ ] stats.PIXEL_AREA_HA is removed or derived
- [ ] and tests/test_stats.py passes with the derived value.
- [ ] gpd.read_file in src/wetland_change/aoi.py passes engine="pyogrio".
- [ ] The four verification gates pass.

## Implementation Plan

Verified in worktree /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-73ad (HEAD 064b577). Pointers hold: stats.py:22 `PIXEL_AREA_HA = 0.01`, used at stats.py:130-131; aoi.py:42 `gdf = gpd.read_file(path)`. BandStack (src/wetland_change/raster/read.py:107) has `transform: Affine` and `epsg: int`. pyogrio>=0.10 is already a declared dependency (pyproject.toml, uv.lock has 0.13.0) and pyproj 3.8 is installed, so no dependency change. Only tests/test_stats.py imports PIXEL_AREA_HA (lines 17, 75, 76, 94, 107, 152, 187, 192, 224, 233, 256, 257); the only other mentions are docs (audit doc, old plan), which stay unchanged.

1. TDD red, tests/test_stats.py: remove `PIXEL_AREA_HA` from the stats import and import `pixel_area_ha`. Add module constant `PIXEL_AREA_HA = pixel_area_ha(T, 32750)` after `T` is defined, so every existing assertion (all `n * PIXEL_AREA_HA`) now exercises the derived value, plus `test_pixel_area_ha_is_derived_from_transform` asserting it equals 0.01 (approx). Add `test_pixel_area_ha_rejects_20m_transform` (Affine(20,0,0,0,-20,40), epsg 32750, `pytest.raises(ValueError, match="10 m")`), `test_pixel_area_ha_rejects_non_square_pixel` (Affine(10,0,0,0,-20,40)), `test_pixel_area_ha_rejects_rotated_transform` (Affine(10,1,0,0,-10,40)), `test_pixel_area_ha_rejects_geographic_crs` (Affine(10,0,0,0,-10,40), epsg 4326, match "projected"), `test_pixel_area_ha_rejects_non_metre_projected_crs` (a US-foot projected CRS e.g. EPSG:2263, match "metre"), and `test_summarise_rejects_20m_stack` which builds `BandStack(... transform=Affine(20,0,0,0,-20,40), epsg=32750)` from `_stack()` arrays and asserts `summarise(...)` raises ValueError (proves the guard is wired into summarise, not just the helper). Run `uv run pytest tests/test_stats.py -q`: fails on import.
2. Implement in src/wetland_change/stats.py: delete the `PIXEL_AREA_HA = 0.01` line. Add `PIXEL_STEP_M = 10.0` and `pixel_area_ha(transform: Affine, epsg: int) -> float`. It builds `CRS.from_epsg(epsg)` (pyproj), raises ValueError unless `crs.is_projected` ("EPSG:x is not a projected CRS") and every axis_info unit_conversion_factor is 1.0 (metres, message contains "metre"); raises ValueError if `transform.b` or `transform.d` is non-zero (rotated, within 1e-9); raises ValueError containing "10 m" unless `math.isclose(abs(transform.a), 10.0, abs_tol=1e-6)` and the same for `abs(transform.e)`; returns `abs(transform.a) * abs(transform.e) / 10_000`. In `summarise`, compute `pixel_ha = pixel_area_ha(stack.transform, stack.epsg)` as the first statement and use it for water_ha_index and water_ha_scl (lines 130-131). Update the BandStack-using docstring of summarise to mention it raises ValueError on non-10 m or non-metric stacks. Add `import math` and `from pyproj import CRS`.
3. aoi.py:42 change to `gpd.read_file(path, engine="pyogrio")`. Add a test in tests/test_aoi.py (use the existing fixture pattern in that file) that monkeypatches `wetland_change.aoi.gpd.read_file` with a wrapper recording kwargs and delegating to the real function, calls the existing loader helper for a GeoJSON fixture, and asserts `engine == "pyogrio"`. This proves the engine is pinned.
4. Run the four gates one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts` (run `uv run ruff format` on touched files if needed), `uv run mypy src scripts`, `uv run pytest -q`. All must pass. Commit with the repo convention.
## Orchestrator amendments

These override the text above where they differ.

1. Agents commit nothing, including the commit in step 3; the orchestrator commits after the run. Uncommitted work at the end of a task is expected and is not a defect, and reviewers must not report it. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**.
2. Never call AWS for the project's own bucket, never run terraform plan or apply, never run compaction against S3, and never run `-m live` tests. Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data.
3. Gates, one command each, judged by exit code: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`, `GITHUB_ACTIONS=true uv run pytest -q`. Never clear addopts for a gate; for a count use `-o addopts="-m 'not live'"`. Run ruff format only on files you touched.
4. Story-specific:
   - Outputs must stay byte-identical for today's 10 m EPSG:32750 inputs. Any existing golden or byte-identical test must pass unedited; if one fails, report it and do not regenerate or loosen a golden file.
   - If an existing test calls `summarise` with a non-10 m or non-metric BandStack and now fails, report which test and why in the summary, and fix the test fixture only if the fixture is plainly unrealistic (not the guard).
   - pyproj is already a direct dependency; do not change pyproject.toml or uv.lock.
   - Touch only src/wetland_change/stats.py, src/wetland_change/aoi.py, tests/test_stats.py and tests/test_aoi.py unless a failing test forces otherwise, and name any other file in the summary.
5. Docs and docstrings are flat factual prose with no em dashes.

## Implementation Notes

- 2026-11-06T07:20:17.440Z: Commit 7223cac. stats.pixel_area_ha(transform, epsg) derives hectares from the BandStack transform and raises for non-projected, non-metre, rotated or non-10 m stacks; tests cover a 20 m transform, non-square, rotated, EPSG:4326, EPSG:2263 and summarise with a 20 m stack. PIXEL_AREA_HA removed from src; tests/test_stats.py derives it. aoi.py pins engine=pyogrio with a recording test. Gates pass, 939 passed.

## Questions
