---
id: st-ef8c
title: Add the 2022 gap-row check script
type: feature
epic: st-3d0f
priority: P2
depends_on: [st-a33f]
touches: [docs/research/**, tests/test_cdse_gap_checks*.py]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Write the script for the reported (not decision) checks on the staged 2022-01 to 2022-11 CDSE rows against two independent references, using the existing verify functions unchanged. ADR 0018 lists these checks as reported only.

Script `docs/research/<today>-cdse-gap-checks.py`, argparse options `--staging-root`, `--out-csv`, `--out-json`:

- DEA Waterbodies: for each staged observation row on a DEA Waterbodies polygon, the per-pass comparison of the row's wet share with the DEA Waterbodies wet percentage from the lake's CSV time series (`fetch_series` and `parse_timeseries` in `src/wetland_change/verify/waterbodies.py`), nearest DEA date within 3 days, tolerance 10 pp. Use the per-pass check verify already has if one fits; otherwise call its helpers and keep the tolerance and window as constants named after those in verify.
- NDVI: for each staged scene, the DEA NBART comparison through `find_nbart_item`, `dea_ndvi_median` and `ndvi_median_check` in `src/wetland_change/verify/ndvi.py`, as `ndvi_scene_check` runs it.
- Outputs: a CSV per comparison (scene, polygon, both values, difference, within tolerance or not, skip reason) and a JSON of counts per lake and per tile, with skips by reason.

Tests `tests/test_cdse_gap_checks.py`, loading the script by path, on a tiny staging root in `tmp_path` with the saved Waterbodies excerpt in `tests/fixtures/waterbodies/` and stubbed DEA calls (no network).

## Acceptance Criteria

- [ ] `ls docs/research/*-cdse-gap-checks.py` lists one script and `uv run python -I <script> --help` exits 0.
- [ ] Tests show a pass 2 days from a DEA observation is compared and one 4 days away is skipped with reason, and that differences of 10.0 pp and 10.1 pp fall inside and outside the tolerance.
- [ ] Tests show the NDVI path calls the verify functions (patched stubs record the calls) and records a skip when no NBART item is found.
- [ ] `git diff --stat $(git merge-base HEAD main) HEAD -- src/wetland_change/verify` prints nothing.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10")

- Leave these byte-identical: `src/wetland_change/catalogue/`, `src/wetland_change/config.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/raster/`, `src/wetland_change/stats.py`, `src/wetland_change/mask.py`, everything under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/` and `scripts/fetch_aoi.py`. st-b6bf's pre-registered rows reuse `discover`, the guards of `process_scene`, `check_band_scaling` and `read_stack`; st-dd0d lists every commit to `verify/`, `pipeline.toml`, `pipeline.yml` or `fetch_aoi.py` until its sample closes. Reuse these by import (private helpers included) instead of editing them.
- Never read or write the shared output store (`s3://<OUTPUT_BUCKET>/`): st-b6bf bars any read of it until its decision files are committed. Never run `run`, `backfill`, `score` or `verify` over a scene sensed on or after 2026-11-12. Never read a pipeline.yml or verify.yml run log, a `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`, or an st-dd0d sample report.
- Staging roots are local: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`, `.../staging/overlap-cdse` and `.../staging/cdse-2022`.
- `data/external/` is untracked and absent from story worktrees. Symlink it from the main checkout (`ln -s /Users/jarrodbaker/Documents/swan-wetland-change/data/external data/external`) before any command or test that loads the AOI; never commit it.
- CDSE eodata S3 keys: 1Password vault `luminosity`, item `swan-wetland`; field `credential` is the access key, field `password` the secret. Load them as `CDSE_S3_ACCESS_KEY=$(op item get swan-wetland --vault luminosity --fields label=credential --reveal)` and `CDSE_S3_SECRET_KEY=$(op item get swan-wetland --vault luminosity --fields label=password --reveal)` with `AWS_PROFILE` and the `AWS_*` key variables unset. Never print, log, commit or store them.
- Run Python that reads downloaded files with `-I`. Docs use flat prose and no em dashes. Every dataset first used gets a `data/SOURCES.md` row in the same commit (AGENTS.md).
- Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
