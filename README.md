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
```
