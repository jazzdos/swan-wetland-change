---
id: st-eb5a
title: Add a geometry-only checksum for DEA Waterbodies
type: chore
priority: P3
depends_on: []
discovered_from: st-ff89
touches: [data/SOURCES.md, scripts/fetch_aoi.py, tests/test_fetch_aoi.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

A fetch on 2026-11-06 gave checksum 5e83c045 against the recorded 7d993aa8 (data/SOURCES.md:7). A comparison with the 2026-11-02 backfill copy found 1404 features with the same uids and identical geometry; only dt_wetobs, dt_satpass, dt_updated and wet_sa_m2 differ. The stable_geojson_checksum in scripts/fetch_aoi.py:93-115 covers those refreshable properties, so a DEA refresh changes it and a fresh clone cannot confirm it holds the same polygons. Found by the st-ff89 reproducibility audit, which fixes nothing.

## Acceptance Criteria

- [ ] scripts/fetch_aoi.py prints a second checksum over the sorted uid and geometry of every feature.
- [ ] Two payloads that differ only in dt_updated or wet_sa_m2 give the same geometry checksum
- [ ] shown by a test in tests/test_fetch_aoi.py.
- [ ] Two payloads that differ in one feature's geometry give different geometry checksums
- [ ] shown by a test.
- [ ] The DEA Waterbodies row in data/SOURCES.md records both checksums and says what each covers.
- [ ] The four verification gates pass.

## Implementation Plan

## Findings
- `scripts/fetch_aoi.py:93-115` `stable_geojson_checksum(content: bytes) -> str` hashes the whole payload minus top-level `timeStamp`, so it covers refreshable properties (dt_wetobs, dt_satpass, dt_updated, wet_sa_m2). Keep it unchanged (existing tests and the SOURCES row depend on it).
- `main()` computes `wb_sha = stable_geojson_checksum(wb_bytes)` inside the try/except ValueError block and prints one DEA Waterbodies SOURCES row.
- `tests/test_fetch_aoi.py` has helpers `_collection()` (2 features, uid r3f0 and r3f1), `_dump()`, `_setup_main()`, and `test_main_prints_stable_waterbodies_and_raw_ramsar_checksums`.
- `data/SOURCES.md` line 7 is the DEA Waterbodies v3 row (checksum 7d993aa8...); the paragraph under the table describes it and says to confirm geometry separately. `tests/test_sources.py` only checks hosts and fixture sha256s, so editing this row is safe.
- `data/external/` does not exist in the worktree or main checkout, so the real geometry checksum needs a live WFS fetch (no login).

## Steps (TDD)
1. Tests first in `tests/test_fetch_aoi.py` (import `geometry_checksum`; fails with ImportError until step 2):
   - ignores refreshable properties (dt_updated, dt_wetobs, dt_satpass, wet_sa_m2, top-level timeStamp): raw sha and stable checksum differ, geometry checksum equal. Proves AC2.
   - one feature's vertex changed: checksums differ. Proves AC3.
   - feature order and formatting ignored; uid change detected; other top-level fields and feature `id` ignored.
   - known-answer test against the exact canonical bytes.
   - malformed payloads (bad JSON, non-object, no features list, missing/null uid, missing geometry) raise ValueError.
   - main() prints the geometry checksum in the DEA Waterbodies row alongside the stable checksum.
2. Implement `geometry_checksum(content: bytes) -> str` in `scripts/fetch_aoi.py`: sha256 over canonical JSON of records `[str(uid), geometry]` sorted by (uid, canonical geometry JSON); covers only `properties.uid` and `geometry`. Update module docstring.
3. In `main()` compute `geo_sha` inside the existing try block and print both checksums in the DEA Waterbodies row, each labelled.
4. Run `uv run pytest -q tests/test_fetch_aoi.py`.
5. Fetch live (without writing data/external) to compute the real stable and geometry checksums (expect 1404 features); run twice to confirm geometry checksum is repeatable.
6. Edit `data/SOURCES.md` line 7 and the paragraph below the table: record both checksums, what each covers, that the full one changes on DEA property refreshes, and that the geometry one confirms the same polygons.
7. Run the four gates one per line and commit with prefix `st-eb5a:`.

## What the tests prove
Refresh-only differences leave the geometry checksum equal while the full checksum differs (AC2); a single-feature geometry change moves it (AC3); order, formatting and non-uid ids do not matter, uid does; malformed payloads fail closed; main() prints it in the SOURCES row.
## Orchestrator amendments (override anything above that conflicts)

1. Agents commit nothing. This overrides the plan's commit step in STEP 5. The orchestrator commits after the run. Uncommitted work is expected and is not a defect; reviewers must not report it. Put notes, checksum values and gate results in the summary. Never edit `stories/**` or `.agents/**`.
2. No AWS calls for the project's own bucket, no terraform plan or apply, no S3 compaction, no `-m live` test runs. Anonymous reads of the public DEA geoserver WFS are allowed for computing the checksums in STEP 3. Nothing is written under `/Users/jarrodbaker/Documents/swan-wetland-change-data`, under `data/external`, or in the main checkout `/Users/jarrodbaker/Documents/swan-wetland-change` (work only in the worktree). Any temporary file goes under pytest `tmp_path` or a temporary directory that is deleted afterwards.
3. Gates, one command per line, judged by exit code: `uv run ruff check src tests scripts`; `uv run ruff format --check src tests scripts`; `uv run mypy src scripts`; `uv run pytest -q`; `GITHUB_ACTIONS=true uv run pytest -q`. Never clear or override pytest addopts.
4. Story-specific:
   - Keep `stable_geojson_checksum` and its existing tests unchanged.
   - Also compute `geometry_checksum` and `stable_geojson_checksum` over the read-only 2026-11-02 backfill copy `/Users/jarrodbaker/Documents/swan-wetland-change-data/aoi/dea_waterbodies_v3_swan.geojson` (read it, never write it) and report whether its geometry checksum matches the live one. If they match, say so in the SOURCES paragraph (the 2026-11-02 backfill copy has the same geometry checksum).
   - The SOURCES row records the fetch date and both full checksums, each labelled with what it covers, and keeps the note that the 2026-10-29 full checksum was 7d993aa8.
   - `tests/test_sources.py` keeps passing.
   - Touch only `scripts/fetch_aoi.py`, `tests/test_fetch_aoi.py` and `data/SOURCES.md`.
5. Docs and SOURCES text are flat factual prose with no em dashes.

## Implementation Notes

- 2026-11-06T07:54:08.930Z: geometry_checksum added beside the unchanged stable_geojson_checksum; fetch_aoi main prints both. Live WFS fetch 2026-11-06, run twice, 1404 features: full 5e83c045a4e7d1d9c810c905d588e5eb0eab41a4443f78ebdd396babadfa3772, geometry 5bef29a42a52a00a16272c0ca810ab83eeb5feac9e27ad24aff238649cd0d10f. The read-only 2026-11-02 backfill copy has full 7d993aa8 (the 2026-10-29 value) and the same geometry checksum, so the polygons are unchanged and only refreshable properties moved. SOURCES row and paragraph updated. 967 passed, five gates green.

## Questions
