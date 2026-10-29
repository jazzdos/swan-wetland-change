# swan-wetland-change

Scheduled, incremental NDWI and NDVI change detection for the Swan Coastal
Plain Ramsar wetlands from Earth Search Sentinel-2 Collection 1 COGs, with
every output verified against an independent reference.
Design: `docs/plans/2026-10-29-swan-wetland-change-design.md`.

## Verification

Run in this order, one command per line, so a failure names its step:

```
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src scripts
uv run pytest -q
```

Live tests (`-m live`) hit Earth Search, Planetary Computer and DEA. Run them
before a handoff, never in the default suite.

A deliberately red test is marked `xfail(strict=True)`.

## Layout

```text
CLAUDE.md  AGENTS.md  README.md  LEARNINGS.md  pyproject.toml  uv.lock
config/pipeline.toml  src/wetland_change/  tests/  scripts/  scratch/
data/SOURCES.md  data/external/ (untracked)  outputs/ (untracked)
docs/{plans,decisions,handoffs,research}/
```

## Rules

- Every dataset gets a row in `data/SOURCES.md` (URL, licence, fetch date,
  checksum, CRS, redistribute_public) in the commit that first uses it.
- Reflectance is always DN times scale plus offset read from the item's
  `raster:bands`, never a hard-coded constant, and checked against the ESA
  product XML at run time.
- Only collection `sentinel-2-c1-l2a`. Never mix in `sentinel-2-l2a`.
- Record the source CRS, operation CRS (EPSG:32750) and units with every
  output.
- Pre-registered hypotheses live in `LEARNINGS.md` before a run tests them.

## Locked decisions

- Sentinel-2 Collection 1 only; Landsat is requester-pays on Earth Search.
- Ramsar sites (DBCA-010, CC BY-SA 4.0) are the reporting unit; DEA
  Waterbodies polygons (CC BY 4.0) are the verification unit.
- Water area is stored three ways: calibrated index, SCL class 6, and the
  DEA Water Observations agreement score.
