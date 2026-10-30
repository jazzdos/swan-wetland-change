---
id: st-8c11
title: Add the NDVI check against DEA Sentinel-2 NBART
type: feature
epic: st-1d45
priority: P2
complexity: hard
depends_on: []
touches: [LEARNINGS.md, data/SOURCES.md, src/wetland_change/verify/ndvi.py, src/wetland_change/verify/run.py, tests/test_verify.py, tests/test_verify_ndvi.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-30
---
## Description

Verification matrix row "NDVI" (design): DEA NBART from `ga_s2am_ard_3`, `ga_s2bm_ard_3` and `ga_s2cm_ard_3` (DEA STAC `https://explorer.dea.ga.gov.au/stac`, unsigned `dea-public-data`), for the same acquisition, with nodata -999. The per-polygon NDVI median must be within 0.05 of `ndvi_median`, and correlation across the run's polygon rows must be above 0.95.

- Open research item from the design: the NBART scale factor (1e-4 per the dea-load-and-mask skill, not confirmed in STAC metadata). Confirm the scale and offset from product metadata and record them.
- Choose the clear-pixel mask (DEA fmask on the same pixels, or the pipeline's SCL clear mask) and state the choice in the module docstring.
- DEA ARD is expected in EPSG:32750 for these tiles; assert the CRS before comparing.
- Recent passes may only have provisional ARD; use the newest pass that has a matching final or provisional item.
- New `src/wetland_change/verify/ndvi.py`, wired into `verify_run`.

## Acceptance Criteria

- [ ] Offline test with synthetic arrays: NDVI medians 0.04 apart pass `ndvi_vs_dea_nbart`, medians 0.06 apart fail, and -999 pixels are excluded.
- [ ] Offline test: the correlation check over at least 5 synthetic polygon rows passes above 0.95 and fails below it.
- [ ] LEARNINGS.md gains a dated "DEA NBART scale" note stating the scale and offset found and their source.
- [ ] Live test marked `live`: the check scores the Thomsons polygon on the newest pass with a matching DEA ARD item and reports measured and reference medians.

## Implementation Plan

# st-8c11 plan: NDVI check against DEA Sentinel-2 NBART

Worktree: `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-8c11` (branch `story/st-8c11`, clean, at e7e1d9a).

## Story pointers checked against the code

- `src/wetland_change/verify/ndvi.py` does not exist yet. `src/wetland_change/verify/run.py::verify_run` exists. It wires checks through `_verify_scene` with injectable lookups (`wo_lookup`, `wo_reader_factory`, `pixel_checker`) and `_guard`/`_error_check`. `verify/wo.py` is the precedent to copy: DEA STAC POST search, `DEA_STAC`, `dea_reader()` (unsigned, `AWS_REGION=ap-southeast-2`), s3 to https href mapping, and a grid-transform equality check.
- `ndvi_median` is an `ObservationRow` column (`stats.summarise`). It is the median of `indices.ndvi(nir, red)` over `clear_mask(scl, green, red, nir, swir16) & inside`. It is stored per item at `outputs.geoparquet.observation_path(year, tile, item_id)`.
- `tests/test_verify.py` has an autouse `_no_network` fixture that only patches `wetland_change.verify.run.open_client`. A new default DEA lookup would hit the network in the offline suite unless the fixture also patches it, so `tests/test_verify.py` is touched even though the story's `touches` list leaves it out.
- AGENTS.md rule: every dataset gets a `data/SOURCES.md` row in the commit that first uses it, so a DEA ARD row is added.

## DEA facts probed live on 2026-10-30

- DEA STAC search over Thomsons for 2026-09-01 to 2026-10-30 returned 15 items in `ga_s2am_ard_3`, `ga_s2bm_ard_3` and `ga_s2cm_ard_3`, all with `odc:region_code` 50HLK. `dea:dataset_maturity` is `final` up to 2026-10-17 and `nrt` from 2026-10-22. DEA's word for provisional is `nrt` (DEA also uses `interim`). Preference order is final, then interim, then nrt.
- Assets `nbart_red` (band04) and `nbart_nir_1` (band08) are 10 m, int16, nodata -999 and `proj:code` EPSG:32750, with transform origin (300000, 6500020). That is identical to the Earth Search 50HLK B03/B04/B08 grid. `oa_fmask` is 20 m. The 2026-10-29 item has no item-level `proj:epsg`, and its item-level `proj:transform` is 20 m, so the EPSG must be read from the band assets' `proj:code`.
- Scale and offset:
  - STAC `raster:bands` for the nbart assets carries only `nodata` -999, `data_type` int16 and `unit` "1".
  - The ODC product YAML (`https://explorer.dea.ga.gov.au/products/ga_s2cm_ard_3.odc-product.yaml`) has dtype int16, units '1' and nodata -999, with no scale_factor. The dataset `.odc-metadata.yaml` and `.proc-info.yaml` have none either.
  - The COG band04 has no scale or offset tags: rasterio reports the GDAL defaults, 1.0 and 0.0.
  - The DEA Knowledge Hub page "DEA Surface Reflectance NBART (Sentinel-2C MSI)" (`https://knowledge.dea.ga.gov.au/data/product/dea-surface-reflectance-nbart-sentinel-2c-msi/`) states "Valid data range [1,10000]" and "For all 'nbart_' bands, Surface Reflectance is scaled between 0 and 10,000".
  - So the scale is 1e-4 and the offset is 0. NDVI does not change under a pure scale, so only the zero offset matters.
- Same acquisition: the Earth Search `s2:product_uri` `S2C_MSIL2A_20261027T021211_N0513_R060_T50HLK_...` and the DEA `sentinel:product_name` `S2C_MSIL1C_20261027T021211_N0513_R060_T50HLK_...` share tokens 0 (platform), 2 (sensing start), 4 (relative orbit) and 5 (tile).
- Probe on the fixture pass (2026-10-27, DEA item 155b809a, nrt) over the Thomsons box: the pipeline NDVI median was 0.5028 and the DEA NBART median on the same 63600 clear pixels was 0.4962 (difference 0.0066). There were no -999 pixels and the pixel correlation was 0.980.

## Design decisions

- **Clear-pixel mask:** the pipeline's SCL clear mask, the same pixels `ndvi_median` was computed over (`clear_mask(scl, green, red, nir, swir16) & inside`), minus pixels where either DEA band is -999. DEA fmask is not used. With identical pixels, a difference measures Sen2Cor L2A against NBART reflectance and not a cloud-mask disagreement. This choice is stated in the module docstring.
- **Per-polygon check `ndvi_vs_dea_nbart`:**
  - `measured` is the absolute difference and `threshold` is 0.05. It passes when diff <= 0.05.
  - `detail` carries `ndvi_median` (pipeline), `dea_ndvi_median`, `abs_diff`, `n_compared`, `n_dea_nodata`, `scale`, `offset`, `mask` and the DEA item, collection and maturity.
  - The check is skipped when the pipeline median is not finite or no pixels can be compared.
  - It fails with reason "crs differs" when the DEA item EPSG, DEA grid EPSG or scene grid EPSG is not the operation EPSG (32750), and with reason "grid differs" when the transforms differ.
- **Run-level check `ndvi_correlation_vs_dea_nbart`:** Pearson r between pipeline and DEA medians over the run's scored polygon rows. It passes when r > 0.95. It is skipped when there are fewer than 5 finite rows or r is undefined.
- **Item metadata:** an item whose `raster:bands` states a scale other than 1e-4, an offset other than 0, or nodata other than -999 raises `NbartMetadataError`. `_guard` reports that as "check did not run" with the error.
- **Stack reads:** the WO and NDVI checks share one `read_stack` per polygon through a per-polygon memo, so the scene is not read twice.

## Steps

1. **Batch 1, task A.** Create `src/wetland_change/verify/ndvi.py` with the constants, `NbartItem`, `NbartMetadataError`, `dea_https`, `parse_nbart_item`, `same_acquisition`, `select_nbart_item`, `find_nbart_item`, `nbart_reflectance`, `dea_ndvi_median`, `ndvi_median_check`, `ndvi_correlation_check` and `ndvi_scene_check`. Offline tests go in `tests/test_verify_ndvi.py`:
   - Medians 0.04 apart pass and 0.06 apart fail (AC1).
   - -999 pixels are excluded; the -999 pixels are the majority, so including them would move the median (AC1).
   - Correlation over 6 rows passes at r=0.972 and fails at r=0.937; 4 rows are skipped (AC2).
   - Item parsing, maturity preference, same-acquisition matching and the request body sent to DEA.
   - The scene check on the fixture stack: pass, crs differs, grid differs.
2. **Batch 2, task B.** Wire the checks into `src/wetland_change/verify/run.py`:
   - New `verify_run` parameters `nbart_lookup` (default resolved at call time to the module-global `find_nbart_item`) and `nbart_reader_factory=dea_reader`.
   - `stored_ndvi(store, scene)` reads the run's stored `ndvi_median` per polygon.
   - One NDVI check per overlapping polygon, a shared stack memo, and the run-level correlation check after the scene loop when the run has scenes.
   - Tests in `tests/test_verify.py`: extend `_no_network`; an injected NBART item passes against stored rows; no DEA item, lookup error and missing observation row each give a skipped check; the stack is read once per polygon; `stored_ndvi` works.
3. **Batch 2, task C.** Live test, marked `live`, in `tests/test_verify_ndvi.py`. It finds the newest Earth Search c1 50HLK pass over Thomsons in the last 60 days that has a matching DEA ARD item, then scores the Thomsons box with `ndvi_scene_check` on the stored-equivalent `summarise(...).ndvi_median`. It prints and records the measured and reference medians, satisfying AC4. Append a dated "DEA NBART scale" note to `LEARNINGS.md` (AC3) and a DEA ARD row to `data/SOURCES.md`.

## Verification (AGENTS.md order)

```
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src scripts
uv run pytest -q
uv run pytest -q -m live tests/test_verify_ndvi.py -s   # task C, needs network
```

## Implementation Notes

## Questions
