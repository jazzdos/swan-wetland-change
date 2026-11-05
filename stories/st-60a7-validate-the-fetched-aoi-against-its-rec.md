---
id: st-60a7
title: Validate the fetched AOI against its recorded source
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [scripts/fetch_aoi.py, src/wetland_change/aoi.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

fetch_aoi calls only raise_for_status (scripts/fetch_aoi.py:84-89), so an HTTP 200 error body is written as the AOI file. If SLIP renumbers objectids the ramsar-15, ramsar-28 and ramsar-56 overrides silently attach to other polygons. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md L3.

## Acceptance Criteria

- [ ] fetch_aoi fails when the response is not a GeoJSON feature collection
- [ ] fetch_aoi fails or warns when the polygon ids used by water overrides are missing or renamed

## Implementation Plan

## Implementation Notes

## Questions
