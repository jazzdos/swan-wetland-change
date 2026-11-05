---
id: st-4fa1
title: Add bucket lifecycle and object content types
type: chore
epic: st-f849
priority: P3
depends_on: []
touches: [infra/main.tf, src/wetland_change/store.py, tests/test_infra.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

The bucket has no lifecycle rule to abort incomplete multipart uploads, every object is uploaded as application/octet-stream including the STAC JSON, and directory markers are PUT again on every write (src/wetland_change/store.py:29-31). Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md L6.

## Acceptance Criteria

- [ ] infra adds a lifecycle rule that aborts incomplete multipart uploads after one day
- [ ] JSON and parquet objects are written with their media types

## Implementation Plan

## Implementation Notes

## Questions
