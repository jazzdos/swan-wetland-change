---
id: st-1990
title: Build and validate the STAC catalogue from the ledger
type: feature
epic: st-93a8
priority: P1
depends_on: []
touches: [config/pipeline.toml, pyproject.toml, src/wetland_change/config.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, tests/test_catalogue.py, tests/test_config.py, uv.lock]
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

## Findings from exploring the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-1990)

All story pointers are real and no prerequisite is missing. `src/wetland_change/stac/` does not exist yet. Do not confuse it with the existing `src/wetland_change/catalogue/`, which is Earth Search search/guard code and stays untouched.

- `ledger.py` has `read_ledger(store) -> pa.Table` (`LEDGER_SCHEMA`), `entry_for`, `write_ledger`, and the `source_item` JSON string column. `observation_path` is a store-relative path (`observations/year=Y/tile=T/obs_<id>.parquet`, from `outputs/geoparquet.py::observation_path`) and is None when no rows were written. `_latest()` is private. Do not edit ledger.py (not in the story's touches); the new module does its own latest-per-item selection.
- `store.py::OutputStore` has `write_bytes`, `read_bytes`, `list_files`, `exists`.
- `config.py`: `PipelineConfig(stac, aoi, water, output)`. `tests/test_pipeline.py` builds `PipelineConfig(...)` directly, so a new `catalogue` field must have a default or that test breaks.
- `pyproject.toml` dev group has no stac-check or jsonschema. `uv sync` gives pystac 1.15.2 (STAC 1.1.0), stac-geoparquet 0.8.3. `stac-check==1.14.0` exists on PyPI.

Prototype results, which drive the design:
1. A catalogue written with absolute https hrefs cannot be re-read by pystac from disk, because the root/child links point at the not-yet-existing public URL. `validate_all` on a re-read catalogue therefore needs a StacIO that maps `<base_url>/...` to `OutputStore.read_bytes`. Confirmed working with a `DefaultStacIO` subclass installed through `pystac.StacIO.set_default(...)`.
2. `validate_all` also needs `jsonschema`, via `pystac[validation]`. pystac bundles the core 1.1.0 item/catalog/collection schemas, so validation is offline as long as items declare no `stac_extensions`. Declared extensions would be fetched from stac-extensions.github.io, so rebuilt items carry a curated property subset and declare none.
3. stac-check 1.14 (stac-validator 4.2.2) fetches core schemas from schemas.stacspec.org over the network. It works offline when `stac_validator.utilities.fetch_and_parse_file` is monkeypatched. The patch serves `https://` schema URLs from `pystac.validation.local_validator.get_local_schema_cache()` (a dict keyed by those exact URLs) and delegates local paths to the real function. Verified with HTTPS_PROXY pointed at a dead port: catalog, collection and item all report `valid_stac=True`. Call `stac_validator.utilities.fetch_and_parse_schema.cache_clear()` before and after patching.
4. The source Earth Search item carries `s3://` links (canonical, via) and many non-catalogue assets. Rebuilt items therefore keep only geometry, bbox, curated properties, one `observations` asset, and an https `derived_from` link to the item's Earth Search self URL, so every href stays absolute https.

## Steps

1. Dependencies and config (batch 1)
   - `pyproject.toml` dev group: add `stac-check==1.14.0` and `pystac[validation]>=1.15`, using `uv add --dev` so `uv.lock` updates.
   - `src/wetland_change/config.py`: add `CatalogueConfig(base_url: str)`. It requires an `https://` prefix and strips a trailing slash. Add `PipelineConfig.catalogue` with a default factory using the placeholder `https://example.invalid/swan-wetland-change`.
   - `config/pipeline.toml`: add `[catalogue] base_url = "https://example.invalid/swan-wetland-change"`.
   - `tests/test_config.py`: add tests that the shipped config loads with the https placeholder, that a non-https value is rejected, that the trailing slash is stripped, and that omitting the section yields the default.

2. Catalogue builder (batch 2)
   - `src/wetland_change/stac/__init__.py` exports `build_catalogue`, `write_catalogue`, `build_and_write`, `StoreStacIO`.
   - `src/wetland_change/stac/io.py`: `StoreStacIO(DefaultStacIO)` that rewrites reads of `<base_url>/stac/...` to `store.read_bytes` and also reads a `file://` or plain path normally. It is reused by the follow-up story.
   - `src/wetland_change/stac/catalogue.py`:
     - `processed_entries(ledger)`: latest row per item (sort by `processed_at`, `run_id`, take the last per `item_id`), keep `status == "succeeded"` with non-null `source_item`, sort by `item_id`. Failed and rejected rows never appear.
     - `build_catalogue(ledger, *, base_url) -> pystac.Catalog`:
       - Catalog id `swan-wetland-change-catalog`, `CatalogType.ABSOLUTE_PUBLISHED`, one Collection `swan-wetland-change` with license `CC-BY-SA-4.0`.
       - Providers named exactly "Element 84 (Earth Search)", "European Space Agency (ESA)", "Department of Biodiversity, Conservation and Attractions (DBCA)" and "Geoscience Australia (DEA)", each with an https url and valid roles.
       - Extent: spatial union of item bboxes and temporal min/max of item datetimes. With no items, use a fixed Swan Coastal Plain bbox and open temporal interval.
       - One Item per entry, from `json.loads(source_item)`: id, geometry, bbox, `datetime` parsed with `catalogue.item.parse_timestamp`, and properties limited to created, updated, platform, constellation, instruments, eo:cloud_cover, grid:code, s2:product_uri, s2:processing_baseline, proj:epsg (only keys present).
       - No `stac_extensions`. Add a `derived_from` link taken from the raw item's https `self` link, if present.
       - If `observation_path` is set, add asset `observations` with href `f"{base_url}/{observation_path}"`, media type `application/vnd.apache.parquet`, roles `["data"]`.
       - Call `catalog.normalize_hrefs(f"{base_url}/stac")` so every self/root/parent/child/item link is absolute https.
     - `validate_catalogue(catalog)`: runs `catalog.validate_all()` in memory and raises on failure.
     - `write_catalogue(catalog, store, *, base_url) -> list[str]`: for each object (catalog, collection, items) serialise `json.dumps(obj.to_dict(include_self_link=True, transform_hrefs=False), indent=2, sort_keys=True) + "\n"`. The store path is the self href with `f"{base_url}/"` stripped, so `stac/catalog.json`, `stac/swan-wetland-change/collection.json` and `stac/swan-wetland-change/<id>/<id>.json`. Write via `store.write_bytes` and return the sorted relpaths.
     - `build_and_write(store, *, base_url)`: `read_ledger`, build, validate, write.
     - No timestamps from `now()` anywhere, so output is deterministic.

3. Tests in `tests/test_catalogue.py` (all offline, base URL `https://catalogue.test.invalid/wetlands`)
   - Fixture builds N=3 succeeded ledger entries from `fixture_item` copies with distinct ids (via `parse_item` and `entry_for`, observation_path from `observation_path(year, tile, id)`), plus one failed and one rejected entry, plus one item that failed first and succeeded in a later run. Written through `write_ledger`.
   - `test_writes_catalog_collection_and_items`: `store.list_files("stac")` is exactly catalog.json, one collection.json and N item JSONs. Failed and rejected items are absent, and the superseded item appears once.
   - `test_observations_asset_href`: each item has `assets["observations"].href == base_url + "/" + observation_path`.
   - `test_validate_all_on_written_catalogue`: an autouse-style fixture installs `StoreStacIO` as the pystac default (restored after). It loads `<base>/stac/catalog.json` and `pystac.validation.validate_all` passes.
   - `test_stac_check_offline`: monkeypatch `stac_validator.utilities.fetch_and_parse_file` as described in finding 3, then run `stac_check.lint.Linter(path)` on a temp copy of the collection JSON and of one item JSON (path-based). Assert `valid_stac is True` and no `error_message`. A sub-test or comment shows the patch is what keeps it offline.
   - `test_all_hrefs_absolute_https`: walk every written JSON and assert each link href and each asset href parses with scheme `https` and a netloc.
   - `test_collection_license_and_providers`: license is `CC-BY-SA-4.0` and provider names contain Element 84, ESA, DBCA and Geoscience Australia.
   - `test_rebuild_is_byte_identical`: build and write twice (same store, and into a second store); every file's bytes are equal.
   - `test_empty_ledger_still_valid`: an empty ledger writes a catalogue and collection with no items and validates.

4. Verify (from AGENTS.md): `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.

## Implementation Notes

- 2026-10-29T19:32:49.724Z: touches-expansion: overlaps st-8228 (.gitignore, LEARNINGS.md, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_change.py, tests/test_cli.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py) — coordinate or split
- 2026-10-29T19:32:49.726Z: touches-expansion: overlaps st-ae6e (.gitignore, LEARNINGS.md, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_change.py, tests/test_cli.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py) — coordinate or split
- 2026-10-29T19:32:49.728Z: touches-expansion: overlaps st-afcf (.gitignore, LEARNINGS.md, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_change.py, tests/test_cli.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py) — coordinate or split
- 2026-10-29T19:32:49.729Z: touches-expansion: overlaps st-d4a8 (.gitignore, LEARNINGS.md, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_change.py, tests/test_cli.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py) — coordinate or split
- 2026-10-29T19:32:49.731Z: touches-expansion: overlaps st-f4d3 (.gitignore, LEARNINGS.md, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_change.py, tests/test_cli.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py) — coordinate or split

## Questions
