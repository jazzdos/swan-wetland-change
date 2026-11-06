---
id: st-c667
title: Stop S3 deletes from re-creating directory markers
type: bug
priority: P2
depends_on: []
discovered_from: st-2cc2
touches: [src/wetland_change/store.py, tests/test_store.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

OutputStore.delete (src/wetland_change/store.py) calls pyarrow's S3FileSystem.delete_file. The st-2cc2 planner probed pyarrow 26.0.0 against the stub S3 server in tests/test_store.py: delete_file sends DELETE <key> and then PUT <parent>/ with Content-Type application/x-directory, so every delete re-creates the parent directory marker that st-2cc2 removes from writes. Callers are ledger compaction (src/wetland_change/ledger.py:291,295) and pipeline.py:320. No S3FileSystem option stops it. Out of scope in st-2cc2, whose criteria cover writes only. Candidate fixes: delete through fs.delete_files if it skips the parent marker (to be checked against the stub), or a direct S3 DeleteObject call; the fix must not call AWS in tests.

## Acceptance Criteria

- [ ] Deleting a key from an S3 root sends no request that creates a key ending in a slash
- [ ] checked against the stub S3 server on 127.0.0.1
- [ ] OutputStore.delete still returns whether the key existed
- [ ] and deleting from a local root still works

## Implementation Plan

## Implementation Notes

## Questions
