---
id: st-8856
title: Add the DEA CC BY 4.0 attribution to the published files
type: feature
priority: P2
complexity: hard
depends_on: []
discovered_from: st-1a9c
touches: [src/wetland_change/outputs/provenance.py, src/wetland_change/stac/catalogue.py, src/wetland_change/verify/checks.py]
exclusive: false
created: 2026-11-14
updated: 2026-11-14
---
## Description

st-1a9c (`docs/research/2026-11-14-public-release-licences.md`, term T1) found that the published files carrying Geoscience Australia DEA data under CC BY 4.0 carry no attribution.

- Observation Parquet holds DEA Waterbodies v3 polygons, their uids and the DEA Water Observations agreement score. Change files hold the same polygons. The verification JSON holds values derived from DEA Water Observations, DEA Sentinel-2 ARD NBART and the DEA Waterbodies time series.
- The Parquet footer keys (`src/wetland_change/outputs/provenance.py`, `FOOTER_KEYS`) and the report payload (`src/wetland_change/verify/checks.py`, `write_report`) have no licence or attribution field. The STAC collection (`src/wetland_change/stac/catalogue.py`, `PROVIDERS`) names Geoscience Australia as licensor with a homepage only.
- CC BY 4.0 section 3(a) requires the attribution and copyright notice the licensor supplies (the DEA product page gives "© Commonwealth of Australia (Geoscience Australia)" and citations), a licence notice with its URI, a link to the material, and an indication of modification. Section 3(a)(2) lets a link to a resource holding these satisfy it.
- Files already in the bucket lack it. `src/wetland_change/outputs/footer_backfill.py` is the existing footer rewrite path.

Constraints: no agent makes an AWS call or reads any object in the output store (st-b6bf and st-dd0d pre-registrations in `LEARNINGS.md`); the backfill of existing bucket files is documented for the operator and not run by an agent. Build agents do not commit or push; the orchestrator commits on the story branch.

Blocks ADR 0011 step 3 (opening the bucket).

## Acceptance Criteria

- [ ] Observation and change Parquet files carry the CC BY 4.0 section 3(a) DEA attribution, directly or by a link, and a test reads it back from a written file
- [ ] The verification JSON carries it, and a test asserts it
- [ ] The STAC collection carries it and a link to the licence text, and the catalogue still validates
- [ ] Existing bucket files get it through a documented backfill path that the operator runs
- [ ] `uv run pytest -q` passes
