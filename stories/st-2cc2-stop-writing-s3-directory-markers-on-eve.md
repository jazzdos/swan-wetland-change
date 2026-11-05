---
id: st-2cc2
title: Stop writing S3 directory markers on every write
type: bug
priority: P2
depends_on: [st-4fa1]
discovered_from: st-4fa1
touches: [src/wetland_change/store.py, tests/test_store.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

OutputStore.write_bytes calls create_dir on the parent of every key (src/wetland_change/store.py:29), which review finding L6 confirmed puts directory marker objects again on each write. S3 has no directories, so these are extra requests and extra objects in a public bucket. The description of st-4fa1 names this but its acceptance criteria do not, so it is out of scope there. Evidence: docs/research/2026-11-04-milestone-2-review.md L6.

## Acceptance Criteria

- [ ] Writing to an S3 root sends no request that creates a key ending in a slash
- [ ] checked against a stub S3 server on 127.0.0.1
- [ ] Writing to a local root still creates missing parent directories

## Implementation Plan

## Implementation Notes

## Questions
