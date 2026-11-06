# 0008 Exit code for live water check failures

Status: accepted, 2026-11-06, pending Jarrod's review of the epic. Amends the
Consequences of 0006; does not change the 5.0 pp limit or the per-row
`Check.passed`.

## Context

0006 put the wet area clause (absolute gap of 5.0 pp or less) into
`Check.passed` for `water_vs_dea_s2_wo` and left the exit logic of `verify`
unchanged, so `verify` exits 3 if any check fails. Its Consequences state that
on the 6 dates with every polygon measured, the dates with a failing row go
from 2 (agreement alone) to 6 (agreement or clause).

Story st-7047 raised the concern that the daily pipeline job would end red on
most days. It also found that the markdown report and the CLI line showed only
the agreement and its threshold, so a row that failed on wet area alone looked
like a pass with the measured value above the threshold, and the gap was not
shown.

Jarrod directed the orchestrator to proceed without asking and will review the
epic, so this is a measured-rule decision pending his review.

Disclosure: the per-date counts were readable in
`docs/research/2026-11-05-wet-area-gap.csv` when the rule was written, and the
st-9aff section of LEARNINGS.md already gives 2 and 6 for K2 and K1. The rule
and its decision rule are a policy choice recorded in LEARNINGS.md before the
script ran, not a blind test. The tie-break between K2 and K4 was also fixed
before the script ran.

## Decision

One polygon failing the live water check on one scene fails the run only when
it fails agreement. A failure on wet area alone is a `warn` row showing its
gap. The run fails on wet area when the gap pooled over every scored live
water check in the run exceeds 5.0 pp in absolute value. That is a new check,
`water_vs_dea_s2_wo_pooled_wet_area`.

- `Check.passed` stays False for a row that fails the clause. The JSON keeps
  `passed` False with `wet_area_passed` False and gains `n_warned`.
- The markdown table shows status `warn` for such a row, with a note naming
  the polygon, item, signed gap and limit. The CLI prints a `warn` line with
  the same note.
- The matrix rows 'Water extent, live' and End to end take status `warn` when
  the only failures are wet-only ones. `all_passed` stays strict.
- The exit order 3, 6, 4 is unchanged.

The pooled gap is 100 times the sum of pipeline wet counts minus the sum of
WO wet counts, divided by the sum of mutually clear pixels, over the scored
live water checks of the run. The research script recovers each wet count as
round(share * n) from the CSV, and the code does the same from the check
detail, summing integer counts so the 5.0 pp limit is exact.

Share of the 6 measured dates that would exit 3, from
`docs/research/2026-11-06-exit-rule-shares.txt`: 2 of 6 under the chosen
rule, both on agreement (2026-09-17 and 2026-09-12). The pooled gap is below
2.0 pp on every measured date. Under the old rule (K1, 0006 as it stood) it
was 6 of 6.

## Rejected alternatives

- K1, any failure fails the run (0006 as it stands): 6 of 6 measured dates
  fail, 4 more than agreement alone, so the pipeline job ends red on every
  measured date for a clause that fails 9 of 253 rows.
- K2, agreement alone fails the run: it ties K4 at 2 of 6 on the measured
  dates but leaves no wet area condition that can fail a run, so a run-wide
  wet bias against WO would be reduced to warnings.
- K3, a polygon failing the clause on every one of its rows in a date: 4 of 6
  measured dates fail, 2 more than agreement alone, above the pre-registered
  allowance of 1.
- Widening the limit to 10 pp or setting per-polygon limits: this changes the
  fixed limit of 0006 without a calibration.
- Dropping the clause: this loses the design's wet area check.

## Evidence

The rule, the candidates K1 to K4 and the decision rule are pre-registered in
LEARNINGS.md under 'Pre-registered hypotheses (st-7047, 2026-11-06)' Part A.
The decision rule is: B is the number of measured dates that fail under K2; a
candidate is admissible if it fails at most B + 1 dates; choose the admissible
candidate that fails the most dates; ties go to the candidate whose failing
condition includes the other's. The outcome is in LEARNINGS.md under 'Exit rule
for the live water check (2026-11-06)'. From
`docs/research/2026-11-06-exit-rule-shares.txt`, B is 2 and the admissible set
is K2 and K4.

Measured dates failing under K1: 6 of 6
Measured dates failing under K2: 2 of 6
Measured dates failing under K3: 4 of 6
Measured dates failing under K4: 2 of 6
Chosen rule: K4

Rows failing the clause alone: 9 of 253 (0.0356).

Files, with sha256:

- `docs/research/2026-11-06-exit-rule-shares.py` sha256 `61a5b3ef62c86d6e26cfaa31951c43765c11c94c573ca11d4d74004f3d043290`
- `docs/research/2026-11-06-exit-rule-shares.csv` sha256 `963d244ba4d1b3f187ff791c76c0ff2f37664f113591b1266723f29a760dba21`
- `docs/research/2026-11-06-exit-rule-shares.txt` sha256 `77da47c55c36305ea88538bd919260c3c167ae256bfb2a3ee727f8d8d114a386`
- `docs/research/2026-11-06-ramsar-12-gap.py` sha256 `95a0dddeb5cbd7ee63e29091c38efdb3de28fc83bd2190c6c73fb21864824d18`
- `docs/research/2026-11-06-ramsar-12-gap.csv` sha256 `174597ef0d757c62d78ca3ab0a1a308bbbdcb3d8e444b9dca7e7730e774714e4`
- `docs/research/2026-11-06-ramsar-12-gap.txt` sha256 `604db635afb5f674cd5e6a1027d0abcc4d068074839239a6877603c95293126b`
- `docs/research/2026-11-05-wet-area-gap.csv` sha256 `8eda9a0d4d304ad96fcda3f82a66ca52d5a0022d5b73a7ae7e3c4f9006b6506c`

`tests/test_config.py` checks the digests and recomputes the counts and the
chosen rule from the committed CSV.

## Limits

- The sample is 6 dates from one season.
- Pooling dilutes one small polygon's gap. A polygon with a large gap on a
  small area can fail the clause without moving the pooled gap, so the per-row
  `warn` lines carry those gaps and a human has to read them.
- ramsar-12 is 5 of the 9 rows that fail the clause alone, and its over-call
  persists, so it raises no alert under this rule. The ramsar-12 finding
  (LEARNINGS.md, 'ramsar-12 wet area gap (2026-11-06)'): the reproduction
  check passed, and G1, G3, G4 and G5 are supported while G2 is not. The
  global MNDWI threshold of -0.1 over-calls water against WO, the extra wet
  pixels sit on the polygon edge and are mostly SCL class 4 or 5, and the same
  direction shows in 296 of 299 stored rows. Which source is right is
  unknown, because WO is unvalidated.
- Changing ramsar-12's water setting or the limit would be a separate decision
  under 0005 and is not made here.

## Consequences

The pipeline job and `verify.yml` end green when the only failures are wet
area failures on single rows and the pooled gap is within 5.0 pp. `verify`
still exits 3 on agreement failures as before, and now also when the pooled
gap exceeds 5.0 pp. JSON consumers keep `passed` False for the checks that
fail the clause.
