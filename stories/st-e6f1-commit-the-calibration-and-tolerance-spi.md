---
id: st-e6f1
title: Commit the calibration and tolerance spikes and fix stale research scripts
type: chore
priority: P2
depends_on: []
discovered_from: st-ff89
touches: [LEARNINGS.md, docs/decisions/0007-spearman-threshold-from-whole-history.md, docs/research/2026-10-29-backfill-count.py, docs/research/2026-10-29-polygon-calibration.py, docs/research/2026-10-29-water-calibration.py, docs/research/2026-10-30-waterbodies-tolerance-extra.csv, docs/research/2026-10-30-waterbodies-tolerance.py, docs/research/2026-11-02-backfill-driver.sh, docs/research/2026-11-03-backfill-evidence-frozen.md, docs/research/2026-11-05-spearman-windows.py, tests/test_repo_hygiene.py, tests/test_research_scripts.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

The thresholds in config/pipeline.toml come from docs/research/2026-10-29-water-calibration.csv and 2026-10-29-polygon-calibration.csv, which were written by scratch/spikes/s2_calibrate.py and scratch/spikes/polygon_calibrate.py. Those scripts exist only in the main checkout under scratch/, which .gitignore excludes, so a clone cannot regenerate the CSVs. Both fix their window as now minus 90 days (DEA ga_s2_wo_provisional_3 keeps about three months), so a rerun reads different scenes, and the water CSV has no item ids. The 10 pp tolerance (tolerance_pp = 10.0, config/pipeline.toml:57-60) rests on docs/research/2026-10-30-waterbodies-tolerance.csv, written by s9_tolerance.py (LEARNINGS.md:341-342 says it is untracked; LEARNINGS.md:279-280 says the same of polygon_calibrate.py), and docs/research/2026-10-29-backfill-count.csv was written by s4_backfill_count.py. Neither script exists in the main scratch/spikes/; both live only under .worktrees/feature/wetland-change-pipeline/scratch/spikes/ (with s9_tolerance_extra.csv), so removing that worktree loses them. Also docs/research/2026-11-05-spearman-windows.py calls _history_paths with history_days, which no longer exists, so 2026-11-05-spearman-windows.csv cannot be regenerated, and docs/research/2026-11-02-backfill-driver.sh defaults WT to the removed worktree .worktrees/st-b983. Also, regenerating docs/research/2026-11-03-backfill-evidence.json with docs/research/2026-11-02-backfill-analysis.py on the branch head differs from the committed file: h4.lakes[*].passed flips from false to true for all four lakes because the script reads the current spearman_min (0.83, backfill-analysis.py:963 and 980) where the committed file used 0.9 under commit 114459b and config sha256 9ce8408c; rho, n_pairs, n_unpaired and h4.per_pass counts change (commit 00e8fb0 explains the rho change only); runs.backfill_calls, backfill_seconds_sum and seconds_per_processed_scene become null without a progress log; config_sha256, git_head, date and reference.searched_at differ. Found by the st-ff89 reproducibility audit, which fixes nothing.

## Acceptance Criteria

- [ ] s2_calibrate.py
- [ ] polygon_calibrate.py
- [ ] s9_tolerance.py and s4_backfill_count.py are committed under docs/research/ with a dated prefix
- [ ] copied from .worktrees/feature/wetland-change-pipeline/scratch/spikes/ (s9
- [ ] s4) and scratch/spikes/ (s2
- [ ] polygon). The two calibration scripts take --start and --end arguments in place of the 90-day window.
- [ ] The committed water-calibration script writes the Earth Search item id of every scored scene into its CSV.
- [ ] Each committed script header states that the DEA WO provisional window for the original run has passed and names its committed CSV (2026-10-29-water-calibration.csv
- [ ] 2026-10-29-polygon-calibration.csv
- [ ] 2026-10-30-waterbodies-tolerance.csv
- [ ] 2026-10-29-backfill-count.csv) as the record.
- [ ] docs/research/2026-11-05-spearman-windows.py carries a header stating it is frozen at commit 46e0e20
- [ ] or is ported so it runs on the branch head.
- [ ] docs/research/2026-11-02-backfill-driver.sh defaults WT to the repository root instead of the st-b983 worktree path.
- [ ] docs/research/2026-11-03-backfill-evidence.json has a frozen header (or an adjacent note file) naming commit 114459b and config sha256 9ce8408c...
- [ ] and listing the fields that differ on regeneration with the current config: h4 passed
- [ ] rho
- [ ] n_pairs
- [ ] n_unpaired and per_pass counts
- [ ] the null runs timing fields
- [ ] config_sha256
- [ ] git_head
- [ ] date and reference.searched_at. Alternatively docs/research/2026-11-02-backfill-analysis.py takes spearman_min and a progress log as arguments so a regeneration with the pinned values matches the committed file.
- [ ] LEARNINGS.md lines 279-280 and 341-342 name the committed docs/research/ paths of polygon_calibrate.py and s9_tolerance.py and no longer say the scripts are untracked in scratch/spikes/.
- [ ] tests/test_repo_hygiene.py extends SOURCE_DIRS to docs/research
- [ ] and adds a test that no script path (a scratch/ path ending in .py or .sh) named in LEARNINGS.md or in docs/research/*.md is gitignored
- [ ] except in two frozen records that name scratch/ scripts because they were untracked when written: docs/research/2026-11-04-milestone-2-review.md and docs/research/2026-11-06-reproducibility-audit.md. The test holds these two filenames in an explicit allowlist with a comment giving that reason. The check does not cover docs/plans
- [ ] docs/handoffs or docs/decisions.
- [ ] The four verification gates pass.

## Implementation Plan

# st-e6f1 plan: make the calibration and tolerance records reproducible from tracked files

Verified in worktree `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-e6f1` (HEAD d039c0e). Corrections to the story:
- LEARNINGS.md pointers are stale. The "untracked" sentences are at LEARNINGS.md:312-313 (polygon_calibrate.py) and :374-375 (s9_tolerance.py), not 279-280 / 341-342.
- Source scripts (outside the worktree, gitignored): `/Users/jarrodbaker/Documents/swan-wetland-change/scratch/spikes/{s2_calibrate.py,polygon_calibrate.py}` and `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/feature/wetland-change-pipeline/scratch/spikes/{s9_tolerance.py,s4_backfill_count.py,s9_tolerance_extra.csv}`. All exist now.
- `_history_paths` in src/wetland_change/verify/run.py:75 now takes `(ledger, *, newest)`; `history_days` is gone. Commit 46e0e20 and 114459b both exist.
- `2026-11-02-backfill-analysis.py` already has `--progress-log`; `spearman_min` is read from config (backfill-analysis.py:963, 980; config/pipeline.toml:65 = 0.83). Take the story's "frozen note" alternative for the evidence JSON; do not change the analysis script.
- Gates ruff/mypy do not cover docs/research; the new tests and anything in tests/ must pass all four gates.
- Only `docs/research/*.md` and LEARNINGS.md are scanned by the new hygiene test. `.py` files under docs/research may mention scratch/ (e.g. 2026-11-05-wet-area-measure.py:10) without failing.

## Steps

1. Copy the four scripts into `docs/research/` with the stem of the CSV they wrote (use `git mv`-free `cp`, then edit):
   - `2026-10-29-water-calibration.py` from s2_calibrate.py
   - `2026-10-29-polygon-calibration.py` from polygon_calibrate.py
   - `2026-10-30-waterbodies-tolerance.py` from s9_tolerance.py
   - `2026-10-29-backfill-count.py` from s4_backfill_count.py
   - optionally `2026-10-30-waterbodies-tolerance-extra.csv` from s9_tolerance_extra.csv (the extra n_items/n_px columns).
2. Water calibration script: wrap the module-level code in `main()`, add `build_parser()` (`--start`, `--end` required, ISO dates; `--out` required, so a rerun can never overwrite the committed record). Replace the `now - 90 days` window with `datetime=f"{start}/{end}"`. Track `items_by_lake: dict[lake_id, set[item_id]]` for every scene that contributed pixels (scene.item_id, the Earth Search id). Factor a pure `write_csv(tally, items_by_lake, out)` that writes columns `lake,method,threshold,agreement,n_pixels,n_scenes,item_ids` (item_ids sorted, `;`-joined, repeated on each row of that lake). Header note: the committed CSV predates the last two columns.
3. Polygon calibration script: same treatment (`--start`, `--end`, `--out` required, keep `--dry-run`), replacing the 90-day `since`; keep the existing columns (it already writes item_id). Update the docstring run line to `uv run python docs/research/2026-10-29-polygon-calibration.py --start ... --end ... --out ...`.
4. s9 and s4 scripts: s9 writes its extra CSV to `scratch/spikes/s9_tolerance_extra.csv`; change to an optional `--extra-out` (default none) with a small argparse; keep the default OUT (dated today, so no overwrite). s4 keeps its fixed START/END; move constants to `--start/--end/--out` defaults only if trivial, otherwise leave.
5. Headers: each of the four scripts opens with a docstring that (a) names its committed CSV (`2026-10-29-water-calibration.csv`, `2026-10-29-polygon-calibration.csv`, `2026-10-30-waterbodies-tolerance.csv`, `2026-10-29-backfill-count.csv`) as the record, and (b) says a rerun reads different data than the original. For the two calibration scripts state explicitly that the DEA `ga_s2_wo_provisional_3` window for the original run has passed (it keeps about three months), so the committed CSV, not a rerun, is the record. Do not write any `scratch/...py` path in headers or docs.
6. `docs/research/2026-11-05-spearman-windows.py`: add a header paragraph "Frozen at commit 46e0e20. `_history_paths` no longer takes `history_days`, so this does not run on the branch head; the CSV is the record" (keep the docstring's first line). Do not port.
7. `docs/research/2026-11-02-backfill-driver.sh`: change the default to `WT=${WT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}` (repository root) and update the comment. The stub test `2026-11-02-backfill-driver-test.sh` always sets WT, so it is unaffected; confirm by reading it (run it only if it is fast and offline).
8. Add `docs/research/2026-11-03-backfill-evidence-frozen.md` (adjacent note; JSON cannot carry a header). State: file produced at commit 114459b with config sha256 9ce8408cb8c554248cd8a8c03a6531405c56fe26b9ca899607625a13b340134f and spearman_min 0.9; regenerating with `2026-11-02-backfill-analysis.py` on the current head and config (spearman_min 0.83) differs in: h4.lakes[*].passed (false becomes true for all four lakes); h4 rho, n_pairs, n_unpaired and per_pass counts (commit 00e8fb0 explains the rho change only); runs.backfill_calls, backfill_seconds_sum, seconds_per_processed_scene (null without `--progress-log`); config_sha256, git_head, date, reference.searched_at. The file is the record; do not regenerate. Do not name any scratch/ script path in it.
9. LEARNINGS.md: replace lines 312-313 with a sentence naming `docs/research/2026-10-29-polygon-calibration.py` (and that its window now takes `--start/--end`, the original WO window having passed), and lines 374-375 with `docs/research/2026-10-30-waterbodies-tolerance.py`. Grep LEARNINGS.md afterwards: no `scratch/...py|sh` path may remain, and the word "untracked" must not describe these scripts.
10. `tests/test_repo_hygiene.py`: `SOURCE_DIRS = ["src", "tests", "scripts", "docs/research"]`; add `FROZEN_SCRATCH_RECORDS = {"2026-11-04-milestone-2-review.md", "2026-11-06-reproducibility-audit.md"}` with a comment: they name scratch/ scripts because those were untracked when the records were written. Add a helper `scratch_script_paths(text) -> set[str]` using regex `scratch/[\w./-]*\.(?:py|sh)` and a test `test_no_documented_scratch_script_is_gitignored`: scan LEARNINGS.md and `docs/research/*.md` (not docs/plans, handoffs, decisions), skip the allowlist, `git check-ignore -q <path>` (skip if not a git checkout, like the existing test), and fail listing `file: path` for any ignored hit.
11. New `tests/test_research_scripts.py`: load docs scripts with `importlib.util.spec_from_file_location` (filenames start with digits), guard `if __name__ == "__main__"` so import has no side effects.

## Tests and what they prove

- `test_no_python_sources_are_gitignored` (existing, extended to docs/research): no ignored .py in docs/research.
- `test_no_documented_scratch_script_is_gitignored`: LEARNINGS.md and docs/research/*.md name no gitignored script. Would have failed before step 9; passes with the two-file allowlist.
- `test_scratch_path_regex_finds_py_and_sh` (unit): the helper matches `scratch/spikes/x.py` and `scratch/a/b.sh` and ignores `scratch/` dirs and non-script paths; and a negative test that the allowlist filenames exist in docs/research (so a rename cannot silently disable the exemption).
- `test_calibration_scripts_require_window_args`: both calibration scripts' `build_parser()` reject missing `--start`/`--end`/`--out` (SystemExit) and parse valid ISO dates; asserts the source no longer contains `timedelta(days=90)`.
- `test_water_calibration_csv_has_item_ids`: call `write_csv` with a small hand-made tally and `items_by_lake`; assert header ends with `n_scenes,item_ids`, and that every item id appears in the file, sorted and `;`-joined.
- `test_script_headers_name_committed_csv`: for each of the four scripts, the module docstring contains its committed CSV filename and that file exists in docs/research; the two calibration docstrings also contain "provisional".
- `test_spearman_windows_header_is_frozen`: docstring contains `46e0e20`.
- `test_backfill_driver_default_wt_is_repo_root`: the driver's `WT=` line does not contain `st-b983` or `.worktrees`; write that line plus `echo "$WT"` to `tmp_path/docs/research/probe.sh`, run with bash, assert the output equals `str(tmp_path.resolve())` (default resolves two levels up).
- `test_backfill_evidence_note`: the note exists and contains `114459b`, `9ce8408c`, and each field name listed in step 8.

## Finish

Run the four gates in order (ruff check, ruff format --check, mypy, pytest) from the worktree, then `uv run python docs/research/2026-10-29-polygon-calibration.py --dry-run --start 2026-08-01 --end 2026-10-29 --out /tmp/x.csv` only if network is available (not required). Commit on branch story/st-e6f1. Do not touch committed CSVs.
## Orchestrator amendments

These override the text above where they differ.

1. Agents commit nothing; the orchestrator commits after the run. Uncommitted work at the end of a task is expected and is not a defect, and reviewers must not report it. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**.
2. Never call AWS for the project's own bucket, never run terraform plan or apply, never run compaction against S3, and never run `-m live` tests. Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data.
3. Gates, one command each, judged by exit code: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`, `GITHUB_ACTIONS=true uv run pytest -q`. Never clear addopts for a gate; for a count use `-o addopts="-m 'not live'"`.
4. Story-specific:
   - Do not run any of the research scripts against the network, including the optional polygon dry run. The tests exercise argument parsing and the pure CSV writer only.
   - The source copies under /Users/jarrodbaker/Documents/swan-wetland-change/scratch/spikes/ and /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/feature/wetland-change-pipeline/scratch/spikes/ are read only. Copy from them; never edit, move or delete them, and write nothing in the main checkout.
   - Copy s9_tolerance_extra.csv to docs/research/2026-10-30-waterbodies-tolerance-extra.csv so it survives removal of the feature worktree, and name it in the tolerance script header.
   - Do not modify any existing committed file under docs/research/ that ends in .csv, .json or .txt. `git diff --name-only -- 'docs/research/*.csv' 'docs/research/*.json' 'docs/research/*.txt'` must print nothing at the end.
   - Importing a research script in a test must have no side effects (no network, no file writes); keep all work under `if __name__ == "__main__":` or `main()`.
   - Tests write only under pytest's tmp_path, never /tmp.
   - The story's LEARNINGS.md line numbers are stale; the sentences are at about lines 312-313 and 374-375. Find them by content.
5. Docs, headers and notes are flat factual prose with no em dashes.

## Implementation Notes

- 2026-11-06T07:03:27.730Z: Commit 0bfabf4. Four spike scripts committed under docs/research/ (2026-10-29-water-calibration.py, 2026-10-29-polygon-calibration.py, 2026-10-30-waterbodies-tolerance.py, 2026-10-29-backfill-count.py) plus the tolerance extra CSV. Calibration scripts take --start/--end/--out; water CSV writer adds n_scenes and item_ids. spearman-windows.py takes the frozen-header alternative; because ADR 0007 records its sha256 and tests/test_config.py checks it, ADR 0007's hash was updated with a note that only the docstring changed. Backfill evidence JSON takes the adjacent frozen-note alternative. LEARNINGS.md sentences were at lines 312-313 and 374-375, not 279-280/341-342. No script run against the network; no committed CSV/JSON/TXT changed. Gates pass, 931 passed.

## Questions
