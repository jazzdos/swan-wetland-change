---
id: st-332a
title: Record the st-1433 verify timeout in LEARNINGS.md and ADR 0007
type: chore
priority: P3
depends_on: []
discovered_from: st-1433
touches: [LEARNINGS.md, docs/decisions/0007-spearman-threshold-from-whole-history.md]
exclusive: false
created: 2026-11-16
updated: 2026-11-16
---
## Description

st-1433 (merged as ebea401) raised the step limit of 'Verify the latest daily run' in .github/workflows/verify.yml from 20 to 40 minutes and the job limit from 60 to 75. Two documents still state the old 20 minute limit as current and say verify's S3 read time is unmeasured:

- LEARNINGS.md:1048, the 'Limits' paragraph of 'Spearman threshold calibration (2026-11-06)': "S3 read time is unmeasured, against a 20 minute verify step timeout in `verify.yml`."
- docs/decisions/0007-spearman-threshold-from-whole-history.md:100: "S3 read time is unmeasured because AWS calls were out of scope (epic st-f849). `verify.yml` gives the verify step a 20 minute timeout."

The read time is now measured: verifying pipeline run 43072355326 (2026-11-11, 5 scene-tiles) took 19m34s inside the daily pipeline (10m17s of per-scene raster reads, then 9m17s of run-level checks), and weekly verify run 43791803460 was killed by the 20 minute limit on 2026-11-16 (issue #3).

Both are dated records, so the original sentences stay as written and a dated update follows each one. Out of scope for st-1433, which changed only the workflow and its test. No other document cites the verify step limit (searched README.md, docs/decisions, docs/handoffs, infra/README.md and LEARNINGS.md on 2026-11-16).

## Acceptance Criteria

- [ ] LEARNINGS.md keeps the sentence at line 1048 unchanged and adds a dated 2026-11-16 update right after it that names st-1433 and the 40 minute verify step limit and the 75 minute job limit and the measured 19m34s verify of run 43072355326 and the 20 minute timeout of weekly run 43791803460 (issue #3).
- [ ] docs/decisions/0007-spearman-threshold-from-whole-history.md keeps its line 100 sentence unchanged and adds a dated 2026-11-16 update in the same bullet that gives the same facts.
- [ ] No other line under LEARNINGS.md or docs/ changes.
- [ ] uv run ruff check src tests scripts exits 0.
- [ ] uv run ruff format --check src tests scripts exits 0.
- [ ] uv run mypy src scripts exits 0.
- [ ] uv run pytest -q exits 0.

## Implementation Plan

## Verified facts (worktree /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-332a, HEAD ebea401)

- LEARNINGS.md line 1048 is the last line of the file (ends with a single newline). It reads: "Limits: the threshold is calibrated on the same backfill it then gates. Each verify reads all 1147 files (235,595,220 bytes) and the count grows with each pass. S3 read time is unmeasured, against a 20 minute verify step timeout in `verify.yml`."
- docs/decisions/0007-spearman-threshold-from-whole-history.md lines 99-100 are the bullet "- S3 read time is unmeasured because AWS calls were out of scope (epic st-f849). `verify.yml` gives the verify step a 20 minute timeout." (the bullet wraps; continuation line is indented two spaces). Line 101 starts the next bullet ("- DEA Waterbodies is refetched at each verify...").
- .github/workflows/verify.yml (st-1433, already merged) has the verify step at 40 minutes, job at 75, and a comment citing run 43072355326 (19m34s: 10m17s per-scene reads + 9m17s run-level checks, 5 scene-tiles). The facts in the story match the code.
- LEARNINGS.md already uses the inline convention "Update 2026-11-06: ..." (line 753), so the new text follows it.
- Pinning tests: tests/test_config.py reads ADR 0007's "## Decision" section for `spearman_min = ...` and checks sha256 lines only for research files (not the ADR body); tests/test_ramsar21_preregistration.py and tests/test_waterbody_limit_preregistration.py pin the st-b6bf and st-dd0d sections (lines 314-443, not touched); tests/test_repo_hygiene.py scans LEARNINGS.md for scratch script paths (the new text names none). No test pins the 'Limits' paragraph or the ADR 'S3 read time' bullet. Edits at the end of LEARNINGS.md line 1048 and ADR bullet at line 100 do not touch any pinned section.
- Line 835 of LEARNINGS.md says pipeline.yml sets no step timeout on its verify step; that is about pipeline.yml, not verify.yml, and stays unchanged.

## Steps

1. Edit LEARNINGS.md: leave line 1048's existing sentences byte for byte unchanged and append, on the same line after "`verify.yml`.", a space and the update sentence(s):
   "Update 2026-11-16: st-1433 measured it and raised the limit of the 'Verify the latest daily run' step in `verify.yml` from 20 to 40 minutes and the job limit from 60 to 75 minutes. Verifying pipeline run 43072355326 (2026-11-11, 5 scene-tiles) took 19m34s inside the daily pipeline, 10m17s of per-scene raster reads and then 9m17s of run-level checks. Weekly verify run 43791803460 was killed by the 20 minute step timeout on 2026-11-16 (issue #3)."
   Keep it as one line (this file uses one line per paragraph). No em dashes.
2. Edit docs/decisions/0007-spearman-threshold-from-whole-history.md: keep the two existing lines of the bullet unchanged and add continuation lines (indented two spaces, wrapped near 78 columns like the surrounding bullets) in the same bullet:
   "Update 2026-11-16: st-1433 measured it and raised the verify step limit in `verify.yml` from 20 to 40 minutes and the job limit from 60 to 75 minutes. Verifying pipeline run 43072355326 (2026-11-11, 5 scene-tiles) took 19m34s inside the daily pipeline, 10m17s of per-scene raster reads and then 9m17s of run-level checks. Weekly verify run 43791803460 was killed by the 20 minute step timeout on 2026-11-16 (issue #3)."
   Do not alter the "## Decision" section or any sha256 line.
3. Check the diff: `git diff --stat` shows only LEARNINGS.md and the ADR; `git diff -U0` shows line 1048 changed only by appended text (the original sentence is a prefix of the new line) and ADR line 99-100 intact with added lines after; no other lines under LEARNINGS.md or docs/ change; `grep -c '—'` on the added text is 0.
4. Run the gates in order, one per line, each must exit 0:
   - uv run ruff check src tests scripts
   - uv run ruff format --check src tests scripts
   - uv run mypy src scripts
   - uv run pytest -q
   What the tests prove: test_config.py ADR 0007 tests prove the Decision section and sha256 lines are intact; the two pre-registration tests prove the st-b6bf and st-dd0d sections are unchanged; test_repo_hygiene proves no new scratch path reference was introduced. No new test is added: the change is prose only and the acceptance criteria are checked by the diff inspection in step 3 (the user's instruction to ignore the licence requirement is noted; no data source is added so SOURCES.md is not involved).
5. Commit on the story branch with message "st-332a: Record the st-1433 verify timeout in LEARNINGS.md and ADR 0007" ending with the attribution line Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>.
