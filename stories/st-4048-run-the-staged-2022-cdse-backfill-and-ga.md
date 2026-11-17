---
id: st-4048
title: Run the staged 2022 CDSE backfill and gap-row checks
type: spike
epic: st-3d0f
priority: P1
depends_on: [st-59c8, st-ef8c]
touches: [docs/research/**, docs/decisions/**]
exclusive: false
gates: [test]
created: 2026-11-17
updated: 2026-11-17
---
## Description

Run the staged CDSE backfill of the 2022 gap and the reported gap-row checks. Start only if ADR 0018's Evidence section and LEARNINGS.md `## Results (CDSE overlap, ...)` record an overall pass; if they record a fail, park this story asking Jarrod whether to cancel the rest of the epic.

Measured scope (epic): about 185 acquisitions, about 76 GB downloaded and deleted per product, a few hours. The CDSE S3 quota for this account has not been checked: watch for HTTP 429 or quota errors, and on a quota stop park with the counts reached instead of retrying in a loop.

1. With the CDSE keys loaded: `uv run wetland-change backfill-cdse --start 2022-01-01 --end 2022-11-30 --output-root /Users/jarrodbaker/Documents/swan-wetland-change-data/staging/cdse-2022` (background). Rerun the same command after an interruption; it skips finished items.
2. Run the committed `docs/research/*-cdse-gap-checks.py` on that root, writing `docs/research/<today>-cdse-gap-checks.csv` and `.json`.
3. Write `docs/research/<today>-cdse-gap-run.md`: commands, code commit, admitted, succeeded, failed and rejected counts (rejections by reason, all per tile), bytes downloaded, wall time, and the gap-check counts.
4. Add the counts and the report path to ADR 0018's Evidence section; status unchanged.

## Acceptance Criteria

- [ ] The staging root holds observations for 2022 only, one or more ledger parts, a run manifest per run, and download manifests whose files are all verified (a short `-I` Python check over the root, quoted in the report).
- [ ] The report's succeeded count plus failed count equals the admitted count, and it lists every failed item with its error.
- [ ] `docs/research/<today>-cdse-gap-run.md` and the gap-check CSV and JSON are committed, and ADR 0018's Evidence section names the report.
- [ ] The cache directory the run used (`cache_dir` in `config/cdse-backfill.toml`, relative to the worktree) holds no product folder.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10")

- Leave these byte-identical: `src/wetland_change/catalogue/`, `src/wetland_change/config.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/raster/`, `src/wetland_change/stats.py`, `src/wetland_change/mask.py`, everything under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/` and `scripts/fetch_aoi.py`. st-b6bf's pre-registered rows reuse `discover`, the guards of `process_scene`, `check_band_scaling` and `read_stack`; st-dd0d lists every commit to `verify/`, `pipeline.toml`, `pipeline.yml` or `fetch_aoi.py` until its sample closes. Reuse these by import (private helpers included) instead of editing them.
- Never read or write the shared output store (`s3://<OUTPUT_BUCKET>/`): st-b6bf bars any read of it until its decision files are committed. Never run `run`, `backfill`, `score` or `verify` over a scene sensed on or after 2026-11-12. Never read a pipeline.yml or verify.yml run log, a `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`, or an st-dd0d sample report.
- Staging roots are local: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`, `.../staging/overlap-cdse` and `.../staging/cdse-2022`.
- `data/external/` is untracked and absent from story worktrees. Symlink it from the main checkout (`ln -s /Users/jarrodbaker/Documents/swan-wetland-change/data/external data/external`) before any command or test that loads the AOI; never commit it.
- CDSE eodata S3 keys: 1Password vault `luminosity`, item `swan-wetland`; field `credential` is the access key, field `password` the secret. Load them as `CDSE_S3_ACCESS_KEY=$(op item get swan-wetland --vault luminosity --fields label=credential --reveal)` and `CDSE_S3_SECRET_KEY=$(op item get swan-wetland --vault luminosity --fields label=password --reveal)` with `AWS_PROFILE` and the `AWS_*` key variables unset. Never print, log, commit or store them.
- Run Python that reads downloaded files with `-I`. Docs use flat prose and no em dashes. Every dataset first used gets a `data/SOURCES.md` row in the same commit (AGENTS.md).
- Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
