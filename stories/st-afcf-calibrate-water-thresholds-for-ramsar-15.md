---
id: st-afcf
title: "Calibrate water thresholds for ramsar-15, ramsar-28 and ramsar-56"
type: spike
epic: st-1d45
priority: P1
depends_on: []
touches: [LEARNINGS.md, docs/research/2026-10-29-polygon-calibration.csv]
exclusive: false
gates: [test]
created: 2026-10-29
updated: 2026-10-29
---
## Description

Spike. Decision at board approval: calibrate ramsar-15, ramsar-28 and ramsar-56 separately instead of excluding them. The DEA S2 Water Observations check (`src/wetland_change/verify/wo.py`, check `water_vs_dea_s2_wo`, agreement_min 0.91) fails on these polygons on the 2026-10-27 and 2026-10-29 passes (`docs/handoffs/2026-10-29-milestone-1.md`, State):

| Polygon | Measured agreement |
|---|---|
| ramsar-15 | 0.576 and 0.902 |
| ramsar-28 | 0.907 to 0.909 |
| ramsar-56 (Forrestdale, on the 50HLK/50HMK seam) | 0.854 to 0.868 |

The global method, MNDWI at -0.1, came from spike S2 over four lakes (LEARNINGS.md, "S2 water calibration"; `docs/research/2026-10-29-water-calibration.csv`). The S2 scripts are untracked and exist only at `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/feature/wetland-change-pipeline/scratch/spikes/` (`s2_calibrate.py`, `wo_spike.py`). Copy them into this worktree's gitignored `scratch/spikes/` and adapt them.

DEA `ga_s2_wo_provisional_3` keeps about three months, so sweep the passes available now. For each polygon, sweep NDWI and MNDWI thresholds and SCL class 6 and record pixel-weighted agreement. Recommend a method, threshold and agreement_min per polygon, and say whether one estuary-and-creek class setting would serve all three. Compare ramsar-56's scores on 50HLK and 50HMK to see whether the seam explains its lower agreement.

## Acceptance Criteria

- [ ] `docs/research/<date>-polygon-calibration.csv` has one row per polygon, method, threshold and pass, with n_mutually_clear and agreement.
- [ ] LEARNINGS.md gains a dated "Per-polygon water calibration" section giving, for each of ramsar-15, ramsar-28 and ramsar-56, the chosen method, threshold, pixel-weighted agreement and proposed agreement_min.
- [ ] That section states whether ramsar-56 agreement differs between tiles 50HLK and 50HMK, and by how much.
- [ ] No file under `src/` or `config/` changes in this story.

## Implementation Plan

# Plan for st-afcf: calibrate water thresholds for ramsar-15, ramsar-28, ramsar-56

Spike story. The deliverables are one CSV and one LEARNINGS.md section. `src/` and `config/` must not change. The sweep script lives in the gitignored `scratch/spikes/`, so it is never committed.

## Findings from verifying the story pointers (worktree `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-afcf`)

- `src/wetland_change/verify/wo.py` matches the story. `WO_EXCLUDE = 1|2|32|64`, `WO_WET = 128`, `find_wo_href`, `dea_reader` and `wo_agreement` all exist, and `wo_check` has agreement_min 0.91 and also records `scl_agreement`. The `src/` tree is identical to the feature worktree's.
- The S2 scripts exist only at `.../.worktrees/feature/wetland-change-pipeline/scratch/spikes/` (`s2_calibrate.py`, `wo_spike.py`, plus S2 log). `s2_calibrate.py` is the template. `wo_spike.py` is the older single-lake script and is only a reference for the DEA read pattern.
- This worktree has no `scratch/`, no `.venv` and no `data/external/`. `data/*` and `scratch/` are gitignored. The inputs `dbca_010_ramsar_sites.geojson` and `dea_waterbodies_v3_swan.geojson` exist only in the feature worktree's `data/external/`, and that worktree also has a working `.venv`. Setup therefore needs `mkdir -p scratch/spikes`, a symlink `data/external` to the feature worktree's copy (git ignores it via `data/*`), and `uv sync` (fall back to the feature worktree's `.venv/bin/python` if sync fails; the `src/` trees match).
- Polygon ids come from `load_ramsar` (`ramsar-<objectid>`), loaded with the `[aoi]` section of `config/pipeline.toml`. ramsar-15 (67.5 ha) and ramsar-28 (60.0 ha) are in Peel-Yalgorup System, on tile 50HLJ and 50HLK. ramsar-56 (246 ha, Forrestdale & Thomsons Lakes) spans 50HLK (coverage 1.0 of its window) and 50HMK (about 0.36).
- `plan_window` clips to the scene and `scene_coverage` is only reported. The S2 script's `scene_coverage < 0.99` skip would drop every 50HMK pass of ramsar-56, so this spike must not apply that filter. The `inside` mask from `rasterise` already restricts scoring to the polygon part that lies in the scene.
- A scored pass is one Earth Search item (tile) for one polygon. Use the S2 inclusion rules: collection `sentinel-2-c1-l2a`, `eo:cloud_cover < 20`, last 90 days, skip when fewer than 100 mutually clear pixels, skip when the WO grid transform differs from the scene grid.
- Story prerequisite check: none missing. `depends_on` is empty. Downstream st-2048 consumes the LEARNINGS.md section, so its format must be exact (see step 5).

## Steps

1. **Setup (no tracked changes).** In the worktree: `mkdir -p scratch/spikes`; `ln -s /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/feature/wetland-change-pipeline/data/external data/external`; `uv sync`. Copy `s2_calibrate.py` and `wo_spike.py` from the feature worktree's `scratch/spikes/` into `scratch/spikes/`. Confirm `git status --short` shows nothing new.
2. **Write `scratch/spikes/polygon_calibrate.py`**, adapted from `s2_calibrate.py`.
   - Load `config/pipeline.toml`, `load_ramsar`, and keep ramsar-15, ramsar-28 and ramsar-56.
   - Query Earth Search over the union bbox, 90 days, cloud under 20.
   - For each item and each polygon that intersects the scene, plan the window (no coverage filter), read the stack, build `inside` and `clear`, read the WO window with `dea_reader`, and form `both = clear & wo_clear`. Skip when `both.sum() < 100`.
   - Score NDWI and MNDWI thresholds from -0.50 to +0.50 in steps of 0.05, which widens S2's range because its NDWI optimum sat on the -0.30 edge. Also score SCL class 6.
   - Write `docs/research/2026-10-29-polygon-calibration.csv` with columns `polygon_id,tile,item_id,pass_date,subset,method,threshold,n_mutually_clear,n_agree,agreement`. `subset` is `all` for every polygon. For ramsar-56 also add `seam_overlap` rows, scored on only the pixels inside the polygon that both 50HLK and 50HMK windows cover (match pixels by world coordinates from `transform10`; the lattices align per S1). On the same pixels HLK and HMK each score against their own WO tile.
   - Print per-polygon pooled best by method, and per-pass tables at the best setting.
3. **Run it** (needs network: Earth Search, DEA STAC, S3). Save the log to `scratch/spikes/polygon_calibrate.log`. Expect roughly 10 to 25 scored passes per polygon. If a scored polygon has fewer than 3 passes, say so in the write-up rather than widening the cloud limit silently.
4. **Analyse** (in a throwaway script or pandas, not committed).
   - For each polygon, compute pixel-weighted agreement per (method, threshold) over all `subset == all` rows, i.e. sum(n_agree) / sum(n_mutually_clear). Choose the best method and threshold. Prefer MNDWI at -0.1 (the global setting) when its pooled agreement is within 0.005 of the best, to avoid overfitting.
   - Compute the worst single-pass agreement at the chosen setting.
   - Propose `agreement_min` as pooled agreement minus 0.02, rounded down to 2 decimals (the S2 convention). If the worst pass sits below that, state it and the pass.
   - Pooled answer to "would one estuary-and-creek class setting serve all three": best (method, threshold) over the three polygons pooled, plus each polygon's agreement under it and how far each falls below its own best. Say yes only if no polygon loses more than about 0.01.
   - Investigate the ramsar-15 outlier (0.576 on 2026-10-27 against 0.902 on 2026-10-29). Report its agreement per pass at the chosen setting and, for 2026-10-27, the wet pixel counts in the scene index and in WO, to say whether the threshold cures it.
   - ramsar-56 seam: compare 50HLK and 50HMK agreement at the chosen setting, per pass and pooled. Report the pixel-weighted difference on `all` and on `seam_overlap`. The overlap comparison separates a seam or resampling effect from a spatial effect, because the HMK piece is a different part of the lake.
5. **Append LEARNINGS.md section** `### Per-polygon water calibration (2026-10-29)` after the S2 section and before `## Live run findings` (insert only; never edit existing text). Required content:
   - Pass count, date range, item and pixel counts per polygon.
   - For each of ramsar-15, ramsar-28 and ramsar-56, a line giving: method, threshold, pixel-weighted agreement, proposed agreement_min. Use `method mndwi, threshold -0.1` wording that st-2048 can copy into `config/pipeline.toml`.
   - The shared-setting answer.
   - A ramsar-56 seam sentence stating whether HLK and HMK differ and by how much, in percentage points, for `all` and for `seam_overlap`.
   - A pointer to `docs/research/2026-10-29-polygon-calibration.csv`, and a note that the scripts are untracked in `scratch/spikes/`.
   - The DEA retention caveat (about 3 months).
6. **Verify** (what each check proves):
   - A Python check that the CSV has exactly the ten columns, covers all three polygon ids, and that each (polygon, tile, item, subset, method, threshold) is unique with `0 <= agreement <= 1` and `n_agree <= n_mutually_clear`. This proves the acceptance-criterion CSV shape.
   - `grep -n "Per-polygon water calibration" LEARNINGS.md` plus reading the section for the three polygon lines, the seam sentence, and the exact values matching the CSV (recompute one number from the CSV by hand). This proves the second and third criteria.
   - `git diff --name-only main... ; git status --short` lists only `LEARNINGS.md` and `docs/research/2026-10-29-polygon-calibration.csv`, with nothing under `src/` or `config/`. This proves the last criterion.
   - Story gate `test`: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts` and `uv run pytest -q` still pass, since nothing under the checked trees changed.
7. **Commit** only the CSV and LEARNINGS.md. Do not add the `data/external` symlink or `scratch/`; both are ignored. Use the Co-Authored-By trailer from the session reminder.

## Implementation Notes

- 2026-10-29T19:32:49.745Z: touches-expansion: overlaps st-1990 (.gitignore, config/pipeline.toml, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.747Z: touches-expansion: overlaps st-8228 (.gitignore, config/pipeline.toml, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.748Z: touches-expansion: overlaps st-ae6e (.gitignore, config/pipeline.toml, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.749Z: touches-expansion: overlaps st-d4a8 (.gitignore, config/pipeline.toml, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.751Z: touches-expansion: overlaps st-f4d3 (.gitignore, config/pipeline.toml, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split

## Questions
