---
id: st-587f
title: Merge the staged 2022 rows into the output store
type: chore
epic: st-3d0f
priority: P2
complexity: hard
depends_on: [st-8a07, st-c062, st-782f]
touches: [docs/research/**, docs/decisions/**, README.md]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Merge the staged CDSE 2022 rows into the shared output store, rescore and rebuild the catalogue, in one window before the 10:17 UTC scheduled run (`pipeline.yml` cron `17 10 * * *`). Read ADR 0018's merge steps first.

Preconditions, checked in this order; park with the question if one fails:

1. ADR 0018's status line reads `Status: Accepted`. If it still reads `Proposed`, park asking Jarrod to accept or reject ADR 0018, quoting the O1 to O3 values from its Evidence section. On Jarrod's answer, edit the status line (accepted, with date and "by Jarrod") as part of this story.
2. The `spearman_min` commit from the recalibration story is on local main.
3. Jarrod has asked, in this session, for the push and the store write. Otherwise park with the exact command list below as the question.

Steps, all before 10:17 UTC on one day, re-exporting the `accu-tracker` credentials before each S3 step:

1. Push main (carries the new `spearman_min`).
2. Copy `observations/`, the ledger part(s), the run manifest(s) and `cdse/downloads-*.json` from `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/cdse-2022` into the store unchanged, then list the copied keys and compare each object's size and sha256 (download back to a temporary directory) with the staged file.
3. `uv run wetland-change compact-ledger --output-root s3://<OUTPUT_BUCKET>/`, `uv run wetland-change score --start 2022-01-01 --end <today> --output-root s3://<OUTPUT_BUCKET>/`, `uv run wetland-change build-catalogue --output-root s3://<OUTPUT_BUCKET>/`.
4. Commit `docs/research/<today>-cdse-merge.md`: commands, times in UTC, commit, object counts, every checksum comparison, the compact, score and catalogue outputs.
5. README.md: rewrite the limitation bullet near line 669 ("Earth Search Collection 1 has no items before 2022-12 ...") and the backfill text near lines 252 to 269 to state that 2022-01 to 2022-11 comes from CDSE baseline 05.10 under ADR 0018; ADR 0018 Consequences gains the merge date.

Verify reads the latest daily run's scenes through `scenes_for_run` (`verify/run.py`), which re-parses `source_item` with the c1 collection pin; the CDSE run is never the latest daily run. Confirm from the code before step 2 that no scheduled verify path parses a CDSE ledger row, and park with what you found if one does.

## Acceptance Criteria

- [ ] ADR 0018's status line starts `Status: Accepted` and its Consequences name the merge date.
- [ ] `docs/research/<today>-cdse-merge.md` is committed, lists a size and sha256 match for every copied object, and records that the store write finished before 10:17 UTC on the merge day.
- [ ] The report quotes the `build-catalogue` output and the count of catalogue items derived from CDSE products, which equals the staged succeeded count.
- [ ] README.md no longer contains `- Earth Search Collection 1 has no items before 2022-12 for five of six` and contains `ADR 0018`.
- [ ] `git diff --stat $(git merge-base HEAD main) HEAD -- src/wetland_change/verify` prints nothing.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10", merge phase)

- Depends on st-b6bf: its decision files are committed, so its blindness rule no longer applies and the output store may be read. st-dd0d's rule still runs until its sample closes (by 2027-01-31): commits touching `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/pipeline.yml` or `scripts/fetch_aoi.py` are listed by its rule (allowed), and no st-dd0d sample report is opened by hand. Leave `src/wetland_change/verify/` byte-identical.
- Store credentials: the `accu-tracker` profile via `aws login`; exported credentials expire after 15 minutes, so re-export before each S3 step. The bucket is the `OUTPUT_BUCKET` repository variable (`gh variable get OUTPUT_BUCKET`).
- Writing to the store and pushing to GitHub are outward actions that need Jarrod's explicit ask in the session. When the story reaches one without that ask, park with the exact command list as the question.
- Staging roots: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/{overlap-c1,overlap-cdse,cdse-2022}`. `data/external/` is untracked; symlink it from the main checkout before loading the AOI.
- Docs use flat prose and no em dashes. Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
