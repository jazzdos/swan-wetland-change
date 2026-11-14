---
id: st-d5c1
title: Add the Copernicus Sentinel data notice to the published files
type: feature
priority: P2
complexity: hard
depends_on: []
discovered_from: st-1a9c
touches: [src/wetland_change/outputs/provenance.py, src/wetland_change/stac/catalogue.py, src/wetland_change/verify/checks.py, src/wetland_change/ledger.py]
exclusive: false
created: 2026-11-14
updated: 2026-11-14
---
## Description

st-1a9c (`docs/research/2026-11-14-public-release-licences.md`, term T2) found that no published file carries the notice the Copernicus Sentinel data legal notice requires on distribution: "Contains modified Copernicus Sentinel data [Year]" (https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice).

- Observation and change Parquet hold values computed from Earth Search `sentinel-2-c1-l2a` reflectance. The STAC items and the ledger hold Earth Search item footprints and properties. The verification JSON holds values read from Earth Search, Planetary Computer and Copernicus Data Space.
- The STAC collection (`src/wetland_change/stac/catalogue.py`, `PROVIDERS`) names ESA as producer and licensor but carries no notice.
- Writers: `src/wetland_change/outputs/provenance.py` (Parquet footer), `src/wetland_change/stac/catalogue.py`, `src/wetland_change/verify/checks.py` (`write_report`), `src/wetland_change/ledger.py`.

Constraints: no agent makes an AWS call or reads any object in the output store (st-b6bf and st-dd0d pre-registrations in `LEARNINGS.md`). Build agents do not commit or push; the orchestrator commits on the story branch.

Blocks ADR 0011 step 3 (opening the bucket).

## Acceptance Criteria

- [ ] Observation and change Parquet footers carry the notice with the acquisition year or years, and a test reads it back
- [ ] The STAC collection carries the notice, and the catalogue still validates
- [ ] The ledger and verification JSON carry the notice (for example in file metadata), and a test asserts it
- [ ] `uv run pytest -q` passes
