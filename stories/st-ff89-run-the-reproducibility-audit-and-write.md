---
id: st-ff89
title: Run the reproducibility audit and write the Milestone 2 handoff
type: chore
priority: P3
depends_on: [st-06a8, st-b983]
touches: [docs/research/**, docs/handoffs/**]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Success criterion 5 (design): run the `geospatial:reproducibility-audit` skill over the repository as the final gate, and write the Milestone 2 handoff. Fix nothing in this story; file a discovered story for each failing audit item with `story create --discovered-from <this id>`.

The handoff states the project state, verification status per matrix row, deviations, and the follow-ups the board could not do:

- AWS account, bucket and `infra` apply.
- GitHub repository creation and its repository variables.
- Spikes 5 (runner dry run), 6 (static catalogue in stac-browser) and 7 (DuckDB over S3).
- The four-week unattended run.
- Codename registry and inventory rows.
- DBCA-010 licence confirmation.
- The CDSE option for the 2022 gap, which needs a Copernicus account.

## Acceptance Criteria

- [ ] `docs/research/<date>-reproducibility-audit.md` lists every audit item with pass or fail.
- [ ] Each failing audit item cites a story id filed with `--discovered-from` this story.
- [ ] `docs/handoffs/<date>-milestone-2.md` exists and lists each follow-up named in the Description.

## Implementation Plan

## Implementation Notes

## Questions
