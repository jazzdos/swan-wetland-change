---
id: st-70d1
title: "Milestone 2: backfill and change detection"
type: epic
priority: P1
depends_on: []
touches: []
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Milestone 2, part one: turn the Milestone 1 daily pipeline into a seasonal change detector. Read first: `docs/plans/2026-10-29-swan-wetland-change-design.md` (Run stages 1 to 7, Change detection, pre-registered hypotheses) and `docs/handoffs/2026-10-29-milestone-1.md`.

Decisions taken at board approval on 2026-10-29:

- Collection 1 only; decision 0001 stands. Earth Search `sentinel-2-c1-l2a` has no scenes before 2022-12 for five of the six tiles (LEARNINGS.md, S4), so the backfill and the baseline start at 2022-12-01. The other 2022 sources were checked live and rejected: Earth Search `sentinel-2-l2a` and Planetary Computer carry processing baseline 04.00, and 54 of 60 Earth Search `sentinel-2-l2a` items had `earthsearch:boa_offset_applied` true while still advertising the offset. CDSE carries baseline 05.10 but needs credentials and serves JPEG 2000. Hypothesis 2 is tested on 2023 only, and its 2022 half is recorded as untestable.
- A worker runs the full backfill locally into a persistent output root outside every worktree: `/Users/jarrodbaker/Documents/swan-wetland-change-data/outputs`.

Shared conventions: `uv run pytest` runs the offline suite; network tests carry `@pytest.mark.live` and run with `-m live`; ruff check, ruff format and `uv run mypy src scripts` (strict) stay clean. AOI files under `data/external/` are gitignored: run `uv run python scripts/fetch_aoi.py` before any live run. `PROJ_LIB` must stay unset (LEARNINGS.md, S8).

## Implementation Plan

## Implementation Notes

## Questions
