---
id: st-5f74
title: Populate dea_wo_agreement or record why the column stays null
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [AGENTS.md, LEARNINGS.md, README.md, data/SOURCES.md, docs/decisions/0002-three-water-columns.md, docs/decisions/0009-dea-wo-agreement-populated-at-processing-time.md, docs/plans/2026-10-29-swan-wetland-change-design.md, docs/research/2026-11-06-wo-availability.csv, docs/research/2026-11-06-wo-availability.py, docs/research/2026-11-06-wo-availability.txt, src/wetland_change/cli.py, src/wetland_change/pipeline.py, src/wetland_change/stats.py, src/wetland_change/verify/run.py, src/wetland_change/verify/wo.py, tests/test_cli.py, tests/test_config.py, tests/test_stats.py, tests/test_wo_availability.py, tests/test_wo_observation.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-06
---

## Description

AGENTS.md (locked decisions), ADR 0002 and design line 179 say each observation stores the DEA Water Observations agreement. src/wetland_change/stats.py:131 writes None on every row and the agreement exists only in the verification report. No decision records the change. README.md lists this as a limitation. Found while checking the st-06a8 README, not by the review. DEA keeps the product for three months, so a backfill could not fill it. Needs a decision between populating recent rows and amending the locked decision.

## Acceptance Criteria

- [ ] Observation rows hold the DEA agreement when a matching WO item exists or an ADR records why the column stays null
- [ ] AGENTS.md and the design match whichever is chosen

## Implementation Plan

# st-5f74 plan: populate `dea_wo_agreement` or record why it stays null

Worktree: `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-5f74` (branch story/st-5f74, base b3e6404). Nothing is committed by implementers. Do not edit `stories/**` or `.agents/shousper-stories/local/**`.

## What exploration verified

- `src/wetland_change/stats.py:131` writes `dea_wo_agreement=None`; field is `float | None` (line 45). `summarise()` has no reader or DEA access and `stats.py` cannot import `verify/wo.py` (wo.py imports `stats.water_pixels`, so that would be a cycle). The only place both the stack and a reader exist is `pipeline.process_scene` (pipeline.py:68), which calls `summarise` per polygon and is reached from `_process_one` (run_once and backfill_once). `cli.run` (cli.py:145) and `cli.backfill` (cli.py:193) build the readers.
- `verify/wo.py` already holds everything: `find_wo_href(scene, bbox_4326)` (one DEA STAC POST, timeout 60, raises on HTTP error), `dea_reader()`, `wo_agreement`, and `wo_check(...)`, whose `Check.measured` is the agreement over mutually clear pixels (None when the grid differs or n == 0). `wo_check` builds its clear mask as `clear_mask(scl, green, nir, swir16) & inside` (no red band), uses `water_pixels(water.for_polygon(polygon_id), ...)`, and the WO clear rule `(wo & 127) == 0`. Reusing `wo_check(...).measured` gives exactly the number in the verification report and keeps wo.py the single implementation. `summarise`'s own `clear` mask also requires red, so the stored `n_clear` can differ from the agreement's pixel set by a few pixels; the ADR must say so.
- `scene.tile` is `grid:code` minus `MGRS-` (e.g. `50HLK`); `find_wo_href` matches `/{tile[2:]}/` in the asset href. DEA STAC `next` links carry `"merge": true` and a body like `{"_o": 1}`, which must be merged into the original search body.
- ADR 0009 is the next free number (0008 is the latest). `data/SOURCES.md` has no row for `ga_s2_wo_provisional_3` although verify reads it and the pipeline would now store a derived value; add one in this change.
- Planner's exploratory measurement (not recorded, not blind, disclose in LEARNINGS): DEA WO `properties.created` for 50HLK/50HLJ passes is 07:32 to 09:42 UTC the same day as acquisition (about 02:26 UTC). Earth Search `created` is about 06:34 to 08:43 UTC. The cron is `17 10 * * *`. A rough pass over 2026-08-08..2026-11-05 (cloud cover at most 20, 6 tiles, bbox [115.3,-33.2,116.0,-31.6]) found a WO item before the first cron for 49 of 49 scene-tiles, with a smallest margin of 0.4 hours. That pass had a pagination bug (it replaced the search body instead of merging), so the real script must be written and run properly. Expected outcome is populate, but the pre-registered rule decides.
- Existing tests that pin None: `tests/test_stats.py:78`, `test_change.py:65`, `test_change_outputs.py:103,270`, `test_geoparquet.py:53`, `test_pipeline.py:556,648`, and `tests/test_golden_run/test_fixture_run_observation_rows_golden.yml`. Under the populate design, `run_once` takes optional `wo_lookup`/`wo_reader_factory` defaulting to None (no DEA lookup), so every existing offline test and the golden stay None unchanged; only `cli.run` passes the real lookup.

## Steps

### Batch 1, task T1: pre-register, measure, record the outcome (no src changes)

1. Append to `LEARNINGS.md`, before `## Spike results`, a section `## Pre-registered hypotheses (st-5f74, 2026-11-06)` containing the sample definition, the metrics, the hypothesis H1 (share at least 0.90, recorded whether or not it holds), the decision rule, the "WO arrives later" semantics, and the disclosure of the exploratory pass. Written before the script is run and never edited afterwards.
2. TDD `docs/research/2026-11-06-wo-availability.py` (stdlib plus `requests`, anonymous public reads of Earth Search and DEA STAC only, no raster reads). Pure functions are tested offline in `tests/test_wo_availability.py` (loads the script by path like `tests/test_config.py` does for the exit-rule script): `next_cron` (created exactly at 10:17:00 maps to itself, 10:17:01 maps to next day, midnight maps to same day 10:17), item-to-row matching by (UTC acquisition date, tile), cloud filter, window filter, `summarise_rows` (share, Wilson 95 percent interval, nearest-rank lag quantiles, by-month counts, +2h sensitivity), `decide` (0.5 boundary: 0.5 gives populate), `fetch_all` pagination merging `merge: true` next bodies (fake session).
3. Run it live once, commit-ready outputs `docs/research/2026-11-06-wo-availability.csv` and `.txt`.
4. Append `### DEA WO availability at first processing (2026-11-06)` to LEARNINGS.md (after the ramsar-12 section, before `## Live run findings`) with the numbers and a line `Outcome: populate` or `Outcome: amend`.

### Batch 2, task T2: populate code (skip entirely if the outcome is amend)

TDD, tests first and seen red:

1. `verify/wo.py`: add `SceneWo` (href, reader, `failed` flag), `resolve_scene_wo(scene, bbox, *, lookup, reader_factory)` and `observation_agreement(...)`, which calls `wo_check(..., min_clear_pixels=1)` and returns `check.measured` or None. Every DEA error (lookup, reader factory, grid open, read) is caught, logged at warning with item id and polygon id, and yields None. After the first error in a scene, `SceneWo.failed` is set and the remaining polygons of that scene skip DEA, so an outage costs one retry cycle per scene and not one per polygon. Move the `WoLookup` alias into wo.py and import it in `verify/run.py`.
2. `pipeline.process_scene`: new keyword-only `wo_lookup: WoLookup | None = None`, `wo_reader_factory: Callable[[], RasterReader] = dea_reader`. After the grid and ESA guards it resolves the WO item once per scene using `union_bbox_4326(polygons)`, then per polygon rasterises `inside` and does `dataclasses.replace(row, dea_wo_agreement=...)`. `_process_one` and `run_once` pass the two arguments through. `backfill_once` passes nothing, so backfill rows stay null (backfill dates are mostly older than DEA's three-month retention, and a lookup per old scene would be wasted calls).
3. `cli.run` passes `wo_lookup=find_wo_href, wo_reader_factory=dea_reader`; `cli.backfill` does not.
4. `stats.py`: comment on the field and a docstring line that `summarise` leaves it None and `process_scene` fills it.

What each test proves (new file `tests/test_wo_observation.py` unless noted):
- observation agreement equals `wo_check(...).measured` on the same inputs: single implementation, same mask, same polygon setting (include an override polygon).
- None when the WO grid differs, when WO flags every pixel (no mutually clear pixel), when the lookup returns None.
- A lookup that raises, a reader factory that raises, and a reader whose `read` raises each give rows with None, no exception, and a logged warning (caplog). The circuit breaker: after one read error the reader is not touched again for the other polygons of the scene.
- `process_scene` with a fake lookup and a fake DEA reader serving a known WO array fills the expected float for each polygon and leaves other columns identical to the no-lookup run.
- `run_once` end to end with a raising lookup: `manifest.failed == 0`, `processed == 1`, stored `dea_wo_agreement` null. With a working fake lookup: stored value non-null float64 and a second run with the same `now` is byte-identical (idempotent).
- `tests/test_cli.py`: `run` passes both arguments to `run_once` (monkeypatched capture), `backfill` does not.
- `tests/test_stats.py:78`: keep the None assertion and rename the test so it states `summarise` leaves the column for `process_scene`. Other None pins are explicit fixture values and the golden is unchanged because no lookup is passed.

### Batch 3, task T3: ADR 0009, docs and the ADR tests (either branch)

1. `tests/test_config.py` (tests first, red until the ADR exists): `test_adr_0009_recorded_sha256_match_committed_research_files` (script and csv sha256 lines in the `SHA_LINE` format, same pattern as ADR 0007 and 0008) and `test_adr_0009_availability_matches_recomputation` (parses `Share available at first processing: K of N` and `Chosen outcome: populate|amend` from the ADR, recomputes both from the committed CSV with the script's `load_rows`, `summarise_rows` and `decide`, and asserts equality).
2. `docs/decisions/0009-<slug>.md`, status line exactly `Status: accepted, 2026-11-06, pending Jarrod's review of the epic.`, plain statement that the orchestrator made the decision under Jarrod's delegation, context, the pre-registered rule, the measured numbers, decision, consequences. Slug `dea-wo-agreement-populated-at-processing-time` (populate) or `dea-wo-agreement-stays-null` (amend).
3. Edit ADR 0002 (add an "Amended by 0009" note to Decision and Consequences; do not rewrite history), `AGENTS.md` locked decision, design line 179 (and the line 332 risk row if its wording conflicts), `README.md` (intro bullet near line 20, Design choices row, the Limitations bullet near line 344, and the run-stage text if it mentions the column), `data/SOURCES.md` row for `ga_s2_wo_provisional_3`.
4. Append the final one-paragraph result to the LEARNINGS.md section from T1 only if T1 left it open; never edit the pre-registration text.

## Gates (run in order, each judged by exit code)

```
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src scripts
uv run pytest -q
GITHUB_ACTIONS=true uv run pytest -q
```
Count: `uv run pytest -q -o addopts="-m 'not live'"`. No live tests in the default suite; the research script is run by hand once, not by pytest.
## Orchestrator amendments

1. Commit nothing; the orchestrator commits. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**. Never call AWS for the project's own bucket. Never run terraform. No live tests in the default suite. Judge pytest by exit code and never clear addopts; for a count use -o addopts="-m 'not live'". Also run GITHUB_ACTIONS=true uv run pytest -q. Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data. Docs and comments are flat factual prose with no em dashes.
2. The decision is the pre-registered rule's, not the expected one: if the recorded script gives S < 0.50, record amend and skip T2, even though the exploratory pass suggested populate.
3. The new data/SOURCES.md row for ga_s2_wo_provisional_3 follows the format of the existing rows for live-read sources (URL, licence CC BY 4.0, fetch date, checksum column as the existing live rows do it, CRS EPSG:32750, redistribute_public).

## Implementation Notes

- 2026-11-06T02:35:42.465Z: Pre-registered rule (populate if S >= 0.50) recorded in LEARNINGS.md before the recorded script ran. Measured 44 of 44 scene-tiles with a DEA WO item before the first 10:17 UTC run (Wilson 0.92 to 1.00, smallest margin 21 min, +2h sensitivity also 44 of 44). Outcome populate: the daily run fills dea_wo_agreement via verify/wo.py observation_agreement (equals wo_check measured), None on no item, no clear pixel, grid mismatch or any DEA error (logged, circuit breaker per scene). Backfill rows stay null. ADR 0009 accepted pending Jarrod's review of the epic. Commit e2d3412; 839 passed, 9 deselected; all five gates exit 0.

## Questions
