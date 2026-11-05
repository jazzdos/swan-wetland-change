---
id: st-b602
title: Make verify's verdict reflect the verification matrix
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/verify/checks.py, src/wetland_change/verify/run.py, src/wetland_change/verify/wo.py, src/wetland_change/verify/ndvi.py, tests/test_verify.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
parked_complexity: routine
---

## Description

verify exits 3 only on a False check and 4 only when nothing scored (src/wetland_change/cli.py:254-258), and all_passed uses scored checks alone (verify/checks.py:79), so an unreachable DEA or Planetary Computer gives exit 0 and all_passed true. The Spearman check sees only the run's scenes and always skips in steady state. Seven matrix rows have no check in the JSON. wo_check has no pixel floor (verify/wo.py:119), so one disagreeing pixel on a tiny DEA polygon fails the run. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 5.

## Acceptance Criteria

- [ ] verify exits non-zero when a reference check is skipped because its source raised an error
- [ ] WO and NDVI checks skip a polygon below a configured minimum of mutually clear pixels
- [ ] The Spearman check scores over stored history and not only the run's scenes
- [ ] The weekly report lists every matrix row with a pass or fail or not-run status

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-b602, HEAD a365acb)

All story pointers still hold. Findings that shape the plan:
- `src/wetland_change/cli.py` `verify` (about lines 254-258): exit 3 on any `passed is False`, exit 4 only when nothing scored. Exit codes 2 (bad option/no run), 3, 4, 5 (manifest unreadable) are taken, so the new code is 6.
- `src/wetland_change/verify/checks.py`: `Check` dataclass; `write_report` sets `all_passed = bool(scored) and all(...)`. An errored skip is `passed None` with `detail["error"]`. It is produced by `run._error_check`, `waterbodies._unavailable` and `freshness._skipped`. A skip with only `detail["reason"]` (no DEA scene, fewer than N pairs) is a legitimate skip, not an error.
- `verify/wo.py::wo_check` passes whenever `n > 0` and agreement >= agreement_min (no pixel floor). `verify/ndvi.py::ndvi_median_check` only skips when `n_compared == 0`.
- `verify/run.py::verify_run`: the NDVI correlation check collects `scored` checks by detail keys `ndvi_median` and `dea_ndvi_median`. Those keys are also present on skipped checks, so a new pixel-floor skip must be excluded from `scored`.
- `verify/run.py::_waterbodies` reads observation files only for the run's own scenes, then `waterbodies._lake_checks` builds the per-pass checks and the Spearman check from those rows. Two changes follow. First, the Spearman input must come from stored history. Second, the ledger already stores `observation_path`, `datetime` and `status` per item (`ledger.latest_entries`), so history paths come from the ledger and `store.list_files` is not needed. A bounded window (`history_days`) keeps S3 requests bounded, as st-b101 intended.
- Matrix rows: `docs/plans/2026-10-29-swan-wetland-change-design.md` lines 217-236 list 14 rows, mirrored in README.md "Verification matrix". Only discovery, bytes, scaling, SCL, water live, water history and NDVI have runtime checks in the JSON. The other 7 rows (index arithmetic, GeoParquet, STAC, incremental, change detection, scheduled job alive, end to end) have none.
- `.github/workflows/verify.yml` runs `verify` then `freshness` as separate steps, and `tests/test_workflows.py` asserts that order. The plan leaves the workflow untouched. The scheduled-job-alive row will read `not_run` in the verify report because `freshness` is a separate command (noted as a limitation).
- Existing offline tests use the `_built_run` helper in tests/test_verify.py. New config defaults (`min_clear_pixels`) can make fixture-based `verify_run` tests skip, so those tests may need the test config to set `min_clear_pixels=1`.

## Steps

### Batch 1: verdict and matrix report (AC1, AC4)
1. `src/wetland_change/verify/checks.py`: add `Check.errored` (property: `passed is None and "error" in detail`). In `write_report` add `n_errored`; set `all_passed = bool(scored) and all(...) and n_errored == 0`; add a `matrix` list to the JSON payload and a "Matrix" table to the Markdown.
2. New `src/wetland_change/verify/matrix.py`: the 14 design rows as data (row name, tuple of check-name matchers, note). `matrix_status(checks) -> list[dict]` returns, per row, `{row, status in pass|fail|not_run, n_pass, n_fail, n_skipped, n_errored, check_names, note}`. Rules: fail if any matching check is False; pass if at least 1 scored and 0 errored; otherwise not_run. Rows with no runtime check are always not_run with a note naming the standing test (tests/test_indices.py, tests/test_geoparquet.py, tests/test_catalogue.py, tests/test_golden_run.py, tests/test_change.py; scheduled-job-alive says "run `wetland-change freshness`"). End to end is derived: fail if any row failed, else pass if the overall verdict is all_passed, else not_run.
3. `src/wetland_change/cli.py` `verify`: after the existing exit 3 check, if any `check.errored`, print `N reference checks could not run for run X` to stderr and exit 6; keep exit 4 after that. Also print errored skips as `skip` lines as now.
Tests (tests/test_verify.py, new tests/test_verify_matrix.py):
- `test_cli_verify_exit_codes` gains a case `[Check("a", True,...), Check("b", None, ..., detail={"error": "X"})] -> 6`; a False plus an errored check still gives 3; a reason-only skip still gives 0; this proves AC1 and the unchanged codes.
- `test_report_*`: errored skip gives `all_passed False`, `n_errored 1`; reason-only skip leaves `all_passed True` when others pass.
- `test_verify_run_turns_exceptions_into_skipped_checks` extension: JSON written by an all-unreachable run has `all_passed False`.
- matrix tests: all 14 rows present in the JSON in design order; each status rule above; standing rows are not_run; end-to-end derivation; the Markdown contains every row name.

### Batch 2: pixel floor (AC2)
4. `src/wetland_change/config.py`: `VerifyConfig.min_clear_pixels: int = Field(default=100, ge=1)` (100 pixels at 10 m = 1 ha). `config/pipeline.toml`: add `min_clear_pixels = 100` under `[verify]` with a comment (a bare `[verify]` header before `[verify.waterbodies]`).
5. `verify/wo.py::wo_check`: new keyword `min_clear_pixels: int = 1`. When `0 < n < min_clear_pixels`, return `Check(name, None, None, agreement_min, wo_href, {..., "n_mutually_clear": n, "min_clear_pixels": m, "reason": "fewer than M mutually clear pixels"})`. Keep the `n == 0` behaviour.
6. `verify/ndvi.py`: `ndvi_median_check(..., min_pixels: int = 1)` skips (passed None, reason `fewer than M compared pixels`, detail still carries `n_compared`) when `0 < n_compared < min_pixels`. Thread the keyword through `ndvi_scene_check(..., min_pixels=1)`.
7. `verify/run.py`: pass `cfg.verify.min_clear_pixels` into `wo_check` and `ndvi_scene_check`. Exclude skipped checks from the correlation `scored` list (`c.passed is not None`).
Tests: wo_check with 1 disagreeing mutually clear pixel and the default floor of 1 fails as before; with `min_clear_pixels=2` it is skipped (passed None, measured None, reason set, n_mutually_clear 1); n equal to the floor is scored. The same pair for ndvi_median_check. A verify_run test shows a skipped-by-floor NDVI row is not fed to the correlation. A config test covers the default and `ge=1`. Existing fixture tests that now fall under 100 pixels set `min_clear_pixels=1` in their config.

### Batch 3: Spearman over stored history (AC3)
8. `config.py`: `WaterbodiesVerifyConfig.history_days: int = Field(default=365, ge=1)`; `pipeline.toml` `[verify.waterbodies] history_days = 365`.
9. `verify/waterbodies.py`: extract the dedupe and pairing loop of `_lake_checks` into a helper returning `(per_pass_checks, pipe_pairs, dea_pairs, n_unpaired)`. `waterbody_checks(..., history: pd.DataFrame | None = None)`: per-pass checks come from the run rows (`start`/`end` still apply to them); the Spearman check runs the same helper over `history` rows for the polygon (or over the run rows when `history is None`, which keeps old callers unchanged). Add `history_days` to the Spearman detail via a new optional argument.
10. `verify/run.py::_waterbodies`: build the history path list from `latest_entries(read_ledger(store))` (status succeeded, `observation_path` not null, `datetime` within `history_days` of the newest run scene), union with the run's own observation paths. Read once with `read_observations(store, paths)`. The run rows are `history[item_id in run item ids]`. Pass both to `waterbody_checks`.
Tests (tests/test_verify_waterbodies.py, tests/test_verify.py): per-pass checks are only for the run rows while Spearman has 10+ pairs from history rows outside the run (proves AC3); old behaviour when `history=None`; history older than `history_days` is excluded; verify_run with 10+ stored passes over several prior runs and a fake loader yields a scored Spearman check; existing `test_verify_run_scores_the_waterbody_history` still shows Spearman skipped at 1 pair.

### Docs (in the batch that changes the behaviour)
README.md: the `verify` bullet (exit codes 3, 4, 5, 6, matrix section in the report, history window), the Verification matrix status text for water live, water history and end to end, and a Limitations note that the scheduled-job-alive row reads not_run in the verify report. Check tests/test_readme.py still passes.

## Verification (each batch, in order)
uv run ruff check src tests scripts / uv run ruff format --check src tests scripts / uv run mypy src scripts / uv run pytest -q

## Orchestrator amendments (settled before build)

These override the plan text above where they differ.

1. The matrix status strings are `pass`, `fail` and `not-run`, matching AC4's wording.
2. Every name verify can emit maps to a matrix row. `_guard` and `_error_check` emit `scl_shares` and `scene_grid`, which the plan's matchers miss: the SCL row matches the prefix `scl_share`, and "Reads the right bytes" also matches `scene_grid`.
3. An errored check with nothing scored exits 6, not 4.
4. `verify_run` reads the ledger once and passes the table to `scenes_for_run` and `_waterbodies`, keeping st-b101's single read. `scenes_for_run` gains an optional `ledger` argument so its callers keep working.
5. History paths are checked against one `store.list_files("observations")` call rather than one `store.exists` per path, because the history can hold a year of files.
6. The Spearman window is closed at both ends: newest scene of the run minus `history_days`, up to that newest scene. Re-verifying an older run therefore gives the same result after later passes are stored.
7. The orchestrator commits after the review gate; implementers commit nothing.

Checked before build: a late reference is not an error. Planetary Computer returns reason "not on Planetary Computer yet", and a missing DEA WO or ARD item returns a reason skip, so exit 6 fires only on a raised exception. `min_clear_pixels = 100` is this story's default (1 ha at 10 m); neither the design nor the review names a value.

## Implementation Notes

- 2026-11-05T13:45:11.062Z: Deviation from the design, for Jarrod's review. The design's 'Water extent, history' row (docs/plans/2026-10-29-swan-wetland-change-design.md:227) sets Spearman at or above 0.9 'over the backfill', and its backfill sizing counts from 2022-01-01 (line 287). This story scores the last history_days days (default 365) ending at the run's newest scene, so a default verify does not score the whole backfill. Reason: every observation file in the window is read on each verify, and st-b101 bounded per-run S3 requests as history grows; 365 days still covers one full seasonal cycle. Raising [verify.waterbodies] history_days widens the window at one more read per stored file. Step limits: verify.yml's verify step has a 20 minute timeout; pipeline.yml's has none of its own and sits under the 120 minute job timeout.
- 2026-11-05T14:08:28.292Z: Measured with scratch/st-b602/measure_rho.py (gitignored, in this worktree), read-only against /Users/jarrodbaker/Documents/swan-wetland-change-data/outputs, 1147 files, file count unchanged. The reviewer's 'no local outputs' was wrong. Results are in scratch/st-b602/rho_by_window.csv. 365-day window, 13 monthly run ends 2025-11-03 to 2026-10-29: 0 of 13 have all four lakes at or above 0.9; rho ranges 0.627 to 0.927; at the newest end Forrestdale 0.831 (20 pairs), Clifton 0.833 (26), Preston 0.720 (25), Thomsons 0.835 (24). 730-day window at the newest end: 0.872, 0.779, 0.789, 0.846. Whole backfill with this code: Forrestdale 0.861, Clifton 0.855, Preston 0.857, Thomsons 0.893, which matches the tile-and-date sensitivity in docs/research/2026-11-03-backfill-hypotheses.md. Gates at this commit: ruff, format, mypy, pytest default and GITHUB_ACTIONS=true all exit 0, 671 passed. Build-flow stopped before its own final verification, and review findings 1 and 3 were fixed by its fix agent with reverted-fix checks.
- 2026-11-05T23:16:34.421Z: Decision 2026-11-06 (Jarrod): option C. Score the Spearman check over the whole stored history, as the design's 'over the backfill' says, and calibrate spearman_min with an ADR like 0005: lowest whole-history rho minus 0.02, rounded down (0.855 gives 0.83). H4 stays recorded as not supported.

## Questions

- 2026-11-05T14:08:28.371Z: st-b602 scores the Spearman check over stored history as its acceptance criterion asks, and that makes verify fail on every run. Measured read-only on the local backfill: at the 365-day window no lake set reaches spearman_min 0.9 at any of 13 monthly run ends (rho 0.627 to 0.927, 20 to 26 pairs at the newest end); over the whole backfill rho is 0.855 to 0.893. Merged as is, the daily verify step exits 3 every day and verify.yml opens an issue every week. Separately, per-pass checks already fail on 53 of 98 Lake Clifton passes in the backfill, so some days are red today. Which do you want? (A) Keep 0.9 and accept red, stated in README Limitations. (B) Make the Spearman check advisory: it shows in the matrix but does not set the exit code or the end-to-end row. (C) Score the whole stored history, as the design's 'over the backfill' says, and calibrate spearman_min with an ADR like 0005: lowest rho 0.855 minus 0.02, rounded down, gives 0.83; H4 stays recorded as not supported. C reads 1147 files and 226 MB per verify today, growing with each pass; S3 read time is unmeasured and verify.yml's step limit is 20 minutes. I recommend C, because 365-day rho is too noisy to gate on and C is the only option where the check can both pass and fail. The code is committed on story/st-b602 and all gates pass.
