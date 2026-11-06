---
id: st-aa46
title: State the repository licence
type: chore
priority: P2
depends_on: []
discovered_from: st-ff89
touches: [LICENSE, README.md, pyproject.toml, tests/test_licence.py]
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

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-aa46)

- No LICENSE file at the repo root; `pyproject.toml` `[project]` has no `license` field (build backend is hatchling, unpinned, so a PEP 639 SPDX string `license = "MIT"` is supported).
- README.md `## Data sources and licences` (line 143) holds a data-only table, then "URLs, fetch dates ... Rows derived from the Ramsar polygons inherit CC BY-SA 4.0." The `## Limitations` section has a stale bullet at lines 427-429 ("The repository has no licence file ... st-aa46, open ...") that must be removed once the licence lands.
- `src/wetland_change/stac/catalogue.py:43` `LICENSE = "CC-BY-SA-4.0"` is the data licence; it stays unchanged. Do not touch it.
- Decision (story note): MIT, standard text, "Copyright (c) 2026 Jarrod Baker". DBCA CC BY-SA 4.0 and DEA CC BY 4.0 data terms are unchanged.
- tests/test_readme.py REQUIRED_HEADINGS are unaffected if no heading is renamed. Existing tests in tests/ use `REPO = Path(__file__).parent.parent`; `tomllib` is available (python >= 3.12).

## Steps (TDD, single batch, single task)

1. Red: create `tests/test_licence.py` (below). Run `uv run pytest tests/test_licence.py -q`; all fail (no LICENSE, no field, no README text).
   - `test_licence_file_exists_with_mit_text`: `LICENSE` exists at repo root, starts with "MIT License", contains "Copyright (c) 2026 Jarrod Baker" and the phrase "Permission is hereby granted, free of charge". Proves the file the criterion requires exists and is the chosen licence.
   - `test_pyproject_license_field_is_set_and_matches_licence_file`: `tomllib` load of pyproject.toml; `project["license"]` is a non-empty str equal to "MIT", and LICENSE's first line is "MIT License". Proves the field is set and names the same licence as the file.
   - `test_readme_states_code_and_data_licences_separately`: README contains a "## Data sources and licences" section whose text mentions the code licence (MIT and `LICENSE`), "CC BY-SA 4.0" and "CC BY 4.0"; and README no longer contains "no licence file". Proves the README states the code licence separately from the data terms and the stale limitation is gone.
2. Green: create `/LICENSE` with the standard MIT text (year 2026, holder Jarrod Baker).
3. Green: in `pyproject.toml` `[project]`, after `requires-python`, add `license = "MIT"` and `license-files = ["LICENSE"]`.
4. Green: README.md. At the top of `## Data sources and licences`, before the table, add a paragraph: the code is released under the MIT licence (`LICENSE`); that licence covers source code only. Data and outputs carry their own terms: outputs derived from the DBCA-010 Ramsar polygons (observation, change and catalogue files, declared as CC-BY-SA-4.0 in the STAC collection) are CC BY-SA 4.0; DEA inputs and references (Waterbodies, Water Observations, ARD) are CC BY 4.0; Sentinel-2 data follow the Copernicus terms. Keep the table and the trailing "Rows derived from the Ramsar polygons inherit CC BY-SA 4.0." sentence. Delete the stale Limitations bullet (README.md lines 427-429, from "- The repository has no licence file" through "declares CC-BY-SA-4.0 for the data only.").
5. Run the four gates in order, one command per line, from the worktree: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. If `uv sync`/build fails on the `license` string (old hatchling), report it rather than pinning anything silently.
6. Commit on the story branch (message ends with the attribution line from the session reminder).
## Orchestrator amendments

These override the text above where they differ.

1. Agents commit nothing, including the commit in step 6; the orchestrator commits after the run. Uncommitted work at the end of a task is expected and is not a defect. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**.
2. Never call AWS for the project's own bucket, never run terraform plan or apply, never run compaction against S3, and never run `-m live` tests. Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data.
3. Gates, one command each, judged by exit code: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`, `GITHUB_ACTIONS=true uv run pytest -q`. Never clear addopts for a gate; for a count use `-o addopts="-m 'not live'"`.
4. After editing pyproject.toml run `uv lock --check` (or `uv lock` if it reports the lock is stale) and say in the summary whether uv.lock changed. Also run `uv build --wheel --out-dir <a temp dir outside the repo>` once and confirm the wheel's METADATA has `License-Expression: MIT` and includes the LICENSE file; delete the temp dir afterwards. If the build backend rejects the PEP 639 fields, report the error text and do not pin or downgrade anything.
5. Docs are flat factual prose with no em dashes.

## Implementation Notes

- 2026-11-06T04:27:19.424Z: Decision: Jarrod chose MIT on 2026-11-06. Use the standard MIT text with 'Copyright (c) 2026 Jarrod Baker'. The CC BY-SA 4.0 data outputs and CC BY 4.0 DEA inputs stay as they are.
- 2026-11-06T06:32:03.760Z: Code is MIT (LICENSE, Copyright (c) 2026 Jarrod Baker); pyproject license = "MIT" with license-files; README separates code licence from data terms (Ramsar-derived outputs CC BY-SA 4.0, DEA CC BY 4.0, Sentinel-2 Copernicus terms); stale limitation removed. STAC catalogue data licence unchanged. Commit e919ad0; gates pass, 910 passed. Copyright holder name taken from Jarrod's choice; change LICENSE if a different legal name is wanted.

## Questions
