---
id: st-1990
title: Build and validate the STAC catalogue from the ledger
type: feature
epic: st-93a8
priority: P1
depends_on: []
touches: [src/wetland_change/stac/**, src/wetland_change/config.py, config/**, tests/test_catalogue.py, pyproject.toml, uv.lock]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

New package `src/wetland_change/stac/` with `catalogue.py` (design stage 8): a pystac Catalog, one Collection, and one Item per processed source scene, rebuilt from the ledger's stored item JSON (decision 0003; `src/wetland_change/ledger.py`), never re-fetched. Each item gets an `observations` asset for its observation file. Change-file and verification assets come in the follow-up story.

- Links and hrefs are absolute https: `[catalogue] base_url` in config plus the store-relative path. Use a placeholder base URL such as `https://example.invalid/swan-wetland-change` until the bucket exists, and a fake one in tests.
- Collection licence CC-BY-SA-4.0. Providers: Element 84 (Earth Search), ESA, DBCA and Geoscience Australia (DEA references).
- Write the JSON into the store under `stac/` through `OutputStore` (`src/wetland_change/store.py`).
- Validate with pystac `validate_all` and stac-check 1.14; add dev dependencies as needed.

## Acceptance Criteria

- [ ] Offline test: building from a ledger with N processed items writes `stac/catalog.json`, one collection and N item JSONs, each item with an `observations` asset whose href is base_url plus the observation file's store path.
- [ ] Offline test: pystac `validate_all` passes on the written catalogue.
- [ ] Offline test: stac-check reports no errors on the collection or on one item.
- [ ] Offline test: every link and asset href in the written catalogue is an absolute https URL.
- [ ] The collection's `license` is CC-BY-SA-4.0 and its providers name the four organisations above.
- [ ] Offline test: rebuilding from an unchanged ledger writes byte-identical catalogue files.

## Implementation Plan

## Implementation Notes

## Questions
