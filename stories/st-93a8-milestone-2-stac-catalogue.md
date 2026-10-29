---
id: st-93a8
title: "Milestone 2: STAC catalogue"
type: epic
priority: P1
depends_on: []
touches: []
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Milestone 2 STAC catalogue: design stage 8 and the "STAC catalogue" row of the verification matrix in `docs/plans/2026-10-29-swan-wetland-change-design.md`. Decision 0003 (`docs/decisions/0003-fixed-schema-ledger.md`): ledger rows keep the full source item JSON so the catalogue rebuilds items from the ledger, and stac-geoparquet is used for the catalogue's `items.parquet` asset.

The public base URL for absolute links is unknown until an AWS bucket exists (open for Jarrod), so it is a config value with a placeholder and tests use a fake URL. Licences: Ramsar-derived outputs CC-BY-SA-4.0, DEA-derived checks CC-BY-4.0 (`data/SOURCES.md`).

## Implementation Plan

## Implementation Notes

## Questions
