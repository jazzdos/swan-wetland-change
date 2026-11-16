---
id: st-abcb
title: Correct the README statements on DBCA-010 attribution scope and the backfill gate
type: bug
priority: P2
depends_on: []
discovered_from: st-22f1
touches: [README.md, tests/test_dbca_licence_text.py, tests/test_readme.py]
exclusive: false
created: 2026-11-15
updated: 2026-11-16
---

## Description

The st-22f1 build review approved the change with minor findings that were not fixed, checked against main at cbe0510. (1) README.md:498-499 says the attribution backfill runs before ADR 0011 step 3; ADR 0011 is superseded by ADR 0016 and the backfill is precondition 2 of ADR 0016 'Preconditions of the apply'. (2) README.md:361 and :556 say the catalogue holds no DBCA-010 material, while :182 lists catalogue files as DBCA-derived CC BY-NC 4.0 outputs and the collection carries dbca_attribution; the intended statement is that add-dbca-attribution does not scan the catalogue because build-catalogue writes the attribution. (3) README.md:201-204 says the published files carry the DBCA-010 attribution, but the ledger, run manifests, verification JSON, STAC catalog and write index carry none. (4) README.md:186 is a 105-character line; :182-188 should be rewrapped. (5) tests/test_dbca_licence_text.py NEEDLE r'by[-_]sa' misses 'Attribution-ShareAlike', 'BY SA' and non-ASCII hyphens. Out of scope for st-22f1 because it was merged before the findings were triaged.

## Acceptance Criteria

- [ ] README names ADR 0016 'Preconditions of the apply' step 2 as the gate of the attribution backfill and no longer cites ADR 0011 step 3 there
- [ ] README states which published file kinds carry the DBCA-010 attribution (observation and change files
- [ ] the STAC collection and items) and which do not
- [ ] with no contradiction between Data sources and licences
- [ ] Running locally and Attribution backfill
- [ ] and a test pins it
- [ ] The licence-text scan matches ShareAlike
- [ ] BY SA and non-ASCII hyphen variants
- [ ] with any new allowlist entries asserted present
- [ ] and still passes
- [ ] uv run ruff check src tests scripts
- [ ] uv run ruff format --check src tests scripts
- [ ] uv run mypy src scripts and uv run pytest -q all exit 0

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-abcb, HEAD ebea401)

README line numbers have moved; statements located by content:
- Data sources and licences (`## Data sources and licences`): the DBCA paragraph (starts "separate terms. Outputs derived from the DBCA-010 Ramsar polygons") has one 105-char line ("DBCA (`docs/research/2026-11-14-public-release-licences.md`). The DEA inputs and references (Waterbodies,"), and the paragraph "The published files carry the DEA attribution ... They also carry the DBCA-010 attribution, term T3" overclaims.
- Running locally: bullet `add-dbca-attribution` says "Verification reports, ledger files and the catalogue hold no DBCA-010 material and are not scanned."
- Attribution backfill (`### Attribution backfill`, under Deployment): "The backfill runs before ADR 0011 step 3 (`docs/decisions/0011-private-output-bucket.md`)". ADR 0016 'Preconditions of the apply' step 2 is "st-22f1's backfill job has run against the output store"; ADR 0011 step 3 is the infra change. The `add-dbca-attribution` bullet there repeats "Verification reports, ledger files and the catalogue hold no DBCA-010 material".
- Ground truth in code: `src/wetland_change/stac/catalogue.py` writes `dbca_attribution` on the collection (line ~252) and the items (items.parquet column); the root `pystac.Catalog` (catalog.json) gets none; observation and change footers carry it (`outputs/geoparquet.py`, `outputs/changes.py`). Ledger, run manifests, verification JSON and Markdown report, and `stac/write-index.json` carry none.
- `tests/test_dbca_licence_text.py`: `NEEDLE = re.compile(r"by[-_]sa", re.IGNORECASE)`, `ALLOWED` dict asserted present by `test_no_live_file_names_the_sharealike_licence` (path in files, snippet count == 1).
- `tests/test_readme.py` has `_section(text, heading, level)` and `_readme()`; existing Backfill tests do not touch the ADR citation.

## Steps

1. README.md (task A, README + tests/test_readme.py, test first)
   a. Add the new tests to `tests/test_readme.py` (below), run them, confirm they fail for the right reasons.
   b. Edit README.md:
      - Rewrap the DBCA paragraph in `## Data sources and licences` to lines of at most 80 characters, text unchanged.
      - Replace the sentence "They also carry the DBCA-010 attribution, term T3 of the same document." with: "The DBCA-010 attribution, term T3 of the same document, is carried by the observation and change files (footer key `dbca_attribution`) and by the STAC collection and items. The ledger files, run manifests, verification JSON and Markdown reports, the STAC root `catalog.json` and `stac/write-index.json` carry none."
      - In both `add-dbca-attribution` bullets (Running locally and Attribution backfill) replace "Verification reports, ledger files and the catalogue hold no DBCA-010 material and are not scanned." with: "It does not scan verification reports, ledger files or run manifests, and it does not scan the catalogue: `build-catalogue` writes `dbca_attribution` to the STAC collection and items."
      - In Attribution backfill replace "The backfill runs before ADR 0011 step 3 (`docs/decisions/0011-private-output-bucket.md`), by one of two routes." with: "The backfill is the gate of the public-read apply: step 2 of 'Preconditions of the apply' in ADR 0016 (`docs/decisions/0016-public-read-output-bucket.md`), which supersedes ADR 0011. It was met on 2026-11-15 (ADR 0016, 'Apply'). It runs by one of two routes." Keep the following sentences intact.
      - No em dashes; flat prose. Do not touch any licence claim (CC BY-NC 4.0 stays; confirmation stays parked as st-4c87).
   c. Tests pass.
2. tests/test_dbca_licence_text.py (task B, test first)
   a. Add a failing unit test for the needle with positive and negative examples; widen NEEDLE; run the scan; add each newly hit live occurrence that states no DBCA-010 licence to `ALLOWED` (exact snippet, asserted present once by the existing loop); fix the docstring count.
3. Run the four gates in order.

## What each test proves
- `test_dbca_attribution_scope_is_stated_in_the_data_sources_section`: the licences section lists every file kind that carries and does not carry the attribution.
- `test_dbca_attribution_scope_does_not_contradict_across_sections`: the README never says the catalogue holds no DBCA-010 material; Running locally and Attribution backfill both say `build-catalogue` writes the attribution and the command does not scan the catalogue.
- `test_attribution_backfill_names_the_adr_0016_gate`: the backfill section cites ADR 0016 'Preconditions of the apply' step 2 and no longer cites ADR 0011 step 3.
- `test_licence_needle_matches_sharealike_variants`: widened NEEDLE catches `BY-SA`, `by_sa`, `BY SA`, `BY‑SA` and other Unicode hyphens, `Attribution-ShareAlike`, `Share Alike`, and ignores `by same`, `Dubai SA`, `bypass a`.
- `test_no_live_file_names_the_sharealike_licence` (existing): still passes with the wider needle and fails if an allowlisted snippet disappears.

## Implementation Notes

## Questions
