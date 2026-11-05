---
id: st-5241
title: Make the daily run converge on an empty or far-behind output root
type: bug
epic: st-f849
priority: P1
depends_on: []
touches: [src/wetland_change/pipeline.py, src/wetland_change/config.py, config/pipeline.toml, infra/README.md, tests/test_pipeline.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

With no ledger, watermark returns None, so discovery has no created or datetime bound and finds at least 1147 scenes. run_once writes the ledger only after the whole loop (src/wetland_change/pipeline.py:319) and pipeline.yml cancels the job at 120 minutes, so a cancelled run leaves observation files with no ledger row and the next run repeats the same oldest scenes. backfill_once checkpoints per scene and run_once does not. A ledger seeded from the backfill lets the first run skip those items but no document describes that. Fix before enabling the workflows. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 1.

## Acceptance Criteria

- [ ] run_once checkpoints the ledger after each scene so a cancelled run keeps its finished scenes
- [ ] run on a ledger with no daily watermark bounds discovery to a configured lookback window
- [ ] infra/README.md documents seeding the S3 output root from the backfill before the first scheduled run
- [ ] A test interrupts run_once after some scenes and shows the next run starts after the last finished scene

## Implementation Plan

## Implementation Notes

## Questions
