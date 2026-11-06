---
id: st-ff89
title: Run the reproducibility audit and write the Milestone 2 handoff
type: chore
priority: P3
depends_on: [st-06a8, st-b983]
touches: [README.md, docs/handoffs/2026-11-06-milestone-2.md, docs/research/2026-11-06-reproducibility-audit.md]
exclusive: false
created: 2026-10-29
updated: 2026-11-06
---
## Description

Success criterion 5 (design): run the `geospatial:reproducibility-audit` skill over the repository as the final gate, and write the Milestone 2 handoff. Fix nothing in this story; file a discovered story for each failing audit item with `story create --discovered-from <this id>`.

The handoff states the project state, verification status per matrix row, deviations, and the follow-ups the board could not do:

- AWS account, bucket and `infra` apply.
- GitHub repository creation and its repository variables.
- Spikes 5 (runner dry run), 6 (static catalogue in stac-browser) and 7 (DuckDB over S3).
- The four-week unattended run.
- Codename registry and inventory rows.
- DBCA-010 licence confirmation.
- The CDSE option for the 2022 gap, which needs a Copernicus account.

## Acceptance Criteria

- [ ] `docs/research/<date>-reproducibility-audit.md` lists every audit item with pass or fail.
- [ ] Each failing audit item cites a story id filed with `--discovered-from` this story.
- [ ] `docs/handoffs/<date>-milestone-2.md` exists and lists each follow-up named in the Description.

## Implementation Plan

## Verified state (worktree /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-ff89, HEAD 2665046)

- Prerequisites st-06a8 (README) and st-b983 (backfill) are done on the board; all review-fix stories named in the orchestrator context are merged. docs/research/2026-11-04-milestone-2-review.md (578 lines, findings 1 to 7 and L1 to L9) and docs/handoffs/2026-10-29-milestone-1.md (format reference) exist. docs/decisions/0008 and 0009 exist.
- Open board: st-2a78 (ramsar-12 water setting), st-c667 (S3 deletes re-create directory markers), st-f849 (Milestone 2 epic). st-ff89 is the only in-progress story. The main checkout has an unstaged edit to stories/st-ff89-*.md and three untracked .DS_Store files; none of that is to be touched or staged.
- No environment/data in the worktree: data/external does not exist, so `uv run python scripts/fetch_aoi.py` must run before the live tests. data/external is gitignored (data/* except data/SOURCES.md).
- Live tests are tests/test_live_public_read.py (skips while catalogue.base_url is the .invalid placeholder; makes no writes), tests/test_live_verify.py, tests/test_live_waterbodies.py (read-only network), tests/test_backfill.py::test_live_backfill_over_the_27_october_pass (writes only under tmp_path) and tests/test_verify_ndvi.py::test_ndvi_scores_thomsons_on_newest_pass_with_dea_ard (read-only). None writes outside tmp_path. pyproject addopts is "-q -m 'not live'", so live runs need `-o addopts=""`.
- Audit skill: /Users/jarrodbaker/.claude/plugins/cache/geospatial-framework/geospatial/0.1.0/skills/reproducibility-audit/SKILL.md defines 10 steps (scope, environment, data manifest, remote provenance, CRS and units, randomness, execution, outputs, licence, limits) and four grep rows. Candidate failures spotted in a quick look, to be verified not assumed: no LICENSE file in the repo root (step 9); scratch/spikes/s2_calibrate.py and polygon_calibrate.py are gitignored and untracked (the 2026-10-30 note asks the audit to decide whether to commit them); data/SOURCES.md has several "per run" or "n/a (read live)" rows with no checksum (step 3); the only RNG is scripts/compare_dea_tools_indices.py:137 (seeded 42, pass); no pip/conda install, no `.crs =` assignment and no EPSG:3857 in src or scripts.
- README.md line 54 says "reruns are safe" and the Limitations section (line 317 onward) predates the review; both must be reconciled with the review and with the merged fix stories.

## Steps

### Batch 1, task `audit` (one task)
1. Invoke `geospatial:reproducibility-audit` through the Skill tool (fallback: read its SKILL.md and apply every item).
2. Run the four skill grep rows plus uv-based equivalents of the shell snippets (`shasum -a 256` against data/SOURCES.md checksums after the AOI fetch; `uv lock --check` for environment vs lock; a one-line runtime-version print under `uv run`). Check whether outputs record runtime versions, CRS, units, STAC item ids, scale and offset (grep src/wetland_change/manifest.py, pipeline.py, outputs/*.py).
3. Run `uv run python scripts/fetch_aoi.py` in the worktree, then `uv run pytest -m live -q -o addopts=""` after confirming no live test writes outside tmp_path. Record each live test's outcome. A live failure is audit evidence, filed not fixed.
4. Read, never move or delete, the spike scripts in the main checkout (scratch/spikes/s2_calibrate.py, polygon_calibrate.py and logs); decide whether they should be committed (they back LEARNINGS.md 'S2 water calibration' and 'Per-polygon water calibration'); if yes that is a failing row.
5. Check the open board read-only for each failing item; cite an existing open story id instead of a FILE token when it covers the item exactly.
6. Write docs/research/2026-11-06-reproducibility-audit.md: scope, one table (check, file:line, severity, pass/fail, evidence, story id or FILE-n token), live test results, runtime versions, then "could not be checked". Every skill item gets a row.
7. Write the scratchpad JSON /private/tmp/claude-501/-Users-jarrodbaker-Documents-swan-wetland-change/22c55541-8069-467e-b57a-005b03353aa1/scratchpad/st-ff89/to-file.json (array, one object per FILE token; `[]` if none).
8. Proof: the audit doc has no row without pass or fail; every fail row has a story id or FILE-n token; the JSON parses and its tokens equal the tokens in the doc. No story mutation, no commit, no source fix.

### Batch 2, task `handoff` (one task, runs after the orchestrator files stories and replaces tokens)
1. Read the audit doc for filed ids.
2. Gather facts: main HEAD (`git -C /Users/jarrodbaker/Documents/swan-wetland-change rev-parse HEAD`), `git remote`/`git status -sb` to state nothing is pushed, merged stories from `git log --merges --oneline` (st-1a95, st-2cc2, st-7047, st-fb21, st-5f74, st-fbe8 and st-9aff, st-ca25, st-0248, st-4fa1, st-b602, st-1b50), per-review-finding fixed or waived status from the board (`story show` read-only), matrix status from the README matrix and the cited verification reports.
3. Run the five gates one per line and record exit codes and the test count (`uv run pytest -o addopts="-m 'not live'" --co -q` or the summary line).
4. Write docs/handoffs/2026-11-06-milestone-2.md following docs/handoffs/2026-10-29-milestone-1.md: state, verification per matrix row (14 rows), deviations, review findings fixed or waived, ADRs 0008 and 0009 pending Jarrod's review, open stories, follow-ups the board could not do (all seven named in the story), the .DS_Store note.
5. Reconcile README.md with the review: fix the "reruns are safe" sentence (Architecture) and the Limitations section against the merged stories, keep every heading and the matrix rows test_readme.py requires. Run tests/test_readme.py; on failure fix README text, not the test.
6. Run the five gates again after the README edit (the second pass is the one recorded as final). Commit nothing.

## What the checks prove
- The five gates prove the repository is green at handoff; `GITHUB_ACTIONS=true uv run pytest -q` proves the CI-mode path (the st-1731 help-text styling case).
- tests/test_readme.py proves the README edit still matches the design matrix, CLI subcommands, DuckDB queries and public-list policy.
- The live run proves the external contracts (Earth Search, Planetary Computer, DEA) still hold today and feeds the per-row status.
## Orchestrator amendments

These override the text above where they differ.

1. Commit nothing; the orchestrator commits. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**. Never call AWS for the project's own bucket. Never run terraform plan or apply. Judge pytest gates by exit code and never clear addopts for them; for a count use -o addopts="-m 'not live'". Also run GITHUB_ACTIONS=true uv run pytest -q. Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data. Docs are flat factual prose with no em dashes.
2. Batch 1: when several fail rows are covered by one fix, they may share one FILE token (one story per fix, not per row); every fail row still names its token or an existing open story id. A failing item whose fix needs a choice only Jarrod can make (for example which licence the repository carries) is still filed; its description says the choice is Jarrod's and names the options.
3. Batch 1: if a live test fails with a network or timeout error, rerun that test once and record both results; only a failure that repeats is a fail row.
4. Batch 2: README.md edits are in scope only for the reconcile the 2026-11-05 note asks for. The handoff lists the stories filed by the audit with the ids the orchestrator gives in this prompt.

## Implementation Notes

- 2026-10-30T00:54:59.553Z: 2026-10-30: the calibration spike scripts behind LEARNINGS.md 'S2 water calibration' and 'Per-polygon water calibration' exist only untracked, at scratch/spikes/s2_calibrate.py and scratch/spikes/polygon_calibrate.py (copied with their logs from .worktrees/feature/wetland-change-pipeline/scratch/spikes/ so removing that worktree does not lose them). The audit should decide whether to commit them.
- 2026-11-05T08:56:36.821Z: Before the handoff reconcile README.md with docs/research/2026-11-04-milestone-2-review.md. README.md says reruns are safe (Architecture), which review finding 2 contradicts until it is fixed, and its Limitations section predates the review. The handoff must also list which review stories were fixed or waived.
- 2026-11-06T03:46:58.327Z: Audit at docs/research/2026-11-06-reproducibility-audit.md: 28 pass, 11 fail rows, filed as st-2bfd, st-aa46 (licence, Jarrod's choice), st-2bc1, st-73ad, st-5acd, st-eb5a, st-e6f1. Live tests 8 passed, 1 skipped (test_live_public_read, placeholder base_url). Handoff at docs/handoffs/2026-11-06-milestone-2.md; README reconciled with the 2026-11-04 review. Gates pass, 841 passed. Commit b4c12e0.

## Questions
