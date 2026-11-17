---
id: st-c062
title: Credit ESA and CDSE in the STAC catalogue for CDSE items
type: feature
epic: st-3d0f
priority: P2
depends_on: [st-a33f]
touches: [src/wetland_change/stac/**, tests/test_catalogue*.py]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Make `wetland-change build-catalogue` credit the right producer and source item for observations made from CDSE products (ledger `collection` `sentinel-2-l2a`, ADR 0018), and change nothing for Collection 1 items. The merge story runs `build-catalogue` over the store once the staged 2022 rows are copied in, so this must land first.

In `src/wetland_change/stac/catalogue.py` (`KEPT_PROPERTIES` near line 85, providers near line 97, `derived_from` near lines 154 to 160):

- For a CDSE-derived item: providers name ESA as producer and processor (baseline 05.10 reprocessing) and the Copernicus Data Space Ecosystem as host, in place of the Element 84 Earth Search entry; the `derived_from` link points to the CDSE STAC item, `https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a/items/<item_id>` (the `self` link of the ledger's `source_item` JSON); `processing:version` or the equivalent kept property carries the CDSE baseline.
- Collection 1 items keep their current output exactly.
- Use the CDSE item fixture committed under `tests/fixtures/cdse/` by the discovery story for the ledger's `source_item`.

## Acceptance Criteria

- [ ] A test builds the catalogue from a ledger holding one c1 row and one CDSE row and asserts the CDSE item's `derived_from` href equals the CDSE `self` href and its providers include ESA and the Copernicus Data Space Ecosystem and exclude Element 84.
- [ ] The same test asserts the c1 item's JSON equals the JSON produced from a c1-only ledger.
- [ ] Every existing test in `tests/` that covers the catalogue passes unchanged (`git diff $(git merge-base HEAD main) HEAD -- tests` shows only added lines in catalogue test files).
- [ ] The built catalogue validates with pystac (`validate_all`) in the test.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10")

- Leave these byte-identical: `src/wetland_change/catalogue/`, `src/wetland_change/config.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/raster/`, `src/wetland_change/stats.py`, `src/wetland_change/mask.py`, everything under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/` and `scripts/fetch_aoi.py`. st-b6bf's pre-registered rows reuse `discover`, the guards of `process_scene`, `check_band_scaling` and `read_stack`; st-dd0d lists every commit to `verify/`, `pipeline.toml`, `pipeline.yml` or `fetch_aoi.py` until its sample closes. Reuse these by import (private helpers included) instead of editing them.
- Never read or write the shared output store (`s3://<OUTPUT_BUCKET>/`): st-b6bf bars any read of it until its decision files are committed. Never run `run`, `backfill`, `score` or `verify` over a scene sensed on or after 2026-11-12. Never read a pipeline.yml or verify.yml run log, a `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`, or an st-dd0d sample report.
- Staging roots are local: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`, `.../staging/overlap-cdse` and `.../staging/cdse-2022`.
- `data/external/` is untracked and absent from story worktrees. Symlink it from the main checkout (`ln -s /Users/jarrodbaker/Documents/swan-wetland-change/data/external data/external`) before any command or test that loads the AOI; never commit it.
- CDSE eodata S3 keys: 1Password vault `luminosity`, item `swan-wetland`; field `credential` is the access key, field `password` the secret. Load them as `CDSE_S3_ACCESS_KEY=$(op item get swan-wetland --vault luminosity --fields label=credential --reveal)` and `CDSE_S3_SECRET_KEY=$(op item get swan-wetland --vault luminosity --fields label=password --reveal)` with `AWS_PROFILE` and the `AWS_*` key variables unset. Never print, log, commit or store them.
- Run Python that reads downloaded files with `-I`. Docs use flat prose and no em dashes. Every dataset first used gets a `data/SOURCES.md` row in the same commit (AGENTS.md).
- Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
