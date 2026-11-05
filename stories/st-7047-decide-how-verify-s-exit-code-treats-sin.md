---
id: st-7047
title: Decide how verify's exit code treats single failures on the live water check
type: task
priority: P2
depends_on: [st-9aff]
discovered_from: st-9aff
touches: [src/wetland_change/verify/checks.py, src/wetland_change/cli.py, docs/decisions/**, LEARNINGS.md]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

With the wet area clause from st-9aff (ADR 0006), verify exits 3 if any water_vs_dea_s2_wo check fails, and a date has 29 to 45 polygon-scene checks. On the 6 dates with every polygon measured (docs/research/2026-11-05-wet-area-gap.csv), dates with a failing row go from 2 to 6, so the daily pipeline job would end red on most days, which is the same problem st-b602 raises for the Spearman check. ramsar-12 is 5 of the 9 rows that fail only the clause, with the pipeline wetter than WO by 5.38 to 6.82 pp on those rows, cause not investigated. The markdown report and CLI line show only agreement and its threshold, so a wet-area-only failure appears as a failure with measured above threshold. Out of scope for st-9aff, whose pre-registered rule put the clause in Check.passed without changing the exit logic.

## Acceptance Criteria

- [ ] An ADR states whether one polygon failing the live water check on one scene fails the run
- [ ] and gives the share of the measured dates that would fail under that choice
- [ ] The markdown report and CLI line show the wet area gap when a live water check fails on wet area alone
- [ ] LEARNINGS.md records the cause of the ramsar-12 gap
- [ ] or what was checked if no cause was found

## Implementation Plan

## Implementation Notes

## Questions
