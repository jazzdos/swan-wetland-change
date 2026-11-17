---
id: st-c911
title: Pre-register the extended-history re-test of H1 to H4
type: chore
epic: st-3d0f
priority: P2
depends_on: [st-4048]
touches: [LEARNINGS.md]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Pre-register the re-test of the backfill hypotheses H1 to H4 on the history extended back to 2022-01 by the staged CDSE rows, before anyone computes them. Context: LEARNINGS.md section `## Pre-registered hypotheses (st-b983, 2026-11-02)` (H1 to H4 and their definitions), `docs/research/2026-11-02-backfill-analysis.py` (their implementation), ADR 0007 (the `spearman_min` recalibration rule), ADR 0018 and the epic.

Append to LEARNINGS.md a section `## Pre-registered hypotheses (CDSE extended history, <today>)`; change no earlier line and leave every recorded result as it stands. It must state:

- H1 to H4 re-tested with the st-b983 definitions and verdict rules unchanged, on the merged history (store plus the staged `cdse-2022` rows), with the one stated change that H4's window starts 2022-01-01 instead of 2022-12-01. The baselines of H1 to H3 change because earlier dates now exist (ADR 0004 baselines use the same polygon and month on strictly earlier dates); say so.
- An expected verdict for each of H1 to H4 with its reason, written before the run.
- The recalibration: new `spearman_min` is the floor to 0.01 of the lowest per-lake rho minus 0.02 over the merged history, by `docs/research/2026-11-06-spearman-calibration.py` unchanged, as ADR 0007 states; the current value is 0.83.
- The analysis command to be run, and that the script runs at a commit recorded in the results.
- Disclosure of what has been seen: the overlap report, the gap-run report, their counts; no H1 to H4 value and no per-lake rho has been computed on the merged history.

Docs only. Read the store for nothing in this story.

## Acceptance Criteria

- [ ] LEARNINGS.md contains the heading `## Pre-registered hypotheses (CDSE extended history,` and the section names H1, H2, H3 and H4, each with an expected verdict.
- [ ] `git diff --numstat $(git merge-base HEAD main) HEAD -- LEARNINGS.md` shows 0 deleted lines.
- [ ] The section contains `2022-01-01`, `0.02`, `0.83` and `docs/research/2026-11-06-spearman-calibration.py`.
- [ ] `git diff $(git merge-base HEAD main) HEAD -- LEARNINGS.md | grep "^+" | grep -c "—"` prints 0.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10")

- Leave these byte-identical: `src/wetland_change/catalogue/`, `src/wetland_change/config.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/raster/`, `src/wetland_change/stats.py`, `src/wetland_change/mask.py`, everything under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/` and `scripts/fetch_aoi.py`. st-b6bf's pre-registered rows reuse `discover`, the guards of `process_scene`, `check_band_scaling` and `read_stack`; st-dd0d lists every commit to `verify/`, `pipeline.toml`, `pipeline.yml` or `fetch_aoi.py` until its sample closes. Reuse these by import (private helpers included) instead of editing them.
- Never read or write the shared output store (`s3://<OUTPUT_BUCKET>/`): st-b6bf bars any read of it until its decision files are committed. Never run `run`, `backfill`, `score` or `verify` over a scene sensed on or after 2026-11-12. Never read a pipeline.yml or verify.yml run log, a `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`, or an st-dd0d sample report.
- Staging roots are local: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`, `.../staging/overlap-cdse` and `.../staging/cdse-2022`.
- `data/external/` is untracked and absent from story worktrees. Symlink it from the main checkout (`ln -s /Users/jarrodbaker/Documents/swan-wetland-change/data/external data/external`) before any command or test that loads the AOI; never commit it.
- CDSE eodata S3 keys: 1Password vault `luminosity`, item `swan-wetland`; field `credential` is the access key, field `password` the secret. Load them as `CDSE_S3_ACCESS_KEY=$(op item get swan-wetland --vault luminosity --fields label=credential --reveal)` and `CDSE_S3_SECRET_KEY=$(op item get swan-wetland --vault luminosity --fields label=password --reveal)` with `AWS_PROFILE` and the `AWS_*` key variables unset. Never print, log, commit or store them.
- Run Python that reads downloaded files with `-I`. Docs use flat prose and no em dashes. Every dataset first used gets a `data/SOURCES.md` row in the same commit (AGENTS.md).
- Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
