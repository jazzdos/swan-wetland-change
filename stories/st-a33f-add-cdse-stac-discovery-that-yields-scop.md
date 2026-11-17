---
id: st-a33f
title: Add CDSE STAC discovery that yields scoped SceneItems
type: feature
epic: st-3d0f
priority: P1
depends_on: [st-3c22]
touches: [src/wetland_change/sources/**, config/cdse-*.toml, tests/test_cdse_search*.py, tests/fixtures/cdse/**, data/SOURCES.md]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Add the CDSE discovery half of the 2022 gap fill: find the CDSE `sentinel-2-l2a` products that ADR 0018's scope rule admits and turn each into the existing `SceneItem` that `process_scene` consumes. Pure metadata work on STAC dicts; no S3 and no pixels. ADR 0018 (`docs/decisions/0018-cdse-baseline-0510-for-the-2022-gap.md`) and the epic hold the measured facts.

New package `src/wetland_change/sources/cdse/` (create `src/wetland_change/sources/__init__.py` and `sources/cdse/__init__.py` empty if absent):

- Settings file `config/cdse-backfill.toml` and a pydantic loader in the package, separate from `config.py` (which must stay byte-identical). Keys: `stac_endpoint` (`https://stac.dataspace.copernicus.eu/v1`), `collection` (`sentinel-2-l2a`), `start` (`2022-01-01T00:00:00Z`), `end` (`2022-11-30T23:59:59Z`), `baseline_prefix` (`05.`), `expected_scale` (0.0001), `expected_offset` (-0.1), `s3_endpoint` (`https://eodata.dataspace.copernicus.eu`), `s3_region` (`default`), `cache_dir` (`scratch/cdse-cache`), `band_assets` (green `B03_10m`, red `B04_10m`, nir `B08_10m`, swir16 `B11_20m`), `scl_asset` (`SCL_20m`), `metadata_asset` (`product_metadata`), `exclude_c1_held` (true). Also commit `config/cdse-overlap.toml`, identical except `start` `2022-12-01T00:00:00Z`, `end` `2023-02-28T23:59:59Z` and `exclude_c1_held` false: the overlap test needs CDSE products for acquisitions c1 already holds, and its staging root never enters the store. AOI, cloud limit (`stac.cloud_cover_max`) and operation EPSG come from `config/pipeline.toml` through the unchanged `load_config`.
- Search: CDSE STAC search over the AOI bbox (as `discover` computes it) and the window given by the caller, clipped to the config's `start`/`end`. Admit an item only if sensed inside the window, `eo:cloud_cover` strictly below `cloud_cover_max`, footprint intersecting the AOI, `processing:version` starting with `baseline_prefix`, and, when `exclude_c1_held` is true, Earth Search `sentinel-2-c1-l2a` (config `stac.endpoint`) holding no item, at any cloud cover, for the same acquisition. Acquisition key: sensing time to the second, relative orbit and tile (CDSE `datetime`, `sat:relative_orbit`, `grid:code`; for c1 the same properties or the parts of `s2:product_uri`). Several CDSE products for one acquisition: keep the newest processing time (the last `_YYYYMMDDTHHMMSS` of the product id). Every refused item comes back with a reason (out of window, cloud, outside AOI, baseline, held by c1, superseded duplicate) so the command can log it.
- Adapter: build a `SceneItem` (`src/wetland_change/catalogue/item.py`) from a CDSE item dict plus a mapping of asset key to local file path. `item_id` the CDSE id, `collection` `sentinel-2-l2a`, `product_uri` the id plus `.SAFE`, `created`/`updated` from the item properties, `tile` in the format `parse_item` produces (`grid:code` without `MGRS-`), `processing_baseline` from `processing:version`, `epsg` from the band assets' `proj:code` (all five must agree; the items carry no item-level code), `cloud_cover`, `geometry_4326`, `bands` keyed green, red, nir, swir16 with `BandSpec` href the local path, `nodata`, `scale` and `offset` from the asset's `nodata`, `raster:scale` and `raster:offset`, resolution from `gsd`, `scl_href` and `product_metadata_href` the local paths, `raw` the item dict. Refuse (raise a named error) when any band's scale or offset differs from `expected_scale`/`expected_offset`, when a needed asset or local path is missing, or when the band EPSGs disagree.
- Fixtures under `tests/fixtures/cdse/`: real CDSE item JSON saved from the public STAC (no credentials needed), at least the two products of acquisition S2B 2022-02-25 R060 T50HMK, one in-scope item, one item dated 2022-12 (out of window) and the c1-held 50JLL acquisition with its Earth Search c1 item. Add a "Committed fixture" row to `data/SOURCES.md` for them.

## Acceptance Criteria

- [ ] `config/cdse-backfill.toml` and `config/cdse-overlap.toml` exist, a test shows the overlap file admits a c1-held fixture that the backfill file refuses, and the loader rejects a file with a missing key or an unknown key (tests).
- [ ] Tests on the fixtures show the scope rule admits the in-scope item and refuses each of: out of window, cloud at or above the limit, baseline not starting `05.`, held by c1, the older duplicate of S2B 2022-02-25 R060 T50HMK, each with its reason.
- [ ] A test builds a `SceneItem` from the in-scope fixture with local paths and asserts `collection == "sentinel-2-l2a"`, bands keyed green, red, nir, swir16, scale 0.0001, offset -0.1, nodata 0 and epsg 32750.
- [ ] Tests show the adapter refuses a fixture edited to scale 0.0002, one with a missing `B11_20m` asset, and one whose band EPSGs disagree.
- [ ] A test marked `live` searches CDSE and Earth Search for 2022-01-01 to 2022-11-30 and asserts every admitted product has `processing:version` starting `05.` and sits inside the window; the worker records the admitted count per tile with `story note`.
- [ ] `git diff --stat $(git merge-base HEAD main) HEAD -- src/wetland_change/catalogue src/wetland_change/config.py src/wetland_change/pipeline.py src/wetland_change/raster src/wetland_change/verify config/pipeline.toml` prints nothing.
- [ ] `data/SOURCES.md` has a row naming `tests/fixtures/cdse/`.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10")

- Leave these byte-identical: `src/wetland_change/catalogue/`, `src/wetland_change/config.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/raster/`, `src/wetland_change/stats.py`, `src/wetland_change/mask.py`, everything under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/` and `scripts/fetch_aoi.py`. st-b6bf's pre-registered rows reuse `discover`, the guards of `process_scene`, `check_band_scaling` and `read_stack`; st-dd0d lists every commit to `verify/`, `pipeline.toml`, `pipeline.yml` or `fetch_aoi.py` until its sample closes. Reuse these by import (private helpers included) instead of editing them.
- Never read or write the shared output store (`s3://<OUTPUT_BUCKET>/`): st-b6bf bars any read of it until its decision files are committed. Never run `run`, `backfill`, `score` or `verify` over a scene sensed on or after 2026-11-12. Never read a pipeline.yml or verify.yml run log, a `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`, or an st-dd0d sample report.
- Staging roots are local: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`, `.../staging/overlap-cdse` and `.../staging/cdse-2022`.
- `data/external/` is untracked and absent from story worktrees. Symlink it from the main checkout (`ln -s /Users/jarrodbaker/Documents/swan-wetland-change/data/external data/external`) before any command or test that loads the AOI; never commit it.
- CDSE eodata S3 keys: 1Password vault `luminosity`, item `swan-wetland`; field `credential` is the access key, field `password` the secret. Load them as `CDSE_S3_ACCESS_KEY=$(op item get swan-wetland --vault luminosity --fields label=credential --reveal)` and `CDSE_S3_SECRET_KEY=$(op item get swan-wetland --vault luminosity --fields label=password --reveal)` with `AWS_PROFILE` and the `AWS_*` key variables unset. Never print, log, commit or store them.
- Run Python that reads downloaded files with `-I`. Docs use flat prose and no em dashes. Every dataset first used gets a `data/SOURCES.md` row in the same commit (AGENTS.md).
- Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
