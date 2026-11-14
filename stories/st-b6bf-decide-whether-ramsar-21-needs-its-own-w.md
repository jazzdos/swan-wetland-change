---
id: st-b6bf
title: Decide whether ramsar-21 needs its own water setting after its agreement failure on 2026-11-11
type: spike
priority: P3
complexity: hard
depends_on: []
discovered_from: st-a32a
touches: [LEARNINGS.md, config/pipeline.toml, docs/decisions/0014-ramsar-21-water-setting.md, docs/research/2026-11-12-ramsar-21-confirm.py, tests/test_config.py]
exclusive: false
created: 2026-11-12
updated: 2026-11-14
parked_complexity: hard
---

## Description

GitHub issue #2, the one ramsar water failure. On the 2026-11-11 pass ramsar-21 on tile 50HLJ scored agreement 0.8539 against its agreement_min of 0.91 on 3,299 mutually clear pixels (global setting MNDWI above -0.1). The pipeline calls 0.7051 of those pixels wet and DEA WO calls 0.5608 wet, a gap of +14.43 pp, and SCL class 6 agrees with WO at 0.8369. Under ADR 0008 an agreement failure on a ramsar polygon fails the run, so this row is a legitimate alert and stays one after st-a32a.

Context. ramsar-21 passed agreement on all six measured dates from 2026-09-12 to 2026-10-29 (docs/research/2026-11-05-wet-area-gap.csv). Its NDVI median moved from -0.808 on 2026-10-29 to -0.052 on 2026-11-11, so the polygon is drying, and the over-call against WO appeared as it dried. This is the pattern found for ramsar-12 (LEARNINGS.md 'ramsar-12 wet area gap': the extra wet pixels sit on the polygon edge and are mostly SCL class 4 or 5). The st-2a78 pre-registration notes that the dry end of the season was covered only by seen rows. Evidence file: /Users/jarrodbaker/Documents/swan-wetland-change/scratch/issue-2-repro/verification-20261111-scenes-20261112T032325Z.json (untracked, absolute path).

What this story decides, with the ADR 0005 mechanism and the st-2a78 method: whether ramsar-21 gets a per-polygon override in config/pipeline.toml. The seen row and the six seen dates only nominate candidates. The decision is made on a confirmatory sample of passes not yet seen for ramsar-21, by rules written into LEARNINGS.md before the script exists: a minimum sample (at least 6 confirmatory rows on at least 3 acquisition dates after 2026-11-01, inside DEA's WO retention), the clause (absolute wet gap of 5.0 pp or less at the chosen setting on every confirmatory row), a gain over the global setting, no over-correction, and an agreement_min by the ADR 0005 convention that is at least 0.91. If the minimum sample does not exist yet when the story is planned, park it with the count of passes available and the date by which three are expected, because the drying season has only begun. DEA WO is unvalidated, so the result measures consistency with WO and not accuracy.

No limit is loosened without the confirmatory sample. The outcome is recorded in an ADR as decided by the pre-registered rule under Jarrod's request to complete the outstanding work and not yet approved by Jarrod.

## Acceptance Criteria

- [ ] LEARNINGS.md holds a pre-registration section for this story committed before the research script: disclosure of the seen rows and the candidate settings and the confirmatory sample and the numbered decision rules
- [ ] The confirmatory sample has at least 6 ramsar-21 rows on at least 3 acquisition dates after 2026-11-01 or the story is parked with the count available
- [ ] docs/research holds the script and its CSV and text summary with gap and agreement per row at the global setting and at each candidate and at SCL class 6
- [ ] An override for ramsar-21 is added to config/pipeline.toml only if every pre-registered rule holds and otherwise the global setting stays and the failed rule ids are recorded
- [ ] An ADR records the outcome with evidence files and sha256 values and a status line saying it is not yet approved by Jarrod
- [ ] ruff check and ruff format --check and mypy and pytest all exit 0

## Implementation Plan

## Implementation Notes

## Questions

- 2026-11-14T11:59:54.874Z: The st-b6bf minimum confirmatory sample does not exist yet, so the story parks under its own rule. Facts checked on 2026-11-14 against Earth Search, the DEA STAC and the AOI file:

- ramsar-21 (Peel-Yalgorup System, 59.9 ha) lies only on tile 50HLJ. That gives one row per acquisition date, so the minimum of 6 rows means 6 dates, not 3.
- After 2026-11-01 the catalogue holds three 50HLJ items:
  - 2026-11-01, cloud 42.4 percent, above cloud_cover_max 20, never processed.
  - 2026-11-06, cloud 34.1 percent, above cloud_cover_max 20, never processed.
  - 2026-11-11, cloud 12.1 percent. This is the seen row.
- Eligible confirmatory passes today: 0 rows on 0 dates.
- The next 50HLJ acquisitions are 11-16, 11-18, 11-21, 11-26, 12-01, 12-06 and so on. Last season, 9 of 16 50HLJ acquisition dates from 2025-11-01 to 2025-12-31 were under 20 percent cloud.
- If every pass is clear, three eligible dates arrive by 2026-11-21 and six by 2026-12-01.
- At last season's clear share, three arrive by about 2026-12-06 and six by about 2026-12-26.

In the meantime the daily pipeline scores ramsar-21 against WO on each new pass, commits the verification report (agreement values without polygon ids) and alerts if the pass fails. Which do you want?

(a) Park with nothing committed and re-plan on or after 2026-12-26.
(b) Commit the LEARNINGS.md pre-registration now, while no confirmatory pass exists. It would hold the candidates, rules R1 to R6 and a forward-looking sample: eligible 50HLJ passes from 2026-11-12 to a fixed end date, such as 2026-12-31. Then park the measurement until six eligible passes exist.
