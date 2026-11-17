---
id: st-3c22
title: Write ADR 0018 and pre-register the CDSE overlap rules
type: chore
epic: st-3d0f
priority: P1
depends_on: []
touches: [docs/decisions/**, LEARNINGS.md, AGENTS.md]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Write the decision record and the pre-registration for the CDSE 2022 gap fill before any code exists. Part of the epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10"; read the epic body for the measured facts.

1. `docs/decisions/0018-cdse-baseline-0510-for-the-2022-gap.md`. Status line: `Status: Proposed YYYY-MM-DD. Amends 0001.`, with the date the ADR is committed. (ADR 0014 and 0015 are reserved by st-b6bf and st-dd0d; 0017 is the private-bucket decision.) Use the headings of ADR 0012 and 0013: Context, Decision-making, Decision, Pre-registration, Rejected alternatives, Evidence, Limits, Consequences. It must state:
   - Scope rule: CDSE supplies an acquisition only if sensed from 2022-01-01T00:00:00Z to 2022-11-30T23:59:59Z, cloud cover strictly below `stac.cloud_cover_max` (20.0), footprint intersecting the AOI, baseline 05.xx, and Earth Search c1 holding no item with the same sensing time, relative orbit and tile (from Earth Search STAC metadata, never the store). Where one acquisition has several products, the newest processing time wins and the others are logged rejections.
   - Scaling: from each band asset's `raster:scale`, `raster:offset` and `nodata`, checked against MTD_MSIL2A.xml by the unchanged `check_band_scaling`, and refused unless equal to 0.0001 and -0.1, the values of the stored c1 history.
   - Downloads to a local cache verified against `file:size` and `file:checksum`; reads of the local files through the unchanged `process_scene`; ledger `collection` recorded as `sentinel-2-l2a`; observation schema unchanged.
   - Decision-making: Jarrod's two answers on 2026-11-17 (stage now and merge after st-b6bf's decision files are committed; a separate adapter rather than a multi-source generalisation or synthetic c1 items, with the reasons) and his approval of the design.
   - The overlap gate (below), the reported gap-row checks (per-pass DEA Waterbodies wet fraction, NDVI against DEA NBART), the merge steps (pre-registered re-test, `spearman_min` recalibration by ADR 0007's rule, copy, `compact-ledger`, `score --start 2022-01-01`, `build-catalogue`) and that acceptance needs Jarrod's approval after the overlap result.
   - Rejected alternatives: windowed `/vsis3/` reads (about 29 s per window), the Sentinel Hub Process API, the Sentinel Hub OAuth client (HTTP 401 DAT-ZIP-609 on downloads).
2. LEARNINGS.md: append at the end a section `## Pre-registered rules (CDSE overlap, YYYY-MM-DD)`, dated the day it is committed. Append only; change no earlier line. It defines:
   - Matched acquisition: an Earth Search c1 item and a CDSE item from 2022-12-01 to 2023-02-28 with equal sensing time (to the second), relative orbit and tile, both succeeded in their staging runs.
   - Matched row: a matched acquisition and one polygon (Ramsar and DEA Waterbodies layers) with an observation row from both sources, `valid_fraction` above 0.8 on both, and at least 100 pixels clear in both sources and inside the polygon (`verify.min_clear_pixels`).
   - Counts per row, with c1 as the first source: clear is `clear_mask(scl, green, nir, swir16)` and inside; a setting calls a pixel wet as `water_pixels` (`src/wetland_change/stats.py`) does with the polygon's configured water setting; a = pixels c1 calls wet and CDSE dry, b the reverse, n the mutually clear count; agreement = 1 - (a + b) / n; gap_pp = 100 * (a - b) / n. Pooled agreement = 1 - sum(a + b) / sum(n). Exact rational arithmetic.
   - O1: pooled agreement over all matched rows is at least 0.98. O2: the share of matched rows with |gap_pp| at most 5.0 is at least 0.95. O3: the median over matched rows of |ndvi_median(c1) - ndvi_median(CDSE)|, from the two observation rows, is at most 0.02.
   - Decision: O1 to O3 all hold, the overlap passes and ADR 0018 may go to Jarrod for acceptance; any failure, nothing merges and ADR 0018 records the rejection.
   - Reported, not decision inputs: O1 to O3 per layer and per tile, SCL class 6 agreement, `valid_fraction` differences, rows and acquisitions on one side only.
   - Disclosure: what has been seen so far is STAC metadata counts and one CDSE product (S2A_MSIL2A_20221127T021341_N0510_R060_T50JML_20240803T071855) read as 1024-pixel windows for timing; no c1 against CDSE value has been computed. The thresholds are proposals approved with the design, not measured.
   - The comparison script and its tests are committed before the decision run.
3. AGENTS.md: the rule "Reflectance is always DN times scale plus offset read from the item's `raster:bands` ..." and the rule "Only collection `sentinel-2-c1-l2a`. Never mix in `sentinel-2-l2a`." each gain a clause saying the CDSE backfill of ADR 0018 is the one exception (acquisitions from 2022-01 to 2022-11 that c1 lacks, scale and offset from the assets' `raster:scale` and `raster:offset`), and that nothing from it enters the output store before ADR 0018 is accepted. The locked decision "Sentinel-2 Collection 1 only" gets the same pointer.

Docs only; no code.

## Acceptance Criteria

- [ ] `docs/decisions/0018-cdse-baseline-0510-for-the-2022-gap.md` exists, its second line matches `^Status: Proposed [0-9]{4}-[0-9]{2}-[0-9]{2}\. Amends 0001\.`.
- [ ] The ADR contains the scope rule dates `2022-01-01T00:00:00Z` and `2022-11-30T23:59:59Z`, the values `0.0001` and `-0.1`, and the O1 to O3 thresholds `0.98`, `0.95`, `5.0` and `0.02`.
- [ ] `git diff --numstat $(git merge-base HEAD main) HEAD -- LEARNINGS.md` shows 0 deleted lines, and LEARNINGS.md contains a heading matching `^## Pre-registered rules \(CDSE overlap, [0-9]{4}-[0-9]{2}-[0-9]{2}\)$` with O1, O2 and O3 and the matched-row definition.
- [ ] `grep -c "ADR 0018" AGENTS.md` is at least 3.
- [ ] `grep -c "—"` over the new ADR and the added LEARNINGS.md lines is 0.
- [ ] `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts` and `uv run pytest -q` each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10")

- Leave these byte-identical: `src/wetland_change/catalogue/`, `src/wetland_change/config.py`, `src/wetland_change/pipeline.py`, `src/wetland_change/raster/`, `src/wetland_change/stats.py`, `src/wetland_change/mask.py`, everything under `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/` and `scripts/fetch_aoi.py`. st-b6bf's pre-registered rows reuse `discover`, the guards of `process_scene`, `check_band_scaling` and `read_stack`; st-dd0d lists every commit to `verify/`, `pipeline.toml`, `pipeline.yml` or `fetch_aoi.py` until its sample closes. Reuse these by import (private helpers included) instead of editing them.
- Never read or write the shared output store (`s3://<OUTPUT_BUCKET>/`): st-b6bf bars any read of it until its decision files are committed. Never run `run`, `backfill`, `score` or `verify` over a scene sensed on or after 2026-11-12. Never read a pipeline.yml or verify.yml run log, a `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`, or an st-dd0d sample report.
- Staging roots are local: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/overlap-c1`, `.../staging/overlap-cdse` and `.../staging/cdse-2022`.
- `data/external/` is untracked and absent from story worktrees. Symlink it from the main checkout (`ln -s /Users/jarrodbaker/Documents/swan-wetland-change/data/external data/external`) before any command or test that loads the AOI; never commit it.
- CDSE eodata S3 keys: 1Password vault `luminosity`, item `swan-wetland`; field `credential` is the access key, field `password` the secret. Load them as `CDSE_S3_ACCESS_KEY=$(op item get swan-wetland --vault luminosity --fields label=credential --reveal)` and `CDSE_S3_SECRET_KEY=$(op item get swan-wetland --vault luminosity --fields label=password --reveal)` with `AWS_PROFILE` and the `AWS_*` key variables unset. Never print, log, commit or store them.
- Run Python that reads downloaded files with `-I`. Docs use flat prose and no em dashes. Every dataset first used gets a `data/SOURCES.md` row in the same commit (AGENTS.md).
- Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
