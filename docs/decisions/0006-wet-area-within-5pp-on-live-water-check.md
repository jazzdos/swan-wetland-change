# 0006 Wet area within 5 pp on the live water check

Status: accepted, 2026-11-05. Amends the Water extent, live row of the
design; does not change the agreement floors of 0005.

The exit-code consequences below are amended by 0008: a check that fails
on wet area alone is a warning and does not change the exit code; the run
fails on wet area when the gap pooled over every scored live water check
in the run exceeds 5.0 pp. 0012 further narrows that pooled population to
the ramsar rows only.

## Context

The design (`docs/plans/2026-10-29-swan-wetland-change-design.md`, line 226)
asks the live water check against DEA `ga_s2_wo_provisional_3` for pixel
agreement at or above a floor and wet area within 5 pp. `water_vs_dea_s2_wo`
(`src/wetland_change/verify/wo.py`) scored agreement only, and no design
document, decision or handoff recorded a reason for dropping the clause.

Over the n mutually clear pixels, let a be the pipeline-wet-only count and b
the WO-wet-only count. The wet-share gap is (a - b) / n and the
disagreement is (a + b) / n, which is 1 minus agreement. So the absolute gap
is at most 1 minus agreement. At the design's 0.95 floor the clause was
implied: the gap could not exceed 5 pp.

0005 lowered the floors per polygon. The largest possible gap at each floor
is now:

| polygon | agreement_min | max possible gap |
|---|---|---|
| every other polygon | 0.91 | 9 pp |
| ramsar-28 | 0.92 | 8 pp |
| ramsar-15 | 0.94 | 6 pp |
| ramsar-56 | 0.95 | 5 pp |

The clause therefore binds for the default setting, ramsar-28 and ramsar-15,
and stays implied for ramsar-56.

## Decision

`water_vs_dea_s2_wo` scores the clause. For a polygon on one pass, the
pipeline wet share and the WO wet share are each the share of mutually clear
pixels that are wet, where mutually clear means the pipeline pixel is clear
and the WO flag byte has no bit below 128 set (the clear rule of
`wo_agreement`). The gap is 100 times (pipeline share minus WO share), in
percentage points, and its sign is stored: positive means the pipeline is
wetter than WO. The clause is checked per pass and per polygon, as
agreement is.

The limit is 5.0 pp, the design's value. It is fixed, not calibrated.
`Check.passed` needs both agreement at or above the polygon's agreement_min
and an absolute gap of 5.0 pp or less. `Check.measured` stays the agreement
and `Check.threshold` stays the polygon's agreement_min. The detail records
`wet_area_pipeline`, `wet_area_wo`, `wet_area_diff_pp` (signed),
`wet_area_max_pp` and `wet_area_passed`. The pooled agreement used to derive
agreement_min in 0005 and the live test of agreement are unaffected.

Evidence: the hypotheses were pre-registered in LEARNINGS.md before any
wet-area measurement. H1: at least 90 percent of the rows that pass
agreement have an absolute gap of 5 pp or less. H2: the same for the
ramsar-28 rows alone. The rule was that if both held the clause would go
into `Check.passed`, and if either failed the story would be parked. H1
held at 242 of 251 rows (0.9641). H2 held at 21 of 22 ramsar-28 rows
(0.9545). The decision rule therefore put the clause in `Check.passed`.
Rows: `docs/research/2026-11-05-wet-area-gap.csv` (sha256
8eda9a0d4d304ad96fcda3f82a66ca52d5a0022d5b73a7ae7e3c4f9006b6506c).

## Limits

The sample is 253 rows, from 6 dates of one season for most polygons.
ramsar-28 has 12 dates. H1 and H2 count rows. They did not test the
run-level result, which is in Consequences.

124 of the 253 rows are dry in both sources and pass the clause trivially.
Of the 104 rows that pass agreement with at least 1 percent wet in either
source, 95 are within 5 pp, a rate of 0.9135.

DEA S2 WO is itself unvalidated, so the clause measures consistency with DEA,
not accuracy. Wet area is taken over mutually clear pixels, not over the
whole polygon.

## Consequences

`verify` exits 3 if any check fails, and the pipeline job then ends red. On
the 6 dates with every polygon measured, the dates with a failing row go
from 2 to 6 with the clause (LEARNINGS.md, "Wet area clause (2026-11-05)").
A daily run holding all of one of those dates' scenes would exit 3 on 2 of 6
dates before the clause and on 6 of 6 with it.

ramsar-12 is 5 of the 9 rows that fail only the clause. The pipeline is
wetter than WO on both tiles on all 6 dates. The cause was not investigated.

This ADR does not change how `verify` turns failed checks into an exit code.

A pass that fails on wet area alone has `passed` false and
`wet_area_passed` false in the detail of the JSON report. The markdown
report table and the CLI line show only the measured agreement and its
threshold, so that failure appears with the measured value above the
threshold.
