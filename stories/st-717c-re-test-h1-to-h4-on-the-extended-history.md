---
id: st-717c
title: Re-test H1 to H4 on the extended history
type: spike
epic: st-3d0f
priority: P2
depends_on: [st-587f]
touches: [docs/research/**, LEARNINGS.md, README.md]
exclusive: false
gates: [test]
created: 2026-11-17
updated: 2026-11-17
---
## Description

Run the pre-registered re-test of H1 to H4 on the merged history and record the results. Read the LEARNINGS.md section `## Pre-registered hypotheses (CDSE extended history, ...)` first and follow it exactly: its command, its definitions, its verdict rules. Changing any of them is a new pre-registration and needs Jarrod.

1. Run the analysis it names (`docs/research/2026-11-02-backfill-analysis.py` with the stated window change) against the store after the merge, recording the commit.
2. Commit the outputs as `docs/research/<today>-extended-history-hypotheses.{csv,md}`: per hypothesis the verdict, the numbers behind it and the expected verdict, plus a comparison with the st-b983 results.
3. Append a dated `## Results (CDSE extended history, <today>)` section to LEARNINGS.md; change no earlier line.
4. README.md's backfill results table (near line 248, H1 to H4 rows): add the extended-history verdict beside each recorded one without removing the recorded text.

## Acceptance Criteria

- [ ] `docs/research/<today>-extended-history-hypotheses.md` and `.csv` are committed and give a verdict for each of H1, H2, H3 and H4.
- [ ] LEARNINGS.md contains the heading `## Results (CDSE extended history,` and `git diff --numstat $(git merge-base HEAD main) HEAD -- LEARNINGS.md` shows 0 deleted lines.
- [ ] `git diff $(git merge-base HEAD main) HEAD -- docs/research/2026-11-02-backfill-analysis.py` prints nothing.
- [ ] README.md's H1 to H4 rows each carry the extended-history verdict and still carry the recorded one.
- [ ] The four gates each exit 0.

## Shared constraints (epic "Fill the 2022 Collection 1 gap from CDSE baseline 05.10", merge phase)

- Depends on st-b6bf: its decision files are committed, so its blindness rule no longer applies and the output store may be read. st-dd0d's rule still runs until its sample closes (by 2027-01-31): commits touching `src/wetland_change/verify/`, `config/pipeline.toml`, `.github/workflows/pipeline.yml` or `scripts/fetch_aoi.py` are listed by its rule (allowed), and no st-dd0d sample report is opened by hand. Leave `src/wetland_change/verify/` byte-identical.
- Store credentials: the `accu-tracker` profile via `aws login`; exported credentials expire after 15 minutes, so re-export before each S3 step. The bucket is the `OUTPUT_BUCKET` repository variable (`gh variable get OUTPUT_BUCKET`).
- Writing to the store and pushing to GitHub are outward actions that need Jarrod's explicit ask in the session. When the story reaches one without that ask, park with the exact command list as the question.
- Staging roots: `/Users/jarrodbaker/Documents/swan-wetland-change-data/staging/{overlap-c1,overlap-cdse,cdse-2022}`. `data/external/` is untracked; symlink it from the main checkout before loading the AOI.
- Docs use flat prose and no em dashes. Gates, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
