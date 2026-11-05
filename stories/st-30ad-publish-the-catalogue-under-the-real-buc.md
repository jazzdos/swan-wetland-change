---
id: st-30ad
title: Publish the catalogue under the real bucket URL
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [config/pipeline.toml, infra/README.md, tests/test_config.py, .github/workflows/pipeline.yml, src/wetland_change/stac/catalogue.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

config/pipeline.toml:46 sets catalogue.base_url to https://example.invalid/swan-wetland-change and nothing overrides it, so every link and asset href in the first published catalogue points at a reserved TLD. infra/README.md never says to set it from the bucket_url output. tests/test_config.py pins the placeholder. Separately the catalogue is built before verify writes its report, so each report is linked one run late. Fix before enabling the workflows. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 4.

## Acceptance Criteria

- [ ] Every link and asset href in the published catalogue starts with the bucket_url output of infra
- [ ] infra/README.md lists setting catalogue.base_url from the bucket_url output as a deploy step
- [ ] tests/test_config.py no longer pins the example.invalid placeholder
- [ ] A run's verification asset is linked in the catalogue written by the same workflow run

## Implementation Plan

## Implementation Notes

## Questions
