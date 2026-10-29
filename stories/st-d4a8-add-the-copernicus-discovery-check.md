---
id: st-d4a8
title: Add the Copernicus discovery check
type: feature
epic: st-1d45
priority: P2
depends_on: []
touches: [src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_live_verify.py, tests/test_verify.py, tests/test_verify_copernicus.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Verification matrix row "Discovery finds every scene" (design): list CDSE STAC `https://stac.dataspace.copernicus.eu/v1`, collection `sentinel-2-l2a` (listing is free; no asset access needed). Per tile per month, item counts and ESA product names must match Earth Search Collection 1 under the same cloud threshold and AOI, allowing 24 hours of latency.

- Earth Search items map to ESA product names through `s2:product_uri`; CDSE item ids are product names.
- Compare on the datatake. Strip the processing baseline and generation time, because Collection 1 and CDSE products of one datatake differ there. Deduplicate CDSE datatakes that appear more than once.
- The check covers the window of the run being verified, not history. CDSE holds 2022 items that Collection 1 lacks (LEARNINGS.md, S4).
- Implement as `src/wetland_change/verify/copernicus.py`, wired into `verify_run` through `_guard` in `src/wetland_change/verify/run.py`.
- Spike S4's working CDSE queries are in the untracked `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/feature/wetland-change-pipeline/scratch/spikes/s4_backfill_count.py`.

## Acceptance Criteria

- [ ] Offline test with fake clients: matching listings pass `discovery_vs_copernicus`, and a product in CDSE but missing from Earth Search, older than 24 hours, fails with the product named in the detail.
- [ ] Offline test: a product newer than 24 hours that is missing from Earth Search does not fail the check.
- [ ] Offline test: two products that differ only in processing baseline or generation time count as the same product.
- [ ] Offline test: `verify_run` emits `discovery_vs_copernicus` checks per tile.
- [ ] Live test marked `live`: tile 50HLK for 2026-10 is listed from both catalogues and scored.

## Implementation Plan

# st-d4a8 Add the Copernicus discovery check

Verified against the worktree `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-d4a8`. No prerequisite is missing. `verify/copernicus.py` does not exist yet. `_guard`, `verify_run`, `catalogue.search.open_client`/`StacClient`, the `live` marker and `tests/test_pipeline.py` (`FakeClient`, `_config`, `_polygons`, `_run`, `NOW`) are all present. The spike script exists at the path in the story. It filters CDSE cloud cover client-side and takes the tile from the last 5 characters of `grid:code`.

## Design decisions (made here, since the story leaves them open)

- **Datatake key.** Take the product name, drop `.SAFE`, split on `_`. A name has 7 tokens: `S2C_MSIL2A_<sensing>_N0513_R060_T50HLK_<generation>`. The key joins every token except the `N0xxx` baseline token and the last (generation) token. An unrecognised shape raises `ValueError`, which `_guard` turns into a skipped check.
  - Earth Search name: `s2:product_uri`.
  - CDSE name: item `id`.
  - `pixels.pc_item_id` only strips the baseline, so it is not reused.
- **Same listing rules on both sides.**
  - Query: `collections`, `bbox` (union of the AOI polygons), `datetime` window.
  - Local filters on both sides: `eo:cloud_cover < cfg.stac.cloud_cover_max`, footprint intersects any AOI polygon in EPSG:4326.
  - Earth Search: also send the `query` cloud filter server-side.
  - CDSE: filter client-side only, as the spike does. A missing cloud value excludes the item.
- **Tile.** Use `grid:code` with the `MGRS-` prefix stripped, i.e. the last 5 characters. For CDSE, fall back to the `_T50HLK_` token of the id if `grid:code` is absent.
- **Month.** `properties.datetime` in UTC, formatted `YYYY-MM`.
- **Window of the run.**
  - Start: the start of the day (UTC) of the earliest `datetime` among the run's succeeded scenes.
  - End: the run manifest's `started_at` (from `runs/<run_id>.json`).
  - This is deterministic and excludes the 2022 history that Collection 1 lacks.
  - `now` for the latency rule is the same `started_at`.
- **24 h latency.** A datatake that appears in only one catalogue counts as a mismatch only if its sensing `datetime` is at or before `now - 24h`. Newer ones go into `pending_latency` and never fail the check.
- **One Check per tile** (tiles seen in either catalogue after filtering), name `discovery_vs_copernicus`.
  - `passed` is `n_mismatched == 0`.
  - `measured` is the float count of mismatched datatakes. `threshold` is `0.0`.
  - `reference` is `"https://stac.dataspace.copernicus.eu/v1 sentinel-2-l2a"`.
  - Detail keys: `tile`, `window_start`, `window_end`, `latency_hours` (24), `months` (`{"2026-10": {"earth_search": n, "cdse": n}}`, unique datatakes), `missing_from_earth_search` (CDSE product names, full with baseline and generation), `missing_from_cdse` (Earth Search product_uri stems), `pending_latency` (names).
  - If both catalogues return nothing, emit one skipped Check (`passed=None`) with `detail["reason"]`.
- **Dedupe.** Both sides are deduplicated by datatake key, so CDSE reprocessed duplicates count once.
- **Known limit.** A scene whose cloud cover straddles the 20 % threshold between baselines can show as a one-sided mismatch. Note this in the module docstring.
- **Wiring in `verify_run`.**
  - New keyword arguments `es_client: StacClient | None = None` and `cdse_client: StacClient | None = None`. `None` means `open_client(...)` inside the guarded lambda, so a network failure becomes a skipped check.
  - If `scenes_for_run` is empty, do not run discovery. The existing test expects `[]` for an unknown run.
  - Run discovery once after the per-scene loop, via `_guard("discovery_vs_copernicus", ...)`.

## Steps

1. Create `src/wetland_change/verify/copernicus.py` and `tests/test_verify_copernicus.py` (batch 1, tasks 1.1 and 1.2).
2. Wire into `src/wetland_change/verify/run.py`, add the `verify_run` test, and isolate the existing tests from the network (batch 2, task 2.1).
3. Add the `live` test to `tests/test_live_verify.py` (batch 2, task 2.2).
4. Final gate: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.

## What each test proves

- `test_matching_listings_pass`: same datatakes on both sides gives passed True, with counts in `months`.
- `test_old_cdse_only_product_fails_and_is_named`: a CDSE product missing from Earth Search and older than 24 h fails, and its name is in `detail["missing_from_earth_search"]`.
- `test_recent_cdse_only_product_does_not_fail`: a missing product newer than 24 h passes and is listed in `pending_latency`.
- `test_baseline_and_generation_time_differences_are_one_product`: names differing only in the N token and generation time match; CDSE duplicates are deduped.
- Filter tests: over-cloud and off-AOI items are ignored on both sides.
- `test_verify_run_emits_discovery_check_per_tile`: `verify_run` with injected fake clients returns one `discovery_vs_copernicus` Check per tile.
- Live test: tile 50HLK for 2026-10 is listed from both catalogues and scored.

## Implementation Notes

- 2026-10-29T19:32:49.752Z: touches-expansion: overlaps st-1990 (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_pipeline.py, tests/test_search.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.753Z: touches-expansion: overlaps st-8228 (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_pipeline.py, tests/test_search.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.754Z: touches-expansion: overlaps st-ae6e (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_pipeline.py, tests/test_search.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.755Z: touches-expansion: overlaps st-afcf (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_pipeline.py, tests/test_search.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.756Z: touches-expansion: overlaps st-f4d3 (.gitignore, LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_infra.py, tests/test_ledger.py, tests/test_pipeline.py, tests/test_search.py, uv.lock) — coordinate or split

## Questions
