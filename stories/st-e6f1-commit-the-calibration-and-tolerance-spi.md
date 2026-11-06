---
id: st-e6f1
title: Commit the calibration and tolerance spikes and fix stale research scripts
type: chore
priority: P2
depends_on: []
discovered_from: st-ff89
touches: [docs/research/**, scripts/**, tests/test_repo_hygiene.py, LEARNINGS.md]
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

## Implementation Notes

## Questions
