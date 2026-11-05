---
id: st-06a8
title: Write the reviewer README
type: chore
priority: P2
depends_on: [st-a868, st-ec32, st-e766]
touches: [README.md, tests/test_readme.py]
exclusive: false
created: 2026-10-29
updated: 2026-11-05
---
## Description

Success criterion 6 (design): a README that explains the design choices and the verification matrix to a reviewer. `README.md` is a 16-line stub today.

Sources: the design document (purpose and decisions, architecture, matrix, challenges), decisions 0001 to 0005 in `docs/decisions/`, LEARNINGS.md findings (SCL overview mode resampling, Planetary Computer faulty copies, the Collection 1 2022 gap) and the handoffs.

Cover: what the pipeline does; architecture and run stages; data sources and licences; the verification matrix with each row's implementing module or test and its status; running locally (`fetch_aoi`, `run`, `backfill`, `score`, `verify`); querying observations with DuckDB using one glob over the hive partitions; deployment (`infra/README.md`, repository variables); and known limitations. Write plain, factual prose.

## Acceptance Criteria

- [ ] README.md has headings for design choices, architecture, verification matrix, running locally, querying with DuckDB, deployment and limitations, checked by a test.
- [ ] Every row of the design's verification matrix appears in the README table with its implementing module or test, or "not implemented" and the reason.
- [ ] `tests/test_readme.py` extracts the README's DuckDB query and runs it against observation files written from the offline fixture, returning at least one row.
- [ ] A test runs every `wetland-change` subcommand named in the running-locally section with `--help` and each exits 0.

## Implementation Plan

## Implementation Notes

- 2026-11-05T08:55:00.595Z: Implemented by cloud session https://claude.ai/code/session_01FNRugN6kQycKSHYeD5rakG as dd58765. Same local gates as st-7432 on the combined merge. Restoring the old README fails all 6 collected tests in tests/test_readme.py. Backfill verdicts, H4 rhos, ADR 0002 and 0005 figures, the S9 and dea-tools figures, the first verify counts, cron times and SCL classes were checked by hand against their cited sources.

## Questions
