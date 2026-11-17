---
id: st-7219
title: Add the CDSE overlap comparison script
type: feature
epic: st-3d0f
priority: P1
complexity: hard
depends_on: [st-3c22, st-a33f]
touches: [docs/research/**, tests/test_cdse_overlap*.py]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Write the script that applies the pre-registered CDSE overlap rules O1 to O3 (LEARNINGS.md, section `## Pre-registered rules (CDSE overlap, ...)`, committed by the ADR 0018 story; read it first and implement it exactly) to two local staging roots covering 2022-12-01 to 2023-02-28: one from Earth Search c1 (`wetland-change backfill`) and one from CDSE (`wetland-change backfill-cdse --cdse-config config/cdse-overlap.toml --keep-downloads`). The run story executes it; this story writes and tests it. LEARNINGS.md requires the script and its tests to be committed before the decision run.

Script `docs/research/<today>-cdse-overlap.py` (date the day you write it), argparse options `--c1-root`, `--cdse-root`, `--cdse-cache`, `--out-csv`, `--out-json`, and a docstring giving the run command:

- Matched acquisitions: succeeded ledger rows from both roots with equal sensing time to the second, relative orbit and tile.
- Pixels: rebuild each c1 `SceneItem` from its ledger `source_item` with `parse_item` and each CDSE `SceneItem` with the CDSE adapter over the cache files, read both with `read_stack` and a plain `RasterioReader`, and compute clear and wet pixels per polygon by calling the same functions `process_scene` uses (`clear_mask` in `src/wetland_change/mask.py`, `water_pixels` in `src/wetland_change/stats.py`, the polygon rasterisation and the configured water setting per polygon). Do not reimplement a threshold.
- Matched rows, counts a, b, n, per-row agreement and gap_pp, pooled agreement and O1 to O3 exactly as the pre-registration defines them, in `fractions.Fraction` arithmetic, floats only for display.
- Outputs: a CSV with one row per matched row (acquisition, layer, polygon id, tile, a, b, n, agreement, gap_pp, both ndvi_median values, both valid_fraction values, SCL class 6 counts) and a JSON with the O1 to O3 values, thresholds, pass or fail each, the overall decision, and the reported-only breakdowns (per layer, per tile, SCL class 6 agreement, valid_fraction differences, rows and acquisitions present on one side only).

Tests `tests/test_cdse_overlap.py`, loading the script by path as `tests/test_research_scripts.py` does, on synthetic stacks and tiny staging roots in `tmp_path` (no network).

## Acceptance Criteria

- [ ] `ls docs/research/*-cdse-overlap.py` lists one script and `uv run python -I <script> --help` exits 0.
- [ ] Tests compute a, b, n by hand for a synthetic pair and assert the script's agreement and gap_pp equal them as `Fraction`s.
- [ ] Tests show rows with `valid_fraction` at 0.8 on either side, or fewer than 100 mutually clear pixels, are excluded from the matched set, and that one-sided acquisitions appear only in the reported breakdown.
- [ ] Tests at the boundaries: pooled agreement exactly 0.98 passes O1, |gap_pp| exactly 5.0 counts inside O2, an O2 share exactly 0.95 passes, a median difference exactly 0.02 passes O3, and a value just past each fails; any single failure makes the overall decision fail.
- [ ] A test asserts the wet call matches `water_pixels` for the polygon's configured water setting, including the ramsar-21 setting.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10")

- Leave these byte-identical: `src/wetland_change/catalogue/`, `src/wetland_change/config.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/raster/`, `src/wetland_change/stats.py`, `src/wetland_change/mask.py`, everything under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/` and `scripts/fetch_aoi.py`. st-b6bf's pre-registered rows reuse `discover`, the guards of `process_scene`, `check_band_scaling` and `read_stack`; st-dd0d lists every commit to `verify/`, `pipeline.toml`, `pipeline.yml` or `fetch_aoi.py` until its sample closes. Reuse these by import (private helpers included) instead of editing them.
- Never read or write the shared output store (`s3://<OUTPUT_BUCKET>/`): st-b6bf bars any read of it until its decision files are committed. Never run `run`, `backfill`, `score` or `verify` over a scene sensed on or after 2026-11-12. Never read a pipeline.yml or verify.yml run log, a `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`, or an st-dd0d sample report.
- Staging roots are local: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`, `.../staging/overlap-cdse` and `.../staging/cdse-2022`.
- `data/external/` is untracked and absent from story worktrees. Symlink it from the main checkout (`ln -s /Users/jarrodbaker/Documents/swan-wetland-change/data/external data/external`) before any command or test that loads the AOI; never commit it.
- CDSE eodata S3 keys: 1Password vault `luminosity`, item `swan-wetland`; field `credential` is the access key, field `password` the secret. Load them as `CDSE_S3_ACCESS_KEY=$(op item get swan-wetland --vault luminosity --fields label=credential --reveal)` and `CDSE_S3_SECRET_KEY=$(op item get swan-wetland --vault luminosity --fields label=password --reveal)` with `AWS_PROFILE` and the `AWS_*` key variables unset. Never print, log, commit or store them.
- Run Python that reads downloaded files with `-I`. Docs use flat prose and no em dashes. Every dataset first used gets a `data/SOURCES.md` row in the same commit (AGENTS.md).
- Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
