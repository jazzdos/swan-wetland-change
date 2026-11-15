---
id: st-22f1
title: Add the DBCA-010 CC BY-NC 4.0 attribution and licence to the published files
type: feature
priority: P2
complexity: hard
depends_on: []
discovered_from: st-1a9c
touches: [.github/workflows/backfill.yml, AGENTS.md, README.md, docs/plans/2026-10-29-swan-wetland-change-design.md, scripts/fetch_aoi.py, src/wetland_change/cli.py, src/wetland_change/dbca_attribution.py, src/wetland_change/outputs/changes.py, src/wetland_change/outputs/dbca_backfill.py, src/wetland_change/outputs/geoparquet.py, src/wetland_change/stac/catalogue.py, tests/test_catalogue.py, tests/test_change_outputs.py, tests/test_cli.py, tests/test_dbca_attribution.py, tests/test_dbca_backfill.py, tests/test_dbca_licence_text.py, tests/test_fetch_aoi.py, tests/test_geoparquet.py, tests/test_licence.py, tests/test_readme.py, tests/test_verify.py, tests/test_workflows.py]
exclusive: false
created: 2026-11-15
updated: 2026-11-15
---

## Description

st-1a9c (docs/research/2026-11-14-public-release-licences.md, term T3). On 2026-11-15 Jarrod approved the orchestrator's recommendation ("approved recommended that unblock stories") that DBCA-010 Ramsar Sites, and the published files that carry its polygons, site names and object ids, are published under CC BY-NC 4.0, the licence the custodian states in its own catalogue entry (https://catalogue.data.wa.gov.au/dataset/ramsar-sites, fetched 2026-11-14). This is the project's adopted reading, not a confirmation from DBCA; see the st-1a9c notes.

What is known:

- Observation and change Parquet hold DBCA-010 polygons, site names (ram_ramsarname, as `site`) and object ids (in `polygon_id`) and carry no DBCA attribution. The STAC collection names DBCA as licensor with a homepage only and declares `license` CC-BY-SA-4.0 (`src/wetland_change/stac/catalogue.py` LICENSE) with no rel=license link.
- CC BY-NC 4.0 section 3(a)(1) requires, on sharing the material or adapted material: identification of the creator (Department of Biodiversity, Conservation and Attractions, Western Australia) and any copyright notice DBCA supplies, a licence notice with the URI https://creativecommons.org/licenses/by-nc/4.0/, a link to the dataset, and an indication of modification (reprojected to EPSG:4326, selected by site, used as zonal boundaries). Section 3(a)(2) lets a link to a resource that holds these satisfy it. Section 3(a)(4): the licence the project applies to the adapted files must not stop recipients complying, so files that carry DBCA-010 material state CC BY-NC 4.0. CC BY-NC 4.0 has no ShareAlike term, so the plan's T4 does not apply.
- The patterns to follow are st-8856 (`dea_attribution`, `src/wetland_change/attribution.py`, `src/wetland_change/outputs/attribution_backfill.py`, `add-dea-attribution`) and st-d5c1 (`copernicus_notice`, `src/wetland_change/sentinel_notice.py`, `src/wetland_change/outputs/notice_backfill.py`, `add-copernicus-notice`): a single-source module for the block, a separate footer or metadata key, a STAC collection field and item property, and an add-* backfill command over the output store with `--dry-run` and the last stdout line `scanned N, rewritten M, skipped K, failed F`. The nine provenance footer keys, `dea_attribution` and `copernicus_notice` stay unchanged.
- `.github/workflows/backfill.yml` runs the add-* commands as chained jobs before build-catalogue; `tests/test_workflows.py` pins its job chain and the README "Attribution backfill" section lists the commands (`tests/test_readme.py`).
- Licence text elsewhere: README "Data sources and licences" (`tests/test_licence.py` asserts "CC BY-SA 4.0" appears) and the AGENTS.md locked decision "Ramsar sites (DBCA-010, CC BY-SA 4.0) are the reporting unit". ADRs and dated research notes are historical and are not edited. `data/SOURCES.md` is changed by st-1a9c.
- Which other published file kinds (ledger, run manifests, verification JSON) hold DBCA-010 material is in the st-1a9c note's per-file table; the build checks it against the writers.

Constraints: no agent runs the backfill, makes an AWS call or reads an output-store object (the st-b6bf and st-dd0d blindness rules in LEARNINGS.md). No `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md` is opened. LEARNINGS.md, infra/ and ADRs are not edited. Build agents do not commit or push.

Blocks ADR 0011 step 3 (opening the bucket).

## Acceptance Criteria

- [ ] Observation and change Parquet footers carry the DBCA-010 attribution in a separate key naming DBCA as creator
- [ ] CC BY-NC 4.0 with its URI
- [ ] a link to the dataset and the modification
- [ ] and a test reads it back from a written file
- [ ] The STAC collection license is CC-BY-NC-4.0
- [ ] the collection has a rel=license link to the CC BY-NC 4.0 legal code and a link to the DBCA-010 catalogue entry
- [ ] each item carries the attribution as a property
- [ ] and the catalogue still validates
- [ ] Every other published file kind that the writers show holding DBCA-010 material carries the attribution
- [ ] and a test asserts it
- [ ] An add-dbca-attribution command adds the block to existing files that lack it and changes nothing else
- [ ] supports --dry-run and ends stdout with the scanned
- [ ] rewritten
- [ ] skipped
- [ ] failed summary line
- [ ] and backfill.yml runs it as a job before build-catalogue with its tests updated
- [ ] README 'Data sources and licences'
- [ ] the README attribution backfill section and the AGENTS.md locked decision name CC BY-NC 4.0 for DBCA-010
- [ ] and no file outside docs/decisions and dated docs/research notes states that DBCA-010 is CC BY-SA 4.0
- [ ] uv run ruff check src tests scripts
- [ ] uv run ruff format --check src tests scripts
- [ ] uv run mypy src scripts and uv run pytest -q all exit 0

## Implementation Plan

## st-22f1 implementation plan: DBCA-010 CC BY-NC 4.0 attribution and licence in published files

Worktree: `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-22f1` (branch `story/st-22f1`, from main 816f454). I checked every pointer below against that tree.

### Readings recorded

1. **"No file outside docs/decisions and the dated docs/research notes states that DBCA-010 is CC BY-SA 4.0."**
   - Scope: every file from `git ls-files -z --cached --others --exclude-standard`, so gitignored `outputs/`, `data/external/`, `scratch/` and `.venv/` are never read.
   - Excluded: `.git/`, `.venv/`, `stories/` (board), `.agents/`, `docs/decisions/` (ADRs), `docs/research/` (dated notes and run reports), `docs/handoffs/`, and `docs/plans/*milestone*`.
   - Paths are filtered before any file is read, so no `docs/research/verification-*.md` is ever opened.
   - The criterion names only docs/decisions and docs/research. The handoffs and the milestone plan are excluded on the orchestrator's ruling: they are dated snapshots, historical like the ADRs, and are not edited.
   - The test is stricter than the criterion. It fails on any `by[-_]sa` text (case-insensitive) in a scanned file, not only text that names DBCA-010. Three allowlisted occurrences state no DBCA-010 licence, and each is asserted present and then removed before the check:
     - `SHAREALIKE: Final = "CC BY-SA 4.0 ShareAlike"` in `tests/test_public_release_licences.py`, a column heading of the research note's table.
     - `if "BY-SA" not in licence:` in the same file.
     - The DBCA-019 clause `(CC BY-NC on data.wa.gov.au, CC BY-SA on data.gov.au)` in the design. It is a different dataset's historical licence conflict.
   - The scan test file itself is excluded, since it must hold the pattern.
   - The live design `docs/plans/2026-10-29-swan-wetland-change-design.md` is amended at lines 20, 306 and 330 to CC BY-NC 4.0 with the note `(amended 2026-11-15, st-22f1: see docs/research/2026-11-14-public-release-licences.md)`. No other line changes; the gate checks `git diff --numstat` shows 3/3.
2. **Which file kinds carry DBCA-010 material.** I checked the writers against the Published files table of `docs/research/2026-11-14-public-release-licences.md`.
   - Observation Parquet carries DBCA-010 material: geometry, `site` = ram_ramsarname, and `polygon_id` = ramsar-<objectid> (`aoi.py:73-77`, `geoparquet.py:70`).
   - Change Parquet carries DBCA-010 material: geometry taken from the observations and `polygon_id`, with no site column (`changes.py:78-79`).
   - The STAC collection declares the licence for its assets.
   - STAC items hold none, but the AC asks for a property, so each item gets one anyway.
   - n/a, holding identifiers only: the STAC catalog, run manifests, ledger and write index.
   - n/a, verification JSON: it holds polygon ids (ramsar-<objectid>) and values computed inside the polygons, but no geometry and no site name (`verify/checks.py:189-241` has no site or geometry field). A new test in `tests/test_verify.py` pins this.
   - The verification JSON is also not scanned by the backfill, a fact pinned in `tests/test_dbca_backfill.py`.
   - The research note itself (T3 status `unmet`) is dated and is not edited.
3. **The collection `license` field.** It becomes `CC-BY-NC-4.0`, the most restrictive licence of the content. The CC BY 4.0 `dea_attribution` block and its rel=license link are kept, and a second rel=license link points to the CC BY-NC 4.0 legal code. A `rel="via"` link points to the DBCA-010 catalogue entry. The providers are unchanged.

### Steps

1. **Single-source block.** New `src/wetland_change/dbca_attribution.py`, following the pattern of `attribution.py` and `sentinel_notice.py`.
   - Kind: `DbcaKind = Literal["observation","change","collection"]`.
   - Keys: `DBCA_ATTRIBUTION_KEY="dbca_attribution"` and `DBCA_ATTRIBUTION_ADDED_KEY="dbca_attribution_added_after_the_fact"`.
   - CC BY-NC 4.0 constants: name, SPDX id, URI and legal code URI.
   - DBCA constants: creator, copyright ("none supplied"), dataset, dataset URI and service URI.
   - `DBCA_ATTRIBUTION_TEXT`.
   - Functions: `dbca_attribution(kind)`, which returns a fresh dict and raises ValueError on an unknown kind, and `dbca_attribution_footer(kind)`.
   - Test `tests/test_dbca_attribution.py` proves the block carries every CC BY-NC 4.0 section 3(a)(1) element in a fixed field order: creator, copyright statement, licence with URI and legal code, disclaimer, dataset link and modification. It also proves the content varies by kind, the footer is one sorted-JSON key, a returned block is a fresh copy, an unknown kind raises, and no text holds an em dash or a ShareAlike reference.
2. **Writers.** `src/wetland_change/outputs/geoparquet.py` (`write_observations`) and `src/wetland_change/outputs/changes.py` (`write_changes`) add `**dbca_attribution_footer(...)`, and their docstrings are updated.
   - Tests in `tests/test_geoparquet.py` and `tests/test_change_outputs.py` write a real file and read `dbca_attribution` back from both the schema-level and file-level metadata, comparing it to `dbca_attribution(kind)` and its creator, licence URI and dataset URI. The key-set assertions (test_geoparquet.py:388, test_change_outputs.py:960) gain the key.
3. **Catalogue.** In `src/wetland_change/stac/catalogue.py`:
   - `LICENSE="CC-BY-NC-4.0"`.
   - Collection `extra_fields` gain `dbca_attribution: dbca_attribution("collection")`.
   - A second rel=license link goes to `CC_BY_NC_4_LEGALCODE_URI`, titled `DBCA_LICENCE_LINK_TITLE`.
   - A `rel="via"` link goes to `DBCA_DATASET_URI`, titled `DBCA_DATASET_LINK_TITLE`.
   - Each item's properties gain `dbca_attribution: DBCA_ATTRIBUTION_TEXT`, so items.parquet gains a column.
   - The docstrings are updated.
   - `tests/test_catalogue.py` is updated: licence id, two licence links found by href, the via link, the collection block, the item property, the items.parquet column, the rebuild after an old collection, and that validate_all and stac-check still pass. It also proves the collection JSON contains no "SA-4.0", "SA 4.0" or "ShareAlike".
4. **Backfill command.**
   - New `src/wetland_change/outputs/dbca_backfill.py` provides `add_missing_dbca_attribution(store, *, commit, on, dry_run=False) -> DbcaBackfillResult`. It covers observation and change files only and reuses `observation_paths`, `_change_paths`, `_with_metadata` and `added_footer_value`.
   - New CLI command `add-dbca-attribution` in `src/wetland_change/cli.py`, the same as `add-copernicus-notice`: `--dry-run`, `--now`, and the summary line `scanned N, rewritten|would rewrite M, skipped K, failed F`; it exits 1 on any failure.
   - In `.github/workflows/backfill.yml`, a new `dbca` job ("add DBCA-010 attribution") needs `copernicus`, and `catalogue` now needs `dbca`. The job uses the same pins, permissions, timeouts and summary-only logging. The header comment is updated.
   - Tests:
     - `tests/test_dbca_backfill.py` proves each file gains exactly the two keys and nothing else changes, a file already holding the block is skipped, a second run is a no-op, a dry run writes nothing, a bad file fails alone, a lossy rewrite is refused, only observation and change paths are scanned, and the content types are right. It also proves the four backfills commute on an observation file (24 orders) and three commute on a change file.
     - `tests/test_cli.py` proves the help, rewrite, second-run, dry-run, failure-exit and no-commit behaviour, and the commands appear in the command lists.
     - `tests/test_workflows.py` proves the job order footers, dea, copernicus, dbca, catalogue, the needs chain, and the parametrized pin, permission, timeout, summary and dry-run checks for the dbca job.
5. **fetch_aoi.** `scripts/fetch_aoi.py` prints the DBCA-010 SOURCES row with a `RAMSAR_LICENCE` constant equal to the data/SOURCES.md licence cell.
   - A test in `tests/test_fetch_aoi.py` parses the DBCA-010 row of data/SOURCES.md and proves the printed row matches it in source, url, licence, crs and redistribute_public.
6. **Verification JSON judgement.** A new test in `tests/test_verify.py`, modeled on `test_verify_run_with_injected_dependencies`, proves the written `verification/<run_id>.json`:
   - holds the ramsar-52 id;
   - holds no polygon site name, no `coordinates`, and no `site` or `geometry` key at any depth;
   - holds no `dbca_attribution` key.
   This records the n/a judgement.
7. **Docs and scan.**
   - README sections:
     - Design choices row.
     - Run stages 6 and 8.
     - Data sources and licences: prose, table row, the T3 sentence and the inherit line.
     - Running locally: the code line and bullet.
     - Attribution backfill: intro, the command lines, the bullet, "four rewrite commands" and the build-catalogue bullet.
   - The README must not use the forbidden "public" phrases.
   - AGENTS.md locked decision becomes "(DBCA-010, CC BY-NC 4.0)".
   - The design is amended at the 3 lines.
   - Tests:
     - `tests/test_licence.py` asserts CC BY-NC 4.0 in Data sources and licences, the DBCA README row, and the AGENTS locked decision.
     - `tests/test_readme.py` adds the add-dbca-attribution lines to BACKFILL_LINES, and adds tests that the backfill section and Run stages name CC BY-NC 4.0 and `dbca_attribution`.
     - New `tests/test_dbca_licence_text.py` runs the scan from reading 1 and asserts the design amendment note appears exactly 3 times.
8. **Gate.** Run `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts` and `uv run pytest -q`, each exiting 0. `git diff --numstat` on the design must show 3/3, and `git status --porcelain` on LEARNINGS.md, infra, docs/decisions, docs/research, docs/handoffs, data/SOURCES.md, stories and .agents must be empty.

### Constraints for every agent

- No AWS call, live test, network fetch or output-store read.
- Never run add-* or backfill against s3:// or outputs/.
- No `gh workflow run` and no run logs.
- Never open docs/research/verification-*.md; searches and diffs are restricted to named paths.
- No edits to LEARNINGS.md, infra/, ADRs, docs/research, docs/handoffs, data/SOURCES.md, stories/ or .agents/.
- No commit or push.
- No new "BY-SA" text outside the scan test.
- No em dashes.

## Implementation Notes

- 2026-11-15T08:00:30.978Z: 2026-11-15, from the st-1a9c planner: scripts/fetch_aoi.py:328 prints the DBCA-010 SOURCES.md row as 'CC BY-SA 4.0 (data.gov.au)' with true; it must print the row st-1a9c writes to data/SOURCES.md (CC BY-NC 4.0, non-commercial) for the 'no file states CC BY-SA 4.0' criterion to hold. Verification JSON holds DBCA-derived polygon ids (ramsar-<objectid>, aoi.py:73) but no geometry or site name; st-1a9c judges it n/a, and the 'other file kinds' criterion re-checks it.

## Questions
