---
id: st-da75
title: Measure why Ramsar NDVI rows miss the DEA NBART tolerance and decide the row rule
type: spike
priority: P1
complexity: hard
depends_on: []
discovered_from: st-a32a
touches: [LEARNINGS.md, data/SOURCES.md, docs/decisions/0013-ndvi-row-rule-against-dea-nbart.md, docs/research/2026-11-12-ndvi-nbart-rows.py, tests/test_config.py]
exclusive: false
created: 2026-11-12
updated: 2026-11-12
---

## Description

GitHub issue #2, second cause. After st-a32a limits the live verdict to the ramsar layer, the per-polygon check ndvi_vs_dea_nbart (pipeline NDVI median within 0.05 of the DEA NBART NDVI median) still fails 4 ramsar rows on each of the two passes measured, so verify still exits 3 on every run with scenes.

Rows seen (disclose all eight in the pre-registration). Evidence files are in /Users/jarrodbaker/Documents/swan-wetland-change/scratch/issue-2-repro/ (untracked, absolute path; sha256 in st-a32a and ADR 0012).
- 2026-10-29, DEA maturity final, 31 ramsar rows scored, 4 fail, Pearson 0.9983: ramsar-15 on 50HLJ 0.115 against 0.214 (6,742 px); ramsar-20 on 50HLJ -0.670 against -0.578 (1,942 px); ramsar-21 on 50HLJ -0.808 against -0.657 (5,976 px); ramsar-27 on 50HLK -0.545 against -0.431 (641,110 px). The pipeline is lower than DEA on all four.
- 2026-11-11, DEA maturity nrt, 42 ramsar rows scored, 4 fail, Pearson 0.9921: ramsar-13 on 50HLK 0.422 against 0.348 and on 50HLJ 0.449 against 0.348 (228 px each; the two tiles' stored medians differ by 0.027 for the same polygon and day); ramsar-20 on 50HLJ -0.226 against -0.156 (1,732 px); ramsar-21 on 50HLJ -0.052 against 0.007 (3,756 px).
- On the 2026-10-29 waterbody rows the largest polygons fail most (21 of 31 at 10,000 px and over, median absolute difference 0.141) and the failing rows have a median pipeline NDVI of +0.021 against +0.134 for DEA.

What is known about the tolerance. The 0.05 figure comes from the design matrix (line 228). It was checked live on one polygon only: Thomsons Lake on 2026-10-30 (difference about 0.003) and on 2026-11-06 (0.4749 against 0.4715 on 63,600 px). No exit rule was ever measured for NDVI the way ADR 0008 did for water.

Working explanation, to be tested and not assumed. NDVI is ill-conditioned at low reflectance: for a per-band reflectance difference e the worst-case NDVI change is 2e / (red + nir), so over open water, where red + nir is a few percent, a difference of 0.005 between the ESA Sen2Cor reflectance and the DEA NBART reflectance moves NDVI by more than 0.05 with correct pipeline arithmetic. Six of the eight failing rows have negative or near-zero NDVI. The two ramsar-13 rows do not fit: bright vegetation, 228 px, seen only against an nrt reference. Mask differences between the stored pipeline median and the compared pixels are a second candidate for ramsar-13.

What this story produces. A measured answer and a decided rule, in the pattern of st-7047 and st-2a78: (1) a pre-registration section in LEARNINGS.md written before the script exists, with the disclosure above, hypotheses on the mechanism, the candidate row rules, numeric adoption criteria and the reading rule; (2) one research script under docs/research that re-reads red and nir for the pipeline and for DEA NBART with the same window, masks and scaling as ndvi_scene_check, checks first that it reproduces the eight seen rows, and records per row the two NDVI medians, the per-band reflectance medians of both sources, red + nir, pixel count, DEA maturity and tile; (3) results in LEARNINGS.md 'Spike results'; (4) ADR 0013 with the outcome, status decided by the pre-registered rule under Jarrod's request to complete the outstanding work and not yet approved by Jarrod; (5) if a rule is adopted, a follow-up story for the code change filed with story create --discovered-from this story, depending on st-a32a. No file under src changes in this story.

Samples. Nomination sample: the two seen passes, used only to fix the parameters of the candidates. Confirmatory sample: ramsar rows of passes never scored against DEA NBART, namely the passes of 2026-09-12, 2026-09-17, 2026-10-02, 2026-10-12 and 2026-10-27 and, for season cover, the newest pass with cloud cover at most 20 in each of January, April and July 2026 taken from the pipeline's own discover. The sample is fixed before any read and not widened afterwards. The script runs once on the confirmatory sample. Dropped rows are listed, not substituted.

Constraints on every candidate rule, fixed here and not open to the planner:
- No ramsar row becomes unscored. A row taken out of the 0.05 NDVI comparison must be scored by another blocking comparison against the same DEA NBART item, for example per-band reflectance medians within a fixed absolute limit.
- The 0.05 tolerance and the 0.95 correlation limit keep their values wherever the rule keeps the NDVI comparison. Widening 0.05 is not a candidate.
- Every parameter is fixed from the nomination sample before the confirmatory sample is read.
- The adoption criteria are numeric and say what share of well-conditioned rows must pass 0.05 and what share of failing rows the mechanism must explain. If they are not met, no rule is adopted, the status quo stays, and the story is parked with the measured rates.
- The status quo (every failing row fails the run) is always one of the candidates and its failing share of measured passes is reported next to the others.
- DEA maturity is recorded per row. nrt references cannot be re-read for old passes, so the result states that the confirmatory sample is final maturity and that daily runs score against nrt, and it re-scores the 2026-11-11 rows against whatever maturity DEA holds on the day the script runs.
- DEA NBART is another processing of the same Sentinel-2 acquisition and is not ground truth. The result measures consistency, as ADR 0005 says of WO.

This story also adds the LEARNINGS.md 'Live run findings' entry for issue #2 (the layer finding of st-a32a with a pointer to ADR 0012, and the NDVI finding), because st-a32a does not edit LEARNINGS.md.

Every dataset first used here gets its data/SOURCES.md row in the same commit. Only collection sentinel-2-c1-l2a. Reflectance from raster:bands scale and offset, never a constant.

## Acceptance Criteria

- [ ] LEARNINGS.md holds a pre-registration section for this story committed before the research script: disclosure of the eight seen rows and the mechanism hypotheses and the candidate row rules and numeric adoption criteria and the fixed confirmatory sample
- [ ] The research script reproduces the eight seen rows before it reads the confirmatory sample and stops with a recorded message if it cannot
- [ ] docs/research holds the script and its CSV and text summary with one row per polygon and scene giving both NDVI medians and the per-band reflectance medians of both sources and red plus nir and pixel count and DEA maturity
- [ ] The confirmatory sample holds the five named 2026 passes and one pass from each of January and April and July 2026 and every dropped row is listed with its reason
- [ ] Every candidate rule keeps each ramsar row under a blocking comparison against DEA NBART and keeps 0.05 and 0.95 unchanged where it keeps the NDVI comparison
- [ ] LEARNINGS.md Spike results states for each candidate the share of measured passes that would exit 3 and whether each adoption criterion held and the rule chosen or that none was adopted
- [ ] docs/decisions/0013 records the outcome with its evidence files and sha256 values and a status line saying it is not yet approved by Jarrod
- [ ] If a rule is adopted a follow-up story for the code change exists on the board depending on st-a32a and if none is adopted this story is parked with the measured rates
- [ ] LEARNINGS.md Live run findings holds the issue #2 entry naming run 43072355326 and the layer finding with a pointer to ADR 0012 and the NDVI finding
- [ ] No file under src is changed by this story
- [ ] ruff check and ruff format --check and mypy and pytest all exit 0

## Implementation Plan

## Implementation Notes

## Questions
