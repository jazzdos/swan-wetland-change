---
id: st-22f1
title: Add the DBCA-010 CC BY-NC 4.0 attribution and licence to the published files
type: feature
priority: P2
complexity: hard
depends_on: []
discovered_from: st-1a9c
touches: [src/wetland_change/**, .github/workflows/backfill.yml, tests/**, README.md, AGENTS.md, scripts/fetch_aoi.py]
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

## Implementation Notes

- 2026-11-15T08:00:30.978Z: 2026-11-15, from the st-1a9c planner: scripts/fetch_aoi.py:328 prints the DBCA-010 SOURCES.md row as 'CC BY-SA 4.0 (data.gov.au)' with true; it must print the row st-1a9c writes to data/SOURCES.md (CC BY-NC 4.0, non-commercial) for the 'no file states CC BY-SA 4.0' criterion to hold. Verification JSON holds DBCA-derived polygon ids (ramsar-<objectid>, aoi.py:73) but no geometry or site name; st-1a9c judges it n/a, and the 'other file kinds' criterion re-checks it.

## Questions
