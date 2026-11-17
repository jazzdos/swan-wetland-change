---
id: st-782f
title: Document the staged CDSE backfill in README.md
type: chore
epic: st-3d0f
priority: P2
depends_on: [st-7714]
touches: [README.md]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Document the CDSE 2022 backfill in README.md while it is staged and not merged. ADR 0018 and the epic hold the context.

- Sources table (near line 199, the Copernicus Data Space row): add that CDSE eodata S3 products at baseline 05.10 are the staged source for 2022-01 to 2022-11 (ADR 0018), read with keys from 1Password, and not yet in the store.
- Backfill section (near lines 239 to 269): add a subsection on `wetland-change backfill-cdse` with the full option list, how to load the keys (the `op item get` lines from the shared constraints, keys never echoed), the default cache path, the staging roots, and that its output enters the store only through the merge steps of ADR 0018 after st-b6bf's decision files are committed and ADR 0018 is accepted.
- Leave the limitation bullet near line 669 ("Earth Search Collection 1 has no items before 2022-12 ...") unchanged; the merge story rewrites it when the claim changes.

Docs only.

## Acceptance Criteria

- [ ] `grep -c "backfill-cdse" README.md` is at least 2 and README.md contains `CDSE_S3_ACCESS_KEY`, `CDSE_S3_SECRET_KEY` and `ADR 0018`.
- [ ] Every option shown by `uv run wetland-change backfill-cdse --help` appears in README.md.
- [ ] README.md still contains the line `- Earth Search Collection 1 has no items before 2022-12 for five of six`.
- [ ] `git diff $(git merge-base HEAD main) HEAD -- README.md | grep "^+" | grep -c "—"` prints 0.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10")

- Leave these byte-identical: `src/wetland_change/catalogue/`, `src/wetland_change/config.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/raster/`, `src/wetland_change/stats.py`, `src/wetland_change/mask.py`, everything under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/` and `scripts/fetch_aoi.py`. st-b6bf's pre-registered rows reuse `discover`, the guards of `process_scene`, `check_band_scaling` and `read_stack`; st-dd0d lists every commit to `verify/`, `pipeline.toml`, `pipeline.yml` or `fetch_aoi.py` until its sample closes. Reuse these by import (private helpers included) instead of editing them.
- Never read or write the shared output store (`s3://<OUTPUT_BUCKET>/`): st-b6bf bars any read of it until its decision files are committed. Never run `run`, `backfill`, `score` or `verify` over a scene sensed on or after 2026-11-12. Never read a pipeline.yml or verify.yml run log, a `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`, or an st-dd0d sample report.
- Staging roots are local: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`, `.../staging/overlap-cdse` and `.../staging/cdse-2022`.
- `data/external/` is untracked and absent from story worktrees. Symlink it from the main checkout (`ln -s /Users/jarrodbaker/Documents/swan-wetland-change/data/external data/external`) before any command or test that loads the AOI; never commit it.
- CDSE eodata S3 keys: 1Password vault `luminosity`, item `swan-wetland`; field `credential` is the access key, field `password` the secret. Load them as `CDSE_S3_ACCESS_KEY=$(op item get swan-wetland --vault luminosity --fields label=credential --reveal)` and `CDSE_S3_SECRET_KEY=$(op item get swan-wetland --vault luminosity --fields label=password --reveal)` with `AWS_PROFILE` and the `AWS_*` key variables unset. Never print, log, commit or store them.
- Run Python that reads downloaded files with `-I`. Docs use flat prose and no em dashes. Every dataset first used gets a `data/SOURCES.md` row in the same commit (AGENTS.md).
- Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
