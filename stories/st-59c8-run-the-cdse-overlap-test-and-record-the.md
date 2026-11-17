---
id: st-59c8
title: Run the CDSE overlap test and record the result
type: spike
epic: st-3d0f
priority: P1
depends_on: [st-7714, st-7219]
touches: [docs/research/**, docs/decisions/**, LEARNINGS.md]
exclusive: false
gates: [test]
created: 2026-11-17
updated: 2026-11-17
---
## Description

Run the pre-registered CDSE overlap test and record the result. Read LEARNINGS.md section `## Pre-registered rules (CDSE overlap, ...)` and ADR 0018 first; this run is their decision run, so the rules and the committed script are used as they stand. Any change to them before the run is a new pre-registration and needs Jarrod.

Steps (long-running commands in the background; about 35 GB of disk for the kept CDSE downloads):

1. `uv run wetland-change backfill --start 2022-12-01 --end 2023-02-28 --output-root /Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`.
2. With the CDSE keys loaded: `uv run wetland-change backfill-cdse --start 2022-12-01 --end 2023-02-28 --cdse-config config/cdse-overlap.toml --keep-downloads --output-root /Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-cdse`.
3. Run the committed `docs/research/*-cdse-overlap.py` on the two roots and the cache, writing `docs/research/<today>-cdse-overlap.csv` and `.json`.
4. Write `docs/research/<today>-cdse-overlap.md`: commands, code commit, item counts per source and tile, matched acquisitions and rows, O1 to O3 values against their thresholds, the decision, and the reported-only breakdowns.
5. Append to LEARNINGS.md a dated `## Results (CDSE overlap, <today>)` section stating each rule's value and the decision; change no earlier line.
6. Add the numbers, the report path and the script's sha256 to ADR 0018's Evidence section. Leave its status `Proposed`: acceptance is Jarrod's call. If the decision is fail, write in ADR 0018 that nothing merges and the README limitation stands.
7. After the report is committed, delete the overlap CDSE cache.

Add a `data/SOURCES.md` row for the committed overlap CSV (derived from Earth Search c1 and CDSE eodata, the two staging roots, the commit) if the table convention for derived research outputs calls for one.

## Acceptance Criteria

- [ ] `docs/research/<today>-cdse-overlap.md`, `.csv` and `.json` are committed and the JSON holds O1, O2, O3 and a decision of pass or fail.
- [ ] `git diff $(git merge-base HEAD main) HEAD -- docs/research/*-cdse-overlap.py LEARNINGS.md` shows no change to the script and only added lines in LEARNINGS.md, including the heading `## Results (CDSE overlap,`.
- [ ] ADR 0018's Evidence section contains the three values and the report path, and its status line still starts `Status: Proposed`.
- [ ] Both staging roots hold a run manifest and the CDSE manifest shows every file verified.
- [ ] The overlap CDSE cache directory no longer exists.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10")

- Leave these byte-identical: `src/wetland_change/catalogue/`, `src/wetland_change/config.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/raster/`, `src/wetland_change/stats.py`, `src/wetland_change/mask.py`, everything under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/` and `scripts/fetch_aoi.py`. st-b6bf's pre-registered rows reuse `discover`, the guards of `process_scene`, `check_band_scaling` and `read_stack`; st-dd0d lists every commit to `verify/`, `pipeline.toml`, `pipeline.yml` or `fetch_aoi.py` until its sample closes. Reuse these by import (private helpers included) instead of editing them.
- Never read or write the shared output store (`s3://<OUTPUT_BUCKET>/`): st-b6bf bars any read of it until its decision files are committed. Never run `run`, `backfill`, `score` or `verify` over a scene sensed on or after 2026-11-12. Never read a pipeline.yml or verify.yml run log, a `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`, or an st-dd0d sample report.
- Staging roots are local: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`, `.../staging/overlap-cdse` and `.../staging/cdse-2022`.
- `data/external/` is untracked and absent from story worktrees. Symlink it from the main checkout (`ln -s /Users/jarrodbaker/Documents/swan-wetland-change/data/external data/external`) before any command or test that loads the AOI; never commit it.
- CDSE eodata S3 keys: 1Password vault `luminosity`, item `swan-wetland`; field `credential` is the access key, field `password` the secret. Load them as `CDSE_S3_ACCESS_KEY=$(op item get swan-wetland --vault luminosity --fields label=credential --reveal)` and `CDSE_S3_SECRET_KEY=$(op item get swan-wetland --vault luminosity --fields label=password --reveal)` with `AWS_PROFILE` and the `AWS_*` key variables unset. Never print, log, commit or store them.
- Run Python that reads downloaded files with `-I`. Docs use flat prose and no em dashes. Every dataset first used gets a `data/SOURCES.md` row in the same commit (AGENTS.md).
- Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
