---
id: st-f80f
title: Add the CDSE eodata downloader with checksum verification
type: feature
epic: st-3d0f
priority: P1
depends_on: [st-3c22]
touches: [src/wetland_change/sources/**, tests/test_cdse_download*.py, data/SOURCES.md]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Add the downloader for the CDSE 2022 gap fill: fetch the five band files and the product XML of one CDSE product from eodata S3 into a local cache and prove each file is the one the STAC item describes. Windowed `/vsis3/` JP2 reads took about 29 s per window, against about 31 s to download a whole scene (412 MB), so the backfill downloads and reads local files (ADR 0018, epic).

Module `src/wetland_change/sources/cdse/download.py` (create empty `src/wetland_change/sources/__init__.py` and `sources/cdse/__init__.py` if absent):

- Client: botocore (already a dependency; boto3 is not installed and is not to be added), endpoint `https://eodata.dataspace.copernicus.eu`, region `default`, path-style addressing, keys from `CDSE_S3_ACCESS_KEY` and `CDSE_S3_SECRET_KEY`. Missing either variable: raise an error that names both variables and the 1Password item (`luminosity` / `swan-wetland`) and never a value. Endpoint, region and cache directory are arguments; the `backfill-cdse` story wires them from `config/cdse-backfill.toml`.
- Download: given a CDSE item dict and asset keys (default `B03_10m`, `B04_10m`, `B08_10m`, `B11_20m`, `SCL_20m`, `product_metadata`), split each `s3://eodata/<key>` href into bucket and key, stream to `<cache_dir>/<item id>/<file name>` through a temporary name and rename on success. Skip a file already in the cache only when it verifies.
- Verification per file: size equals the asset's `file:size`; `file:checksum` is a multihash (varint code, varint length, digest). Code 0x16 is sha3-256 and must match; the band and SCL assets measured so far all use it. The `product_metadata` asset carries code 0xd5 with a 32-byte digest: during the live test, find which of md5, sha256, sha3-256 or blake2b-256 reproduces it and implement that one; if none does, verify size only for that code and say so in the result. A mismatch deletes the file and raises.
- Errors: HTTP 401 or 403 raise a distinct error so the command can stop the whole run; 5xx and dropped connections retry up to three times (reuse `retry_transient` from `src/wetland_change/raster/retry.py` by import if its signature fits).
- Result: a record per file (asset key, s3 href, local path, size, checksum, algorithm, verified true or false) that the command writes into its download manifest.
- `data/SOURCES.md`: add the row for CDSE eodata S3 product downloads (url `s3://eodata/Sentinel-2/MSI/L2A_N0500/` via `https://eodata.dataspace.copernicus.eu`, licence Copernicus Sentinel data terms (free, open), fetched "per backfill-cdse run, first used <date>", sha256 "per file: the item's `file:checksum` (sha3-256), verified at download and listed in the run's download manifest", crs EPSG:32750, redistribute_public true). This commit is the first that downloads from eodata.

## Acceptance Criteria

- [ ] Tests with a stub botocore client (no network) cover: a verified download, a size mismatch and a checksum mismatch (each deletes the file and raises), a cached file that verifies and is not fetched again, a 403 raising the distinct auth error, and a 503 retried then succeeding.
- [ ] A test shows a missing `CDSE_S3_SECRET_KEY` raises an error whose message names both variables and contains neither the access key nor any value of the environment.
- [ ] A test decodes a 0x16 multihash and rejects a digest of the wrong length.
- [ ] A test marked `live` downloads the `SCL_20m` asset (about 1.5 MB) and the `product_metadata` asset of product S2A_MSIL2A_20221227T021341_N0510_R060_T50JML_20240807T115431 into a temporary cache and asserts both verify; the worker records the `product_metadata` checksum algorithm with `story note`.
- [ ] With the keys loaded as in the shared constraints, `git log -p $(git merge-base HEAD main)..HEAD | grep -cF "$CDSE_S3_ACCESS_KEY"` and the same for `$CDSE_S3_SECRET_KEY` each print 0.
- [ ] `data/SOURCES.md` has the CDSE eodata row.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10")

- Leave these byte-identical: `src/wetland_change/catalogue/`, `src/wetland_change/config.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/raster/`, `src/wetland_change/stats.py`, `src/wetland_change/mask.py`, everything under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/` and `scripts/fetch_aoi.py`. st-b6bf's pre-registered rows reuse `discover`, the guards of `process_scene`, `check_band_scaling` and `read_stack`; st-dd0d lists every commit to `verify/`, `pipeline.toml`, `pipeline.yml` or `fetch_aoi.py` until its sample closes. Reuse these by import (private helpers included) instead of editing them.
- Never read or write the shared output store (`s3://<OUTPUT_BUCKET>/`): st-b6bf bars any read of it until its decision files are committed. Never run `run`, `backfill`, `score` or `verify` over a scene sensed on or after 2026-11-12. Never read a pipeline.yml or verify.yml run log, a `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`, or an st-dd0d sample report.
- Staging roots are local: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`, `.../staging/overlap-cdse` and `.../staging/cdse-2022`.
- `data/external/` is untracked and absent from story worktrees. Symlink it from the main checkout (`ln -s /Users/jarrodbaker/Documents/swan-wetland-change/data/external data/external`) before any command or test that loads the AOI; never commit it.
- CDSE eodata S3 keys: 1Password vault `luminosity`, item `swan-wetland`; field `credential` is the access key, field `password` the secret. Load them as `CDSE_S3_ACCESS_KEY=$(op item get swan-wetland --vault luminosity --fields label=credential --reveal)` and `CDSE_S3_SECRET_KEY=$(op item get swan-wetland --vault luminosity --fields label=password --reveal)` with `AWS_PROFILE` and the `AWS_*` key variables unset. Never print, log, commit or store them.
- Run Python that reads downloaded files with `-I`. Docs use flat prose and no em dashes. Every dataset first used gets a `data/SOURCES.md` row in the same commit (AGENTS.md).
- Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
