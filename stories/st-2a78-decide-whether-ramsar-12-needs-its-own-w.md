---
id: st-2a78
title: Decide whether ramsar-12 needs its own water setting
type: task
priority: P3
depends_on: []
discovered_from: st-7047
touches: [LEARNINGS.md, README.md, config/pipeline.toml, data/SOURCES.md, docs/decisions/0010-ramsar-12-water-setting.md, docs/research/2026-11-06-ramsar-12-confirm.csv, docs/research/2026-11-06-ramsar-12-confirm.py, docs/research/2026-11-06-ramsar-12-confirm.txt, tests/test_config.py, tests/test_ramsar12_decision.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

st-7047 (docs/research/2026-11-06-ramsar-12-gap.txt, LEARNINGS.md 'ramsar-12 wet area gap (2026-11-06)') found the global MNDWI -0.1 setting over-calls water on ramsar-12 (Peel-Yalgorup) against DEA WO: G1 supported (thresholds -0.05 to +0.15 keep abs gap <= 5 pp on all 12 measured rows, lowest mean abs gap at +0.05), G3 edge ring over-represented in pipeline-only wet pixels, G4 67 percent of those pixels are SCL class 4 or 5, G5 water_ha_index above water_ha_scl on 296 of 299 stored rows. Changing a polygon's water setting is an ADR 0005 calibration decision, out of scope for st-7047, which only decided the exit code.

## Acceptance Criteria

- [ ] A pre-registered rule for choosing ramsar-12's setting is in LEARNINGS.md before any measurement
- [ ] An ADR records the chosen setting (or the decision to keep the global one) with sha256-pinned evidence and a test in tests/test_config.py
- [ ] If a per-polygon override is added
- [ ] config/pipeline.toml carries it and the gates pass

## Implementation Plan

# st-2a78 plan: choose ramsar-12's water setting by a pre-registered, blind rule

Worktree: /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-2a78 (branch as checked out there). All paths below are relative to it.

## Verified facts (checked against the worktree at 4123d51)

- No prerequisite is missing. `docs/research/2026-11-06-ramsar-12-gap.{py,csv,txt}` and the LEARNINGS.md section 'ramsar-12 wet area gap (2026-11-06)' exist. ADR 0009 is the newest ADR, so the next number is 0010.
- `config/pipeline.toml` has overrides for ramsar-15, ramsar-28 and ramsar-56 only. `tests/test_config.py::test_repo_config_water_overrides_match_learnings` asserts that exact set and must change if ramsar-12 is added.
- The 12 seen rows are ramsar-12 on 6 dates (2026-09-12, 09-17, 10-02, 10-12, 10-27, 10-29), tiles 50HLJ and 50HLK. They are the 6 newest dates of `docs/research/2026-11-05-wet-area-gap.csv`. No gap value exists anywhere in the repo for earlier dates.
- `docs/research/2026-11-06-wo-availability.csv` (Earth Search item list, no gap data) shows ramsar-12 tile scenes with cloud cover at most 20 on 2026-08-23 (HLK only), 08-28, 08-30 and 09-07 (both tiles), all with a DEA WO item. These dates are not among the 12, are inside the DEA WO provisional retention (about 3 months, so to roughly 2026-11-15 for 08-15), and are the confirmatory sample. About 7 scene-tiles on 4 dates are expected, plus any scene from 2026-11-01 to 11-05 that the live search finds. Caveat: they are wetter-season dates; the dry end of the season is covered only by the seen rows.
- Reusable code: `docs/research/2026-11-06-ramsar-12-gap.py` (`measure`, `find_scenes`, `disagreement_counts`, `GapRow`), `wetland_change.catalogue.search.discover(..., datetime_range=...)`, `wetland_change.stats.water_pixels`, `wetland_change.verify.wo.{find_wo_href,dea_reader,WO_EXCLUDE,WO_WET}`. The AOI GeoJSON is absent in the worktree; use `/Users/jarrodbaker/Documents/swan-wetland-change-data/aoi/dbca_010_ramsar_sites.geojson` as read-only input via `--ramsar`.
- Existing patterns to copy: ADR 0008 and 0009 (sha256 lines, 'Decision-making' and 'Disclosure' paragraphs) and the tests `test_adr_0009_*` in `tests/test_config.py` (SHA_LINE regex, importlib loader, recomputation from committed CSV).

## Approach: how the already-seen 12 rows are handled

The 12 rows nominate the candidate thresholds but never decide. The decision uses only a confirmatory sample of ramsar-12 scene-tiles on dates not among the 12, inside the DEA WO provisional window, measured once after the rule and the script are committed. The rule is written into LEARNINGS.md and committed before any raster is read, and the pre-registration commit hash is quoted in the ADR. The LEARNINGS text and ADR disclose that (a) the 12 rows were seen, (b) the planner saw the confirmatory item list (not gap values), (c) confirmatory dates are Aug to Sep, wetter season, and (d) WO is unvalidated, so the rule measures consistency with WO as in ADR 0005.

Pre-registered rule (full text goes in LEARNINGS.md):

- Candidates C = MNDWI above t for t in {0.00, +0.05, +0.10}, the three grid values around the seen-data optimum (+0.05, mean abs gap 0.512 pp). -0.05 and +0.15 are excluded (2.98 and 3.07 pp on the seen rows). Baseline is the global -0.10. scl6 is reported for context only (G2 was not supported).
- Confirmatory sample: Earth Search `sentinel-2-c1-l2a` items found by the pipeline's own `discover` with acquisition date 2026-08-15 to 2026-11-05 inclusive, cloud cover at most 20 (config), whose window intersects ramsar-12 (`plan_window` not None), not on any of the 6 seen dates, with a DEA WO item per `find_wo_href`, and at least 100 mutually clear pixels (verify.min_clear_pixels). Same window, clear mask, inside mask and WO clear rule as `wo_check`. Window and exclusions are fixed and are not widened after seeing results.
- Per row: a = pipeline wet and WO dry, b = WO wet and pipeline dry, n = mutually clear, gap_pp = 100(a-b)/n, agreement = 1-(a+b)/n.
- Selection: T = the candidate with the lowest mean absolute gap over confirmatory rows; ties go to the one closest to +0.05, then the lower.
- Adopt a per-polygon override at T only if all hold (otherwise keep the global setting, and the failed condition ids are recorded):
  - R1 sample: at least 6 confirmatory rows on at least 3 distinct dates (otherwise 'inconclusive', which keeps global).
  - R2 clause: absolute gap at most 5.0 pp on every confirmatory row at T.
  - R3 gain: pooled agreement at T minus pooled agreement at -0.10, over confirmatory rows, is at least 0.005.
  - R4 consistency: agreement at T exceeds agreement at -0.10 on at least 2/3 of confirmatory rows.
  - R5 no over-correction: absolute mean signed gap at T over confirmatory rows at most 2.0 pp.
  - R6 floor: agreement_min = floor to 0.01 of (pooled agreement at T over all rows, the 12 seen plus confirmatory, minus 0.02), the ADR 0005 convention, computed exactly with `fractions.Fraction`; adopt only if it is at least 0.91.
- Override form: `[water.overrides.ramsar-12]` method = "mndwi", threshold = T, agreement_min as computed.

## Steps

1. Batch 1, task A. LEARNINGS.md: add `## Pre-registered hypotheses (st-2a78, 2026-11-06)` after the st-5f74 pre-registration block (before `## Spike results`), holding the rule, disclosure and context above. Commit it alone before anything else runs. Proves: order of events is in git history.
2. Batch 1, task B (TDD). `docs/research/2026-11-06-ramsar-12-confirm.py` with pure `load_rows`, `select_threshold`, `agreement_floor`, `decide` (returns outcome 'override' or 'keep-global', threshold, agreement_min, list of failed condition ids R1 to R6) and a live `main` using the pre-registered window. Unit tests in `tests/test_ramsar12_decision.py` on synthetic rows prove each of R1 to R6 can fail alone, tie-breaking, exact floor arithmetic (for example pooled 0.9632 gives 0.94, pooled 0.9600 gives 0.94, 0.9599 gives 0.93) and that seen dates are excluded. No raster is read. Commit.
3. Batch 2, task C. Run the script once live (anonymous reads of Earth Search and DEA), write `docs/research/2026-11-06-ramsar-12-confirm.csv` and `.txt`, add a LEARNINGS.md result section 'ramsar-12 setting confirmation (2026-11-06)' quoting the rule outcome and numbers. Do not rerun with changed parameters. Commit.
4. Batch 2, task D (TDD). Write failing tests first in `tests/test_config.py`: ADR 0010 sha256 lines match the committed research files; ADR counts and chosen outcome equal recomputation by the script's `decide` from the committed CSVs; the repo config for ramsar-12 equals the ADR's `Chosen outcome`, `threshold` and `agreement_min` lines (override present, or absent for keep-global); the overrides-set test updated. Then write `docs/decisions/0010-ramsar-12-water-setting.md` (status 'decided under delegation by the orchestrator, 2026-11-06; pending Jarrod's review', amends 0005 if override added, lists sha256 for the script, csv and txt, the pre-registration commit hash, disclosure, limits, consequences: stored rows keep their old setting, no rewrite, mixed baselines per ADR 0005). Then edit `config/pipeline.toml` if outcome is override, update README (rows at lines ~43 and ~165, known-gaps bullet at ~404 replacing 'st-2a78, open'), add a `data/SOURCES.md` row for the confirmatory read, run all gates, commit.

## What the tests prove

- tests/test_ramsar12_decision.py: the pre-registered rule is implemented as written, including exact-fraction rounding and each failure mode.
- tests/test_config.py (new): the ADR evidence digests are not stale, the ADR's stated outcome is what the rule yields on the committed CSV, and `config/pipeline.toml` carries exactly the setting the ADR records. The existing config tests still pass with the updated overrides set.

## Gates

uv run ruff check src tests scripts; uv run ruff format --check src tests scripts; uv run mypy src scripts; uv run pytest -q; GITHUB_ACTIONS=true uv run pytest -q.
Constraints: never touch AWS for the project's own bucket, never run terraform plan or apply, never run compaction against S3, never write under /Users/jarrodbaker/Documents/swan-wetland-change-data and never point verify_run there.
## Orchestrator amendments

These override the text above where they differ.

1. Agents commit nothing; the orchestrator commits. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**. Never call AWS for the project's own bucket, never run terraform plan or apply, never run compaction against S3. Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data (reading the AOI file there is fine) and never point verify_run there. Judge pytest gates by exit code and never clear addopts for them; for a count use -o addopts="-m 'not live'". Docs are flat factual prose with no em dashes.
2. The work runs as two build-flow runs. Run 1 is batch 1 (b1-a and b1-b). Wherever a batch-1 prompt says "commit", leave the change uncommitted instead: after run 1 the orchestrator commits b1-a's LEARNINGS.md change alone as the pre-registration commit, then b1-b's script and tests as a second commit, before any measurement. Batch 1 must not run the script's live main, read any raster, or compute any gap value. Unit tests use synthetic rows and never touch the network.
3. Run 2 is batch 2 (b2-c and b2-d). The orchestrator passes the pre-registration commit hash and the script commit hash in the run-2 prompt; the ADR quotes them. The live measurement runs once; parameters, window and exclusions are not changed after results are seen. If the live run fails on a network error, rerun once and record both attempts.
4. The ADR status line reads: decided under delegation by the orchestrator on 2026-11-06, pending Jarrod's review.
5. The first CSV column is `item_id` in both the seen CSV and the confirmatory CSV; where b1-b's write_rows says `id`, write `item_id`.

## Implementation Notes

- 2026-11-06T05:29:06.040Z: Pre-registered the rule (959d15a) and committed the confirmatory script and tests (ca8742e) before any measurement. One live run, 05:08 to 05:09 UTC 2026-11-06, first attempt: 7 confirmatory scene-tiles on 4 dates, 12 dropped for falling on seen dates. Outcome keep-global: R1 and R6 pass, R2 to R5 fail. On the late-August and early-September confirmatory dates the global MNDWI -0.10 under-calls water against DEA WO (gaps -4.1 to +2.5 pp), and every higher candidate widens the gap, so the over-call seen in Sep to Oct is seasonal, not a fixed offset. Measurement committed as c208886; ADR 0010 (decided under delegation, pending Jarrod's review), config comment, five tests, README and SOURCES row as 22f862c. No override added. Gates: 878 passed.

## Questions
