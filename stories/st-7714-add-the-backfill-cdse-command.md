---
id: st-7714
title: Add the backfill-cdse command
type: feature
epic: st-3d0f
priority: P1
complexity: hard
depends_on: [st-a33f, st-f80f]
touches: [src/wetland_change/cli.py, src/wetland_change/sources/**, tests/test_cdse_backfill*.py]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Add the `wetland-change backfill-cdse` command that ties the CDSE search, downloader and adapter (sources/cdse/, from the two producer stories) to the unchanged `process_scene`, writing staged observations, ledger parts and a manifest into a local root. ADR 0018 and the epic hold the context.

Signature: `wetland-change backfill-cdse --start YYYY-MM-DD --end YYYY-MM-DD --output-root DIR [--config config/pipeline.toml] [--cdse-config config/cdse-backfill.toml] [--keep-downloads] [--now ISO]`. Add the command to `src/wetland_change/cli.py` and keep its logic in `src/wetland_change/sources/cdse/backfill.py`.

- Refuse an `--output-root` that has a URL scheme (`s3://` or any other) or is not a local directory path: the staged rows reach the store only through the merge story. Refuse before any network call when either `CDSE_S3_ACCESS_KEY` or `CDSE_S3_SECRET_KEY` is missing, naming both and the 1Password item, never a value.
- Per admitted item, in sensing order: skip it if the staging ledger already holds its (item_id, updated); download; build the `SceneItem`; process it through `_process_one` in `src/wetland_change/pipeline.py` (import it; do not edit pipeline.py) with `run_kind` backfill, a plain `RasterioReader()`, a local `OutputStore`, `wo_lookup=None` (so `dea_wo_agreement` stays null, ADR 0009) and the operation EPSG from config; then delete the product's cache folder unless `--keep-downloads`. Items the search refuses become rejected ledger rows with their reason, as `backfill_once` records rejections.
- An auth error (401 or 403) stops the run at once and still writes the ledger part and manifest for what finished. Guard failures inside `process_scene` (scaling, EPSG, grid) give a failed ledger row as for c1. Exit code 2 when any scene failed, as `backfill` does.
- Write one run manifest (`write_manifest`) and a download manifest `<output-root>/cdse/downloads-<run_id>.json` holding the CDSE config sha256, the code commit, and the per-file records from the downloader (asset key, s3 href, size, checksum, algorithm, verified).
- Observation files land at `observations/year=<Y>/tile=<T>/obs_<item_id>.parquet` with the unchanged schema and footers (provenance, Copernicus notice for the rows' years). The ledger `collection` column reads `sentinel-2-l2a`.

End-to-end test, offline: write synthetic JP2 band and SCL files with rasterio's JP2OpenJPEG driver and a small MTD_MSIL2A.xml with BOA_QUANTIFICATION_VALUE 10000 and BOA_ADD_OFFSET -1000, feed a fake CDSE search result built from the committed `tests/fixtures/cdse/` item (hrefs pointed at the synthetic files through a stub S3 client), and run the command with typer's `CliRunner` into `tmp_path`.

## Acceptance Criteria

- [ ] The end-to-end test runs `backfill-cdse` into `tmp_path` and asserts: one observation file at `observations/year=2022/tile=<T>/obs_<item_id>.parquet`, ledger rows with `collection == "sentinel-2-l2a"` and status succeeded, `dea_wo_agreement` null in every observation row, one run manifest, one `cdse/downloads-<run_id>.json` with `verified` true for every file, and the cache folder deleted.
- [ ] A rerun of the same command into the same root processes nothing new (ledger unchanged, test).
- [ ] With `--keep-downloads` the cache folder remains (test).
- [ ] A synthetic XML with BOA_ADD_OFFSET -2000 gives a failed ledger row from `check_band_scaling` and exit code 2 (test).
- [ ] `--output-root s3://bucket/x` and a missing `CDSE_S3_ACCESS_KEY` each exit non-zero before any search or download call (tests assert the stubs were not called).
- [ ] A stubbed 403 on the second item stops the run and leaves a manifest and ledger part for the first item (test).
- [ ] `uv run wetland-change backfill-cdse --help` lists all options above.
- [ ] `git diff --stat $(git merge-base HEAD main) HEAD -- src/wetland_change/catalogue src/wetland_change/config.py src/wetland_change/pipeline.py src/wetland_change/raster src/wetland_change/verify config/pipeline.toml .github` prints nothing.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10")

- Leave these byte-identical: `src/wetland_change/catalogue/`, `src/wetland_change/config.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/raster/`, `src/wetland_change/stats.py`, `src/wetland_change/mask.py`, everything under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/` and `scripts/fetch_aoi.py`. st-b6bf's pre-registered rows reuse `discover`, the guards of `process_scene`, `check_band_scaling` and `read_stack`; st-dd0d lists every commit to `verify/`, `pipeline.toml`, `pipeline.yml` or `fetch_aoi.py` until its sample closes. Reuse these by import (private helpers included) instead of editing them.
- Never read or write the shared output store (`s3://<OUTPUT_BUCKET>/`): st-b6bf bars any read of it until its decision files are committed. Never run `run`, `backfill`, `score` or `verify` over a scene sensed on or after 2026-11-12. Never read a pipeline.yml or verify.yml run log, a `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`, or an st-dd0d sample report.
- Staging roots are local: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`, `.../staging/overlap-cdse` and `.../staging/cdse-2022`.
- `data/external/` is untracked and absent from story worktrees. Symlink it from the main checkout (`ln -s /Users/jarrodbaker/Documents/swan-wetland-change/data/external data/external`) before any command or test that loads the AOI; never commit it.
- CDSE eodata S3 keys: 1Password vault `luminosity`, item `swan-wetland`; field `credential` is the access key, field `password` the secret. Load them as `CDSE_S3_ACCESS_KEY=$(op item get swan-wetland --vault luminosity --fields label=credential --reveal)` and `CDSE_S3_SECRET_KEY=$(op item get swan-wetland --vault luminosity --fields label=password --reveal)` with `AWS_PROFILE` and the `AWS_*` key variables unset. Never print, log, commit or store them.
- Run Python that reads downloaded files with `-I`. Docs use flat prose and no em dashes. Every dataset first used gets a `data/SOURCES.md` row in the same commit (AGENTS.md).
- Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
