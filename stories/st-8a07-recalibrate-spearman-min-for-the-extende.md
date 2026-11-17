---
id: st-8a07
title: Recalibrate spearman_min for the extended history
type: chore
epic: st-3d0f
priority: P2
depends_on: [st-c911, st-b6bf]
touches: [config/pipeline.toml, docs/decisions/**, docs/research/**]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Compute the recalibrated `spearman_min` for the history extended by the staged CDSE 2022 rows, read-only, and commit it with ADR 0007's dated update, so that verify does not fail on the larger history once the merge story copies the rows into the store. The rule (ADR 0007, restated in the LEARNINGS.md section `## Pre-registered hypotheses (CDSE extended history, ...)`): the floor to 0.01 of the lowest per-lake rho minus 0.02, from `docs/research/2026-11-06-spearman-calibration.py` run unchanged. Current value 0.83 in `config/pipeline.toml` (`spearman_min`).

1. Build a local union root: download read-only the store's `observations/` and ledger into a temporary directory (re-export the `accu-tracker` credentials first), then add the staged `observations/` and ledger parts from `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/cdse-2022`. Never write to the store.
2. Run the calibration script on the union root and save its rows as `docs/research/<today>-spearman-calibration-extended.csv` with a short report `.md` (command, commit, newest scene, rows read, per-lake rho, the computed value).
3. Set `spearman_min` in `config/pipeline.toml` to the computed value, and add a dated update to ADR 0007 giving the value, the inputs and the sha256 of the script and the CSV (ADR 0007's Consequences say to update these together). If the value equals 0.83, change no config line and record that in ADR 0007.

This commit touches `config/pipeline.toml`; if st-dd0d's sample is still open its rule lists the commit, which it allows. Do not push: the merge story pushes this commit and writes the store in one window before the 10:17 UTC scheduled run.

## Acceptance Criteria

- [ ] `docs/research/<today>-spearman-calibration-extended.csv` and its `.md` report are committed, and the report's earliest observation date is in 2022-01.
- [ ] `config/pipeline.toml` `spearman_min` equals the floor to 0.01 of the CSV's lowest per-lake rho minus 0.02 (a one-line `-I` Python check quoted in the report).
- [ ] ADR 0007 has a new dated update with the value and the sha256 of the script and the CSV, and `sha256sum` of both files matches it.
- [ ] `git diff --stat $(git merge-base HEAD main) HEAD -- docs/research/2026-11-06-spearman-calibration.py src/wetland_change/verify` prints nothing.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10", merge phase)

- Depends on st-b6bf: its decision files are committed, so its blindness rule no longer applies and the output store may be read. st-dd0d's rule still runs until its sample closes (by 2027-01-31): commits touching `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/pipeline.yml` or `scripts/fetch_aoi.py` are listed by its rule (allowed), and no st-dd0d sample report is opened by hand. Leave `src/wetland_change/verify/` byte-identical.
- Store credentials: the `accu-tracker` profile via `aws login`; exported credentials expire after 15 minutes, so re-export before each S3 step. The bucket is the `OUTPUT_BUCKET` repository variable (`gh variable get OUTPUT_BUCKET`).
- Writing to the store and pushing to GitHub are outward actions that need Jarrod's explicit ask in the session. When the story reaches one without that ask, park with the exact command list as the question.
- Staging roots: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/{overlap-c1,overlap-cdse,cdse-2022}`. `data/external/` is untracked; symlink it from the main checkout before loading the AOI.
- Docs use flat prose and no em dashes. Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
