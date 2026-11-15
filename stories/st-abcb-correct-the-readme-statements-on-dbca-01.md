---
id: st-abcb
title: Correct the README statements on DBCA-010 attribution scope and the backfill gate
type: bug
priority: P2
depends_on: []
discovered_from: st-22f1
touches: [README.md]
exclusive: false
created: 2026-11-15
updated: 2026-11-15
---

## Description

The st-22f1 build review approved the change with minor findings that were not fixed, checked against main at cbe0510. (1) README.md:498-499 says the attribution backfill runs before ADR 0011 step 3; ADR 0011 is superseded by ADR 0016 and the backfill is precondition 2 of ADR 0016 'Preconditions of the apply'. (2) README.md:361 and :556 say the catalogue holds no DBCA-010 material, while :182 lists catalogue files as DBCA-derived CC BY-NC 4.0 outputs and the collection carries dbca_attribution; the intended statement is that add-dbca-attribution does not scan the catalogue because build-catalogue writes the attribution. (3) README.md:201-204 says the published files carry the DBCA-010 attribution, but the ledger, run manifests, verification JSON, STAC catalog and write index carry none. (4) README.md:186 is a 105-character line; :182-188 should be rewrapped. (5) tests/test_dbca_licence_text.py NEEDLE r'by[-_]sa' misses 'Attribution-ShareAlike', 'BY SA' and non-ASCII hyphens. Out of scope for st-22f1 because it was merged before the findings were triaged.

## Acceptance Criteria

- [ ] README names ADR 0016 'Preconditions of the apply' step 2 as the gate of the attribution backfill and no longer cites ADR 0011 step 3 there
- [ ] README states which published file kinds carry the DBCA-010 attribution (observation and change files
- [ ] the STAC collection and items) and which do not
- [ ] with no contradiction between Data sources and licences
- [ ] Running locally and Attribution backfill
- [ ] and a test pins it
- [ ] The licence-text scan matches ShareAlike
- [ ] BY SA and non-ASCII hyphen variants
- [ ] with any new allowlist entries asserted present
- [ ] and still passes
- [ ] uv run ruff check src tests scripts
- [ ] uv run ruff format --check src tests scripts
- [ ] uv run mypy src scripts and uv run pytest -q all exit 0

## Implementation Plan

## Implementation Notes

## Questions
