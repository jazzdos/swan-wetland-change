---
id: st-fb21
title: Reject a STAC item with a null updated instead of crashing discovery
type: bug
priority: P2
depends_on: []
discovered_from: st-1b50
touches: [src/wetland_change/catalogue/item.py, src/wetland_change/catalogue/search.py, tests/test_search.py]
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

## Implementation Notes

## Questions
