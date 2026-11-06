# 0010 ramsar-12 water setting

Status: decided under delegation by the orchestrator, 2026-11-06; approved by Jarrod on 2026-11-06.
Applies 0005; changes no setting.

## Context

st-7047 found that ramsar-12 (Peel-Yalgorup System, about 100.7 ha) reads
wetter than DEA Sentinel-2 Water Observations (WO) at the global setting
(MNDWI above -0.1, agreement_min 0.91). On its 12 seen rows (6 dates from
2026-09-12 to 2026-10-29, tiles 50HLJ and 50HLK) the pipeline is wetter than WO
on every row, by +3.12 to +6.82 pp. Those rows are 5 of the 9 rows that fail
only the 5 pp wet area clause of 0006. Under 0008 a row that fails only the
clause is a warning, not a failure, so these rows warn and do not turn
`verify` red. Of the hypotheses in LEARNINGS.md 'Pre-registered hypotheses
(st-7047, 2026-11-06)' Part B, G1 (a higher threshold fits), G3 (the over-call
sits on the polygon edge), G4 (the extra wet pixels are SCL class 4 or 5) and
G5 (the same direction in the stored history) were supported, and G2 (scl6)
was not. G1 showed that any MNDWI threshold from -0.05 to +0.15 keeps the
absolute gap at 5 pp or less on all 12 seen rows. Whether to give ramsar-12 an
override under 0005 was left open (st-2a78).

## Decision-making

This decision was made by the orchestrator under Jarrod's delegation of it,
using the rule pre-registered in LEARNINGS.md ('Pre-registered hypotheses
(st-2a78, 2026-11-06)') before the measurement ran. The pre-registration was
committed as 959d15a and the script and its decision tests as ca8742e, both
before the measurement. Jarrod reviewed and approved it on 2026-11-06.

Disclosure:

- The 12 seen rows were not a blind test. They nominated the candidates
  (MNDWI above 0.00, +0.05 and +0.10) and supplied the seen-row counts for the
  agreement_min floor in R6. They were not used to decide anything else.
- The planner read the Earth Search item list in
  `docs/research/2026-11-06-wo-availability.csv` before writing the rule, so it
  expected about 7 scene-tiles on 4 dates in August and September. It saw no
  gap value for any of them.
- The confirmatory dates (2026-08-23 to 2026-09-07) are in the wetter season.
  The dry end of the season is covered only by the seen rows.

## Decision

Chosen outcome: keep-global

ramsar-12 stays on the global setting (MNDWI above -0.1, agreement_min 0.91).
No `[water.overrides.ramsar-12]` table is added to `config/pipeline.toml`. The
rule required R1 to R6 to hold together. R1 and R6 held; R2, R3, R4 and R5
failed. The outcome is not inconclusive.

The confirmatory sample is 7 scene-tiles on 4 dates (2026-08-23 on 50HLK only;
2026-08-28, 2026-08-30 and 2026-09-07 on both tiles). Selected candidate: MNDWI
above 0.00, the one with the lowest mean absolute gap. +0.05 was not selected.

| threshold | pooled agreement, 7 confirmatory rows | pooled agreement, all 19 rows | mean abs gap (confirm) | mean signed gap (confirm) |
|---|---|---|---|---|
| -0.10 (global) | 0.9495 | 0.9459 | 1.942 pp | -0.544 pp |
| 0.00 | 0.9474 | 0.9575 | 2.998 pp | -2.926 pp |
| +0.05 | 0.9440 | 0.9559 | 4.073 pp | -4.073 pp |
| +0.10 | 0.9365 | 0.9502 | 5.227 pp | -5.227 pp |

The all-rows column pools the 12 seen and 7 confirmatory rows. The pipeline is
drier than WO on 5 of the 7 confirmatory rows at the global setting (gap
-4.107 to -0.261 pp) and wetter on the 2 rows of 2026-09-07 (+2.466 and
+2.426 pp). The seen rows were wetter than WO on all 12. Every raised
threshold makes the confirmatory rows drier than WO.

## Evidence

The rule, candidates and sample are in LEARNINGS.md under 'Pre-registered
hypotheses (st-2a78, 2026-11-06)'. The result is under 'ramsar-12 setting
confirmation (2026-11-06)'. The script ran once live on 2026-11-06 (05:08 to
05:09 UTC) against Earth Search and DEA, exited 0 on the first attempt and was
not rerun. Discovery returned 19 scene-tiles in the window; 12 were dropped
because they fell on a seen date, and none for a missing WO item, a differing
grid or fewer than 100 mutually clear pixels.

Files, with sha256:

- `docs/research/2026-11-06-ramsar-12-confirm.py` sha256 `6bba1a06ad235f4ce31b679611d240a02c37bee50a125b99abb5bb9d82292586`
- `docs/research/2026-11-06-ramsar-12-confirm.csv` sha256 `699fa1518087b0d321ab78fe4b7350a7866ff7e61ffa4d662e77c76bd57d4516`
- `docs/research/2026-11-06-ramsar-12-confirm.txt` sha256 `db1df531754a5b33a6dc089a604d154227848cadeb6d35eeb48166e246688bcd`

Seen-row input to the decision:

- `docs/research/2026-11-06-ramsar-12-gap.csv` sha256 `174597ef0d757c62d78ca3ab0a1a308bbbdcb3d8e444b9dca7e7730e774714e4`

Conditions at the selected candidate (MNDWI above 0.00):

- R1, sample: pass. 7 rows on 4 dates, need at least 6 rows on at least 3 dates.
- R2, clause: fail. Maximum absolute gap 6.465 pp (2026-08-23, 50HLK), need 5.0
  or less.
- R3, gain: fail. Pooled agreement 0.9474 minus 0.9495 at -0.10 is -0.0020, need
  at least 0.005.
- R4, consistency: fail. Agreement at 0.00 exceeds agreement at -0.10 on 2 of 7
  rows (0.2857), need at least 0.6667.
- R5, no over-correction: fail. Mean signed gap -2.926 pp, need an absolute
  value of 2.0 or less.
- R6, floor: pass. agreement_min would be 0.93 over the 19 rows, need at least
  0.91. 1 of the 19 rows is below 0.93.

Failed: R2, R3, R4, R5.

## Rejected alternatives

- Override at the selected 0.00. It fails four of six conditions on the
  confirmatory rows and makes them drier than WO (mean -2.926 pp).
- Override at +0.05, the seen-data optimum (mean absolute gap 0.512 pp on the 12
  seen rows). On the confirmatory rows it has a mean signed gap of -4.073 pp
  and 3 of 7 rows beyond 5 pp. Seen-row fit did not carry over.
- Override at +0.10, which has a mean absolute gap of 5.227 pp on the
  confirmatory rows.
- scl6, which G2 rejected on the seen rows (7 of 12 within 5 pp, pooled
  agreement 0.8998) and which is worse on the confirmatory rows (pooled
  agreement 0.8636, mean gap -8.850 pp).
- Thresholds -0.05 and +0.15, which were not in the candidate set because their
  seen mean absolute gaps (2.977 and 3.065 pp) are about six times the optimum.
- A wider clause limit. 0006 sets 5 pp and 0008 already makes a clause-only
  failure a warning, so widening the limit would hide a gap that the data show
  changing sign.

## Limits

- The rule measures consistency with DEA S2 WO, which is unvalidated, not
  accuracy. Neither source is shown to be right for ramsar-12.
- The confirmatory sample is small: 7 rows on 4 dates, and the 2 tiles of one
  date are not independent.
- The confirmatory dates are wetter-season dates (2026-08-23 to 2026-09-07).
  The dry end of the season rests on the seen rows and is not confirmed.
- The gap changes sign between the August to early September rows and the
  September to October rows. No test here separates a seasonal effect from a
  scene effect.
- G3 and G4 suggest the over-call at -0.10 concentrates on the polygon edge
  and in SCL class 4 and 5 pixels. A threshold change is a blunt fix for that,
  and the confirmatory rows show it trading a wet bias for a dry one.

## Consequences

No setting changes, so no stored observation row changes. ramsar-12 rows keep
the setting they were written with, nothing is written to S3 or the backfill
data, and a change baseline is not affected. The clause-only warn rows for
ramsar-12 persist under 0008: they are shown with their gap and do not change
the `verify` exit code. On the next live verify, ramsar-12 is scored with the
global setting and agreement_min 0.91 as before. If a later study finds a
setting that holds on both the dry and wetter seasons, it would amend 0005 and
rows written before that change would mix settings until recomputed, as in
0005.

`tests/test_config.py` checks the digests above and recomputes the outcome from
the committed CSV files.
