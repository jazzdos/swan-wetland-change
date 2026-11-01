---
id: st-93a8
title: "Milestone 2: STAC catalogue"
type: epic
priority: P1
depends_on: []
touches: []
exclusive: false
created: 2026-10-29
updated: 2026-11-01
---
## Description

Milestone 2 STAC catalogue: design stage 8 and the "STAC catalogue" row of the verification matrix in `docs/plans/2026-10-29-swan-wetland-change-design.md`. Decision 0003 (`docs/decisions/0003-fixed-schema-ledger.md`): ledger rows keep the full source item JSON so the catalogue rebuilds items from the ledger, and stac-geoparquet is used for the catalogue's `items.parquet` asset.

The public base URL for absolute links is unknown until an AWS bucket exists (open for Jarrod), so it is a config value with a placeholder and tests use a fake URL. Licences: Ramsar-derived outputs CC-BY-SA-4.0, DEA-derived checks CC-BY-4.0 (`data/SOURCES.md`).

## Implementation Plan

## Implementation Notes

- 2026-11-01T05:08:47.781Z: Epic container: both children (st-1990, st-a868) are done and merged to main. Closed with no code of its own. The public base URL stays a config placeholder until the AWS bucket exists, which is tracked under st-f849 (st-ae6e infra) and remains open for Jarrod.

## Questions
