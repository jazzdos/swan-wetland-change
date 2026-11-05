---
id: st-b101
title: Bound per-run S3 requests as history grows
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [src/wetland_change/ledger.py, src/wetland_change/pipeline.py, src/wetland_change/stac/catalogue.py, .github/workflows/pipeline.yml]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

read_ledger makes a HEAD and a GET per ledger part (src/wetland_change/ledger.py:186) and a backfill-seeded bucket holds about 1172 parts. A daily run reads the ledger three or more times, GETs every observation in scoring and rewrites every catalogue object, about 30k sequential requests on a processed day and growing. Verdict PLAUSIBLE: counts were measured on a fake S3 and runner-to-bucket latency is unknown. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 7.

## Acceptance Criteria

- [ ] A daily run reads the ledger once and passes the table to scoring and catalogue building
- [ ] Ledger parts are compacted so read_ledger needs a bounded number of requests
- [ ] The pipeline workflow builds the catalogue once per run
- [ ] The catalogue writes only items added or changed since the previous run

## Implementation Plan

## Implementation Notes

## Questions
