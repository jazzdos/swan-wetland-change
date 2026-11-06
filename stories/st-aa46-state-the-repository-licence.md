---
id: st-aa46
title: State the repository licence
type: chore
priority: P2
depends_on: []
discovered_from: st-ff89
touches: [LICENSE, pyproject.toml, README.md, tests/test_repo_hygiene.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

The repository has no LICENSE file, no license field in pyproject.toml and no code licence statement in README.md (README.md:116-131 lists data licences only). The STAC collection declares CC-BY-SA-4.0 for data outputs (src/wetland_change/stac/catalogue.py:43), which does not cover the code. The licence choice is Jarrod's. Options include MIT, Apache-2.0 and BSD-3-Clause for permissive terms, or a copyleft licence such as GPL-3.0 or AGPL-3.0; the CC BY-SA 4.0 data outputs are separate from the code licence either way. Found by the st-ff89 reproducibility audit, which fixes nothing.

## Acceptance Criteria

- [ ] A LICENSE file exists at the repository root with the licence text Jarrod chose.
- [ ] pyproject.toml has a license field that names the same licence.
- [ ] README.md states the code licence and separately the CC BY-SA 4.0 and CC BY 4.0 terms of the data and outputs.
- [ ] A test asserts that LICENSE exists and that the pyproject.toml license field is set.
- [ ] The four verification gates pass.

## Implementation Plan

## Implementation Notes

- 2026-11-06T04:27:19.424Z: Decision: Jarrod chose MIT on 2026-11-06. Use the standard MIT text with 'Copyright (c) 2026 Jarrod Baker'. The CC BY-SA 4.0 data outputs and CC BY 4.0 DEA inputs stay as they are.

## Questions
