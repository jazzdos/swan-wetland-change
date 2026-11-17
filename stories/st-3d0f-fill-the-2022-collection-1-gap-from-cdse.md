---
id: st-3d0f
title: Fill the 2022 Collection 1 gap from CDSE baseline 05.10
type: epic
priority: P1
depends_on: []
touches: []
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

Fill the Earth Search Collection 1 gap of 2022-01-01 to 2022-11-30 (spike S4 in LEARNINGS.md) with Copernicus Data Space (CDSE) `sentinel-2-l2a` products, ESA's 2024 reprocessing at baseline 05.10. Jarrod directed "use for 2022 gap" on 2026-11-16 and approved the design on 2026-11-17. The design doc stays uncommitted (kit:brainstorming rule) at `/Users/jarrodbaker/Documents/swan-wetland-change/docs/plans/2026-11-17-cdse-2022-gap-design.md`, untracked in the main checkout and absent from story worktrees; ADR 0018 (first child) carries its substance into the repo. The design names the record ADR 0018: number 0017 went to the private-bucket decision (`docs/decisions/0017-private-output-bucket-again.md`) on 2026-11-17, and 0014 and 0015 are held by st-b6bf and st-dd0d.

Facts measured 2026-11-16 and 2026-11-17:

- CDSE STAC `https://stac.dataspace.copernicus.eu/v1`, collection `sentinel-2-l2a`, AOI bbox, cloud below 20 percent: 187 items on 186 acquisitions from 2022-01-01 to 2022-11-30, all N0510. Earth Search c1 holds 1 of those acquisitions (50JLL); the fill is 185 (50HLJ 25, 50HLK 33, 50HMJ 28, 50HMK 30, 50JLL 34, 50JML 35). Acquisition S2B 2022-02-25 R060 T50HMK has two products.
- Band assets `B03_10m`, `B04_10m`, `B08_10m`, `B11_20m`, `SCL_20m` are JP2 on `s3://eodata/...` with `raster:scale` 0.0001, `raster:offset` -0.1, `nodata` 0, `proj:code`, `proj:transform`, `file:size` and `file:checksum` (multihash prefix 1620, read as sha3-256). There is no `raster:bands` array and no item-level `proj:code`. `product_metadata` is MTD_MSIL2A.xml (BOA_QUANTIFICATION_VALUE 10000, BOA_ADD_OFFSET -1000, PROCESSING_BASELINE 05.10).
- Windowed `/vsis3/` JP2 reads take about 29 s per 10 m window; downloading one scene's five bands takes about 31 s for 412 MB, and local reads are fast. The backfill downloads per scene.
- From 2022-12-01 to 2023-02-28 Earth Search holds 80 items at baseline 05.09 and CDSE 81 at N0510; all 80 Earth Search acquisitions have a CDSE counterpart and no product name is shared.

Decisions: stage the backfill now in local roots and merge into the store only after st-b6bf's decision files are committed; a separate CDSE adapter under `src/wetland_change/sources/cdse/` feeds the unchanged `process_scene`; an overlap test (rules O1 to O3, pre-registered in LEARNINGS.md) gates the merge; ADR 0018 is accepted only on Jarrod's approval after the overlap result.

Children, in dependency order: ADR 0018 and the overlap pre-registration; CDSE discovery and adapter; eodata downloader; `backfill-cdse` command; catalogue provenance; README; overlap comparison script; overlap run; gap-row check script; staged gap run; pre-registration of the extended-history re-test; `spearman_min` recalibration (after st-b6bf); merge into the store; re-test of H1 to H4. Nothing enters the shared output store before st-b6bf's decision files are committed and Jarrod accepts ADR 0018.

## Acceptance Criteria

- [ ] Every child story of this epic is done.
