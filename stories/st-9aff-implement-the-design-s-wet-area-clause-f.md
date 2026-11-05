---
id: st-9aff
title: Implement the design's wet area clause for live water or record why it was dropped
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [LEARNINGS.md, README.md, docs/decisions/0006-wet-area-within-5pp-on-live-water-check.md, docs/research/2026-11-05-wet-area-gap.csv, docs/research/2026-11-05-wet-area-measure.py, docs/research/2026-11-05-wet-area-summary.txt, src/wetland_change/verify/wo.py, tests/test_verify.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

The design's Water extent live row (line 226) requires pixel agreement and wet area within 5 pp. src/wetland_change/verify/wo.py checks only pixel agreement, and no decision or handoff records why. README.md lists this as not implemented. Found while checking the st-06a8 README, not by the review.

## Acceptance Criteria

- [ ] The live water check scores wet area within 5 pp or an ADR records why the clause was dropped
- [ ] The README verification matrix row matches the outcome

## Implementation Plan

## Decision

Implement the clause (do not drop it). Reasons found in the worktree:

- Design line 226 requires "pixel agreement at or above 0.95 on mutually clear pixels; wet area within 5 pp". `wo_check` in `src/wetland_change/verify/wo.py` scores only agreement; README row "Water extent, live" (README.md line 137) says the clause is not implemented and nothing records why.
- Arithmetic: over the mutually clear pixels, wet-share difference = (pipeline-wet-only minus WO-wet-only)/n, and disagreement = (pipeline-wet-only plus WO-wet-only)/n, so |wet area difference| <= 1 - agreement. At the design's 0.95 floor the 5 pp clause was therefore implied. ADR 0005 lowered the floors to 0.91 (default), 0.92 (ramsar-28), 0.94 (ramsar-15) and 0.95 (ramsar-56). For the first three, a pass can now have agreement above its floor and a wet-area gap above 5 pp (up to 9, 8 and 6 pp), so the clause is a real extra constraint, not redundant, and dropping it would need a justification that does not exist.
- Measured before building, under hypotheses pre-registered in `LEARNINGS.md` (c13208a). Result in `LEARNINGS.md`, "Wet area clause (2026-11-05)", and `docs/research/2026-11-05-wet-area-gap.csv` (sha256 8eda9a0d4d304ad96fcda3f82a66ca52d5a0022d5b73a7ae7e3c4f9006b6506c). H1 held at 242 of 251 (0.9641) and H2 at 21 of 22 (0.9545), so the rule puts the clause in `Check.passed`. Recorded with it: on the 6 dates with every polygon measured, dates with a failing row go from 2 to 6. The build does not change verify's exit logic; that decision is filed separately. No live calls in the build.

Scope is `src/wetland_change/verify/wo.py`, `tests/test_verify.py`, a new `docs/decisions/0006-*.md`, and the README matrix row. No config change (constant in wo.py), no edit to `stories/**`, no commit, no AWS or terraform, no live calls in the default suite.

## Definition (exact)

Wet area = share of mutually clear pixels (pipeline clear AND WO value with no flag bit below 128) that are wet, computed for the pipeline (its polygon setting) and for DEA WO (bit 128). `wet_area_diff_pp = 100 * (pipeline_share - wo_share)` (signed). Gate: `abs(wet_area_diff_pp) <= WET_AREA_MAX_PP` with `WET_AREA_MAX_PP = 5.0`. `Check.passed = agreement >= agreement_min AND wet area within 5 pp`; `Check.measured` stays the agreement and `Check.threshold` stays agreement_min (pooled_agreement and the live test keep working). New detail keys on the scored check: `wet_area_pipeline`, `wet_area_wo`, `wet_area_diff_pp`, `wet_area_max_pp`, `wet_area_passed`. The "grid differs" and "nothing mutually clear" branches get no wet-area keys / `passed=None` as today.

## Conflict note: parked branch story/st-b602

It edits the same `wo_check` (adds `min_clear_pixels: int = 1` and a reason-skip block `if 0 < n < min_clear_pixels:` between `scl_agreement` and the final `return Check(...)`) and the same README row (appends a sentence about the skip). To merge cleanly: add new code only as (a) a new module-level helper and constant, and (b) a few lines directly before the final `return Check(...)`, replacing only that return's `passed=` and `detail=` arguments. Do not touch the signature or the code above `clear = clear_mask(...)`. In the README row edit only the sentence beginning `The design's "wet area within 5 pp" clause` and leave the rest of the cell byte-identical (the same-line conflict with st-b602's appended sentence is then a trivial hand resolve). Do not reformat anything else.

## Steps

1. Task A (`wo.py` + tests), TDD:
   - Tests first in `tests/test_verify.py` next to the existing `test_wo_agreement_*` tests (line ~60) and `test_wo_check_*` tests (line ~323+):
     - `test_wo_wet_area_on_mutually_clear_pixels`: hand-built arrays give known pipeline and WO shares and n; WO flag bits (e.g. 4, 64, 1) exclude pixels from both shares; nothing clear returns (nan, nan, 0). Proves the helper uses the same clear rule as `wo_agreement`.
     - `test_wo_wet_area_gap_is_bounded_by_disagreement`: a few random 0/128 arrays; assert `abs(p - w) <= 1 - agreement` (the identity behind the ADR).
     - `test_wo_check_fails_on_wet_area_even_when_agreement_passes`: via `_wo_with`-style helper with a WO array equal to the pipeline's water except k pixels flipped dry-to-wet so agreement is about 0.93 (above agreement_min 0.9) while the signed gap is about -7 pp. Assert `passed is False`, `measured` equals the agreement, `threshold` equals agreement_min, `detail["wet_area_passed"] is False`, `detail["wet_area_diff_pp"]` about -7, `detail["wet_area_max_pp"] == 5.0`.
     - `test_wo_check_passes_when_wet_area_within_5pp`: flip a small number so agreement is above min and gap about 2 pp; `passed is True`, `wet_area_passed is True`.
     - `test_wo_check_wet_area_gate_is_symmetric`: flips wet-to-dry give a positive gap above 5 pp and also fail.
     - Existing test `test_wo_check_agreement_min_alone_decides_pass` (parametrised 0.55 True, 0.60 False, WO all wet, ndwi 0.0 gives agreement 1125/1936, gap about -41.9 pp) will now fail at 0.55 because of the wet-area gate. Rework it so its WO array is the pipeline's own water with an equal number of wet-to-dry and dry-to-wet flips (gap 0, agreement near 0.58), keeping its purpose: agreement_min alone decides the pass when wet area is fine. Keep a 0.55 True and 0.60 False pair with the agreement chosen between them. Other existing wo_check tests (branches, per-polygon setting, scl6, grid differs) use WO all wet with pipeline all wet (measured 1.0) or already expect passed False, and should stay green; confirm, and where `passed` is asserted True also assert `detail["wet_area_diff_pp"] == 0`.
   - Then implement in `src/wetland_change/verify/wo.py`: constant `WET_AREA_MAX_PP = 5.0`; `wo_wet_area(pipeline_water, pipeline_clear, wo) -> tuple[float, float, int]` returning (pipeline wet share, WO wet share, n mutually clear), reusing the clear rule from `wo_agreement` (`(wo & WO_EXCLUDE) == 0`); in `wo_check`, after the agreement lines and just before the final `return Check(...)`, compute the shares, `diff_pp`, `wet_ok`, and set `passed=bool(agreement >= agreement_min and wet_ok) if n else None` with the new detail keys. Update the module docstring to say Check.passed needs both agreement and wet area within 5 pp (design line 226), and that the wet-area gap is bounded by 1 - agreement.
   - Offline sanity only; do not run live tests.
2. Task B (docs), after or alongside A:
   - New `docs/decisions/0006-wet-area-within-5pp-on-live-water-check.md` in the style of ADR 0005 (Status accepted 2026-11-05, Context, Decision, Limits, Consequences). Content: the definition above; the identity |gap| <= 1 - agreement and the table of floors from ADR 0005 showing the clause was implied at 0.95 but binds at 0.91, 0.92, 0.94 (maximum possible gap 9, 8, 6 pp; ramsar-56 at 0.95 stays implied); the gate is per pass and per polygon, signed gap stored; threshold fixed at the design's 5 pp, not calibrated; Limits: the measured rates and the run-level result from LEARNINGS.md, one season of 6 dates, DEA WO is itself unvalidated; a failing pass on wet area alone shows as `passed false` with `wet_area_passed false` in the JSON report's detail, while the markdown report and the CLI line show only agreement, which is then above its threshold. Amends the "Water extent, live" row of the design; does not change ADR 0005 floors.
   - README.md row "Water extent, live" (line 137): replace only the sentence `The design's "wet area within 5 pp" clause is not implemented; no design document, decision or handoff records a reason.` with a sentence saying the wet-area clause is implemented (shares of mutually clear pixels, signed gap within 5 pp, per pass, ADR 0006), that it was implied by the design's 0.95 floor and binds at the lowered per-polygon floors, and the measured result (LEARNINGS.md). Add `docs/decisions/0006-...` mention by name only (no new path prefix is required; `tests/test_readme.py` checks that paths with prefixes src/, tests/, etc. exist and that row text accounts for the goal, so keep existing paths). Also scan README for other "not implemented" or wet-area mentions (grep showed only this row) and fix any.
3. Verify in the worktree, one command per line: `uv run ruff check src tests scripts`; `uv run ruff format --check src tests scripts`; `uv run mypy src scripts`; `uv run pytest -q` (judge by exit code; addopts is `-q -m 'not live'`, use `-o addopts="-m 'not live'"` only to see a count, never clear addopts); `GITHUB_ACTIONS=true uv run pytest -q`. `tests/test_readme.py` must stay green. Commit nothing; the orchestrator commits the story branch after the review gate.

## What the tests prove

Helper tests prove the wet-share definition and the bound that justifies the ADR. The wo_check tests prove the gate: it fails on a wet-area gap above 5 pp even with agreement above agreement_min, in both directions, passes when within 5 pp, leaves `measured` and `threshold` as agreement and agreement_min, and the reworked agreement_min test proves agreement_min alone still decides when wet area is fine.

## Implementation Notes

- 2026-11-05T16:07:23.453Z: Measured before building under hypotheses pre-registered in LEARNINGS.md (c13208a); evidence at 56678f0. H1 242/251 (0.9641) and H2 21/22 (0.9545) held, so the clause is in Check.passed. On the 6 fully measured dates, dates with a failing row go from 2 to 6; merged as is, verify exits 3 and the pipeline job ends red on all 6. Follow-up filed as st-7047. Deviation from the plan: wo_wet_area returns integer counts, not shares, so the gap is exact at the limit, and nothing clear returns (0, 0, 0). One fixture changed in test_wo_check_branches; no assertion weakened. Gates by exit code: ruff 0, format 0, mypy 0, pytest 0, GITHUB_ACTIONS=true pytest 0, 618 passed. Live check through wo_check on S2A_T50HLJ_20261029T021516_L2A: ramsar-12 passed False, gap 5.901 pp; ramsar-28 passed True, gap -3.544 pp; both match the CSV. Default suite offline; the live suite was not run.

## Questions
