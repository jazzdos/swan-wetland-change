---
id: st-fb21
title: Reject a STAC item with a null updated instead of crashing discovery
type: bug
priority: P2
depends_on: []
discovered_from: st-1b50
touches: [src/wetland_change/catalogue/item.py, tests/test_search.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

discover() in src/wetland_change/catalogue/search.py catches (ItemGuardError, KeyError, TypeError, ValueError) around parse_item. parse_item (src/wetland_change/catalogue/item.py:111-112) calls parse_timestamp(props['created']) and parse_timestamp(props['updated']), and parse_timestamp does value.replace(...), so a null created or updated raises AttributeError, which is not caught. One malformed item from Earth Search then aborts the whole discovery instead of being logged as a rejection. Preexisting on main; found while building st-1b50 and out of its scope.

## Acceptance Criteria

- [ ] An item with properties.updated set to null is recorded in Discovery.rejected with a reason
- [ ] and discover() returns the other scenes
- [ ] An item with properties.created set to null is recorded in Discovery.rejected with a reason
- [ ] A test in tests/test_search.py covers both cases

## Implementation Plan

Verified against the worktree (HEAD 019ef9a): the story's pointers are accurate. `parse_item` (src/wetland_change/catalogue/item.py, around lines 110-112) calls `parse_timestamp(props["datetime"|"created"|"updated"])`; `parse_timestamp` does `value.replace(...)`, so a JSON null raises AttributeError, which `discover()` (src/wetland_change/catalogue/search.py, the `except (ItemGuardError, KeyError, TypeError, ValueError)` near line 228) does not catch. `ItemGuardError` subclasses `ValueError` and is already treated as a rejection. `_updated_or_none` (search.py:150) already returns None for a null updated, so the ledger gets `rejected_updated[id] = None` with no change needed. In discover's pre-filter, a null `updated` is skipped by `if updated_raw and ...` and a null `created` is not read there, so both reach `parse_item`.

Approach: fix at the source. Do not widen the except clause.

1. RED: in tests/test_search.py add a parametrized test `test_discover_rejects_a_null_timestamp_without_aborting` over `field in ("created", "updated")`. Build `good = fixture_item`, `bad = _variant(good, "nulltime", **{field: None})`, run `discover(FakeClient([bad, good]), CFG, bbox=BBOX, polygons_4326=[THOMSONS_4326], created_from=None, seen=set())`. Assert: scenes are exactly `[good["id"]]`; `result.rejected` has exactly one entry with id `bad["id"]`; the reason contains the field name (`f"properties.{field}"`) and `ItemGuardError`; for `updated` null `result.rejected_updated == {bad["id"]: None}`, for `created` null `result.rejected_updated[bad["id"]]` equals `parse_timestamp(bad["properties"]["updated"])`. Run `uv run pytest -q tests/test_search.py -k null_timestamp`; both params must fail with AttributeError (crash, not an assertion on content). This proves the bug and that the test reaches it.
2. GREEN: in src/wetland_change/catalogue/item.py add a private helper `_timestamp(props, key, item_id) -> dt.datetime` that reads `props[key]` (a missing key still raises KeyError, preserving existing behaviour and test), and if the value is not a `str` raises `ItemGuardError(f"{item_id}: properties.{key} is {value!r}, expected an RFC 3339 string")`, else returns `parse_timestamp(value)`. In `parse_item` use it for `datetime`, `created` and `updated`. Leave `parse_timestamp` unchanged.
3. Re-run the new tests (green), then the four gates plus `GITHUB_ACTIONS=true uv run pytest -q`. Confirm existing tests still pass, especially test_discover_rejects_malformed_item_without_aborting (KeyError) and the rejected-ledger tests.
4. Do not commit; do not edit stories/** or .agents/shousper-stories/local/**; no live tests.

What the tests prove: a null created or null updated item lands in Discovery.rejected with a reason naming the field, the good scene is still returned (discovery is not aborted), and the ledger keys (rejected_updated) stay consistent with st-1b50 (None for null updated, so never deduplicated as unchanged).

## Implementation Notes

- 2026-11-06T01:58:07.524Z: Built via build-flow run wf_8afca830-caf. parse_item uses a _timestamp helper that raises ItemGuardError naming properties.<key> for a non-string datetime, created or updated; discover's except clause is unchanged. Parametrized test in tests/test_search.py covers null created and null updated (rejected with reason, good scene returned, rejected_updated None for null updated). Gates all exit 0; 786 passed, 9 deselected.

## Questions
