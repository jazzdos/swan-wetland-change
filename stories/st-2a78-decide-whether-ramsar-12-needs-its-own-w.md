---
id: st-2a78
title: Decide whether ramsar-12 needs its own water setting
type: task
priority: P3
depends_on: []
discovered_from: st-7047
touches: [config/pipeline.toml, LEARNINGS.md]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

st-7047 (docs/research/2026-11-06-ramsar-12-gap.txt, LEARNINGS.md 'ramsar-12 wet area gap (2026-11-06)') found the global MNDWI -0.1 setting over-calls water on ramsar-12 (Peel-Yalgorup) against DEA WO: G1 supported (thresholds -0.05 to +0.15 keep abs gap <= 5 pp on all 12 measured rows, lowest mean abs gap at +0.05), G3 edge ring over-represented in pipeline-only wet pixels, G4 67 percent of those pixels are SCL class 4 or 5, G5 water_ha_index above water_ha_scl on 296 of 299 stored rows. Changing a polygon's water setting is an ADR 0005 calibration decision, out of scope for st-7047, which only decided the exit code.

## Acceptance Criteria

- [ ] A pre-registered rule for choosing ramsar-12's setting is in LEARNINGS.md before any measurement
- [ ] An ADR records the chosen setting (or the decision to keep the global one) with sha256-pinned evidence and a test in tests/test_config.py
- [ ] If a per-polygon override is added
- [ ] config/pipeline.toml carries it and the gates pass

## Implementation Plan

## Implementation Notes

## Questions
