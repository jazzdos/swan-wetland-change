# swan-wetland-change

Scheduled, incremental wetland change detection for the Swan Coastal Plain
Ramsar sites from Sentinel-2 Collection 1 Cloud-Optimized GeoTIFFs on
Earth Search. Outputs are GeoParquet observations per wetland per scene
and a STAC catalogue. Every stage is verified against an independent
known-good reference. Design and verification matrix:
`docs/plans/2026-10-29-swan-wetland-change-design.md`.

## Setup

```
uv sync
uv run python scripts/fetch_aoi.py
uv run wetland-change discover --config config/pipeline.toml
uv run wetland-change score --start 2022-01-01 --end 2026-10-29  # after a backfill
```

## STAC catalogue

`wetland-change run` rebuilds the STAC catalogue and
`stac/swan-wetland-change/items.parquet` from the ledger after writing the
run manifest. `wetland-change build-catalogue` rebuilds the same files
without running a scene. Order after a run: `verify`, then
`build-catalogue`. The `verification` item asset only appears once
`build-catalogue` (or the next `run`) executes after `verify`, because the
catalogue links only files that already exist in the output store. The
`changes` asset follows the same rule.
