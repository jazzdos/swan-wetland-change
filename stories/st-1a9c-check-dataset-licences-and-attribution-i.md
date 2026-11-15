---
id: st-1a9c
title: Check dataset licences and attribution in published files for public release
type: spike
priority: P2
complexity: hard
depends_on: []
touches: [data/SOURCES.md, docs/research/2026-11-14-public-release-licences.md, tests/test_public_release_licences.py]
exclusive: false
gates: [test]
created: 2026-11-14
updated: 2026-11-15
parked_complexity: hard
---
## Description

Jarrod approved public access to the output bucket on 2026-11-14. `docs/decisions/0011-private-output-bucket.md`, section "Reopening public access", lists the steps in order. This story is step 2: every dataset in `data/SOURCES.md` must have `redistribute_public` true, and the attribution and ShareAlike terms must be met in the published files, before the bucket is opened. It produces evidence only. The story that writes the superseding ADR and the infra change depends on this one, and the decision that a licence is acceptable stays Jarrod's.

What is known:

- `data/SOURCES.md` has one row per dataset (URL, licence, fetch date, checksum, CRS, `redistribute_public`). The DBCA-010 Ramsar Sites row records "CC BY-SA 4.0 (data.gov.au)" and is fetched from the SLIP public services REST endpoint. data.gov.au is not the primary source.
- `docs/handoffs/2026-11-06-milestone-2.md`, "Follow-ups the board could not do", lists "DBCA-010 licence confirmation" as open: Jarrod needs to confirm it is the licence that applies to redistribution, and the STAC collection and the README depend on it.
- `AGENTS.md` locked decisions: Ramsar sites (DBCA-010, CC BY-SA 4.0) are the reporting unit and DEA Waterbodies polygons (CC BY 4.0) are the verification unit.
- Published file kinds are written under `src/wetland_change/`: observation Parquet files with a provenance footer (st-2bfd, st-1b87), change rows, the STAC catalogue (catalog, collection, items; st-1990, st-a868), run manifests, the ledger and verification JSON. The repository licence was stated in st-aa46.

How to do it:

- Check the DBCA-010 licence with three `claim-verifier` agents in parallel, each trying to refute the claim against the primary source (the publisher's own catalogue entry and the terms of the service the data is fetched from). The claim: DBCA-010 Ramsar Sites is licensed CC BY-SA 4.0, and that licence applies to public redistribution of the data and of products derived from it. Promote on 2 of 3. Under Jarrod's model policy these run on opus at xhigh effort. Requests to outside services carry no user name, email or project name.
- For the other datasets, record the licence from the primary source with the URL and the date the page was fetched.
- Judge the published files from the writer code, the tests and offline test outputs only.

Blindness rules that bind this story (pre-registered in `LEARNINGS.md` for st-b6bf and st-dd0d):

- No object in the output store is read (observations, catalogue, run manifests, `verification/`). No AWS call is made.
- No `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md` is opened, and no `git diff`, `git log -p`, `git show` or search output that includes another one is read.
- No run log of a run newer than 43475454140 is opened.

Out of scope: changing any writer, `infra/`, any ADR (0016 belongs to the dependent story), `LEARNINGS.md`, and the GitHub repository's visibility. Build agents do not commit or push; the orchestrator commits on the story branch.

## Acceptance Criteria

- [ ] A dated note `docs/research/<date>-public-release-licences.md` lists, for each dataset whose data reaches a published file, the licence, the primary-source URL, the date that page was fetched and the `redistribute_public` value; any row whose value is not true is named as blocking
- [ ] Three claim-verifier agents check the DBCA-010 licence against its primary source and the note records each verdict with its source URL; with fewer than 2 of 3 confirming, the story is parked with the question for Jarrod
- [ ] The note states, for each kind of published file (observation Parquet, change rows, STAC catalog, collection and items, run manifests, ledger, verification JSON), which attribution and licence fields it carries, citing the writer file and line, and whether the CC BY-SA 4.0 attribution and ShareAlike terms and the CC BY 4.0 attribution terms are met
- [ ] Each unmet term is filed with `story create --discovered-from` and its id is listed in the note
- [ ] `data/SOURCES.md` matches the note for licence and `redistribute_public` on every row the note covers, and `uv run pytest -q` passes

## Implementation Plan

## Plan: st-1a9c O4 unpark pass, recording the DBCA-010 answer in the licence evidence (2026-11-15)

### Checked in the worktree

The worktree is `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-1a9c`, on branch story/st-1a9c at b090f5a, with a clean tree. The baseline `uv run pytest -q` exits 0.

- **Already on main (from 02276c1):**
  - `docs/research/2026-11-14-public-release-licences.md`: Promoted: no (0 of 3). DBCA-010 is `unconfirmed`, T3 and T4 are `deferred: question to Jarrod`, and every T1 and T2 cell still reads unmet.
  - `data/SOURCES.md` row 6 (DBCA-010): the `unresolved: ...` licence and `unconfirmed`.
  - `data/SOURCES.md` row 19 (ramsar_mini): `CC BY-SA 4.0 (...)`, `true`.
  - `tests/test_public_release_licences.py`: 9 tests.
- **T1 (st-8856) is met in every file kind it listed.** Verified in the writers on main:
  - observation Parquet: `src/wetland_change/outputs/geoparquet.py:119`
  - change rows: `src/wetland_change/outputs/changes.py:114`
  - STAC collection: `src/wetland_change/stac/catalogue.py:231`, plus the rel=license link to the CC BY 4.0 legal code at `:257`
  - verification JSON: `src/wetland_change/verify/checks.py:239`
- **T2 (st-d5c1) is met in every file kind it listed:**
  - observation Parquet: `geoparquet.py:120`
  - change rows: `changes.py:115`
  - STAC collection: `catalogue.py:233`
  - STAC items: `catalogue.py:133`
  - ledger: `ledger.py:192` and `:291`
  - verification JSON: `checks.py:241`, fed by `verify/run.py:557`
- **Tests read these back:**
  - `tests/test_geoparquet.py:358` and `:391`
  - `tests/test_change_outputs.py:929` and `:963`
  - `tests/test_catalogue.py:324`, `:339`, `:413`, `:423` and `:431`
  - `tests/test_ledger.py:1046` and `:1106`
  - `tests/test_verify.py:211` and `:271`
- **Offline rebuild from an empty ledger:** the collection license is still CC-BY-SA-4.0. The links are root, license (DEA CC BY 4.0), self and parent. The extra field is `dea_attribution`. `FOOTER_KEYS` is still the 9 provenance keys.
- **Text that still says DBCA-010 is CC BY-SA 4.0** (outside docs/decisions and the dated notes):
  - `src/wetland_change/stac/catalogue.py:59`
  - README lines 41, 135, 176-177, 184 and 197
  - the AGENTS.md locked decision
  - **`scripts/fetch_aoi.py:328`**, which prints the DBCA-010 SOURCES row as `CC BY-SA 4.0 (data.gov.au)`.

  st-22f1's touches list is `src/**`, `.github/workflows/backfill.yml`, `tests/**`, README.md and AGENTS.md. It does not include `scripts/`.
- **Verification JSON** holds `polygon_id` values `ramsar-<objectid>` (`aoi.py:73`) but no DBCA-010 geometry or site name. `grep site` over `src/wetland_change/verify` finds nothing. The 2026-11-14 judgement of n/a (identifiers only) stays.
- **`tests/test_sources.py`** checks only hosts and fixture checksums. The new licence cells break nothing.
- **`tests/test_licence.py`** asserts "CC BY-SA 4.0" in the README section. It is unchanged here, and it is st-22f1's to update.

### Batch 1 (one task): update the test, the note and `data/SOURCES.md`

1. **Tests first.** In `tests/test_public_release_licences.py`:
   - Rename the judged column "CC BY-SA 4.0 attribution" to "CC BY-NC 4.0 attribution". "CC BY-SA 4.0 ShareAlike" stays.
   - Add a `status` column (unmet, met, n/a) to "Unmet terms", and a `not filed: <reason>` story for an n/a term.
   - Add an `Answered: <date>; licence <licence>; redistribute_public <value>` line to the question section.
   - Run the file. It should fail in tests 8 and 9 (missing columns) against the current note.
2. **Note** (`docs/research/2026-11-14-public-release-licences.md`):
   - Add a new section `## Update 2026-11-15`. It records:
     - Jarrod's reply word for word, and that the orchestrator stated the recommendation itself
     - that the answer is not a confirmation from DBCA
     - the reasons for the answer
     - what changed
     - the residual risk from the SLIP terms, with the URL and quote
     - the recommendation that Jarrod obtains DBCA's written confirmation before the operator's apply (ADR 0011 step 6)
     - the remaining CC BY-SA 4.0 text, including `scripts/fetch_aoi.py:328`
     - the method
   - DBCA-010 dataset row: CC BY-NC 4.0 with the non-commercial term, and `true`.
   - Update the ramsar_mini bullet.
   - Published files: re-judge at b090f5a with the new citations. T1 and T2 become met. T3 stays unmet in observation Parquet, change rows and the STAC collection. ShareAlike is n/a everywhere.
   - Add an offline rerun block.
   - Unmet terms, with status: T1 met st-8856, T2 met st-d5c1, T3 unmet st-22f1. T4 is n/a, with the reason it was not filed.
   - Rewrite Blocking. It names T3 and the backfill of existing objects, and does not contain the string "DBCA-010 Ramsar Sites".
   - Mark the question answered.
3. **`data/SOURCES.md`:**
   - DBCA-010 licence: the same cell as the note, with `true`.
   - ramsar_mini licence: `CC BY-NC 4.0, non-commercial use only (attributes from DBCA-010; geometry is project-drawn rectangles)`.
4. **Gates**, one per line:
   - `uv run ruff check src tests scripts`
   - `uv run ruff format --check src tests scripts`
   - `uv run mypy src scripts`
   - `uv run pytest -q`

### What each test proves after this pass

1. `test_note_is_dated_and_has_no_em_dash`: the newest note is dated and has no U+2014.
2. `test_note_covers_every_dataset_that_reaches_a_published_file` (AC1): all 8 rows, once each.
3. `test_dataset_rows_name_licence_primary_source_and_fetch_date` (AC1): each row has a licence, a flag, an https source and a YYYY-MM-DD fetch date.
4. `test_note_licence_and_redistribute_public_match_sources` (AC5): the note and SOURCES.md are identical for licence and flag on every covered row, including the new DBCA-010 values.
5. `test_rows_not_true_are_named_blocking` (AC1): unchanged.
6. `test_three_claim_verdicts_with_source_urls_and_promotion_count` (AC2): unchanged; still 0 of 3, not promoted.
7. `test_promotion_outcome_is_reflected_in_sources_and_stories` (AC2), now with three branches:
   - **Promoted:** no story is deferred.
   - **Parked:** the flag is not true, DBCA-010 is blocking and the question is open.
   - **Answered:** no story is deferred. The DBCA-010 licence starts with the answered licence, and the flag equals the answered flag. DBCA-010 is blocking exactly when the flag is not true. Every SOURCES.md row whose source names DBCA-010 (at least 2) follows the answered licence. ShareAlike is n/a in every published row when the licence is not BY-SA. The `## Update <date>` section names the licence, the SLIP host and "written confirmation".
8. `test_every_published_file_kind_is_judged_with_a_writer_citation` (AC3): every kind has a row. Citations point at files that exist. The four columns, including the renamed "CC BY-NC 4.0 attribution", hold met, n/a or unmet (Tn).
9. `test_every_unmet_term_is_referenced_and_has_a_story_or_a_deferral` (AC4):
   - ids are unique and match Tn, and each status is one of unmet, met or n/a
   - the ids referenced in the published table equal the unmet ids
   - an unmet term has `st-xxxx` or a deferral, a met term has `st-xxxx`, and an n/a term has `not filed: <reason>`

### Orchestrator steps after the batch

These are outside the build task.

- **O3.** Rerun the four gates from the worktree, then commit on story/st-1a9c with the attribution line.
- **O4.** Close the story through the test gate. Nothing is deferred and T3 is filed as st-22f1, so the close needs no question. The note says the licence decision and the DBCA confirmation stay Jarrod's.
- **Flags for the orchestrator:**
  - `scripts/fetch_aoi.py:328` still prints a CC BY-SA 4.0 SOURCES row and `true`, and `scripts/` is not in st-22f1's touches. Add it to st-22f1, or st-22f1's "no file states CC BY-SA 4.0" criterion fails.
  - Verification JSON stays n/a for DBCA-010 (ids only). st-22f1's "other file kinds" criterion re-checks it.
  - Jarrod's reply approved recommendations he had not seen for this question. The close-out summary should name CC BY-NC 4.0 explicitly so he can overturn it.
  - The handoff follow-up at `docs/handoffs/2026-11-06-milestone-2.md:173` is historical and is not edited.

## Implementation Notes

- 2026-11-14T15:08:45.884Z: 2026-11-14: evidence committed as 02276c1 on story/st-1a9c (docs/research/2026-11-14-public-release-licences.md, data/SOURCES.md DBCA-010 row, tests/test_public_release_licences.py). Not merged to main. Gates run from the worktree after the build: ruff check, ruff format --check, mypy and pytest -q all exit 0. Claim 'DBCA-010 is CC BY-SA 4.0' confirmed by 0 of 3 claim-verifiers, so data/SOURCES.md records the licence as unresolved and redistribute_public as unconfirmed. T1 is st-8856 and T2 is st-d5c1. T3 and T4 are deferred to the licence answer; the plan's unpark steps apply.
- 2026-11-15T07:43:12.310Z: 2026-11-15: Jarrod replied "stories work. approved recommended that unblock stories". The park question labelled no recommendation, so the orchestrator states its own and records it as approved under that reply, not as a confirmation from DBCA. Recommendation taken: the project publishes DBCA-010 and the files that carry its polygons, site names and object ids under CC BY-NC 4.0, the licence the custodian states in its own catalogue entry (https://catalogue.data.wa.gov.au/dataset/ramsar-sites, fetched 2026-11-14). Reasons: the publisher's own entry outranks the data.gov.au aggregator label (CC BY-SA 4.0), CC BY-NC 4.0 is the more restrictive of the two Creative Commons licences named, and the custodian's published licence is read as the prior permission the SLIP service terms ask for. redistribute_public becomes true with the non-commercial term stated. CC BY-NC 4.0 has no ShareAlike term, so T4 does not apply; its licence-notice part is section 3(a)(1)(C) and folds into T3, which also changes the STAC collection licence (catalogue.py LICENSE), README "Data sources and licences" and the AGENTS.md locked decision from CC BY-SA 4.0 to CC BY-NC 4.0. Residual risk: the SLIP terms still read as requiring written permission, so written confirmation from DBCA before the operator's apply (ADR 0011 step 6, Jarrod's) is recommended and left to Jarrod.

## Questions

- 2026-11-14T15:08:45.960Z: DBCA-010 licence. Three checks against DBCA's catalogue entry and the SLIP service terms confirmed CC BY-SA 4.0 in 0 of 3. The primary sources state: "Creative Commons Attribution Non-Commercial 4.0" (https://catalogue.data.wa.gov.au/dataset/ramsar-sites, 2026-11-14); "You are not permitted to, in any form, reproduce, distribute, commercialise or create derivative works of this data without the data custodians prior written permission." (https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Environment/MapServer?f=pjson, 2026-11-14). The only CC BY-SA 4.0 label is on the data.gov.au aggregator (https://data.gov.au/data/dataset/ramsar-sites, 2026-11-14). Which licence applies to public redistribution of DBCA-010 and of the observation and change files that carry its polygons and site names? Until this is answered, DBCA-010 is blocking in data/SOURCES.md and the bucket stays private. If the answer is not CC BY-SA 4.0, the STAC collection licence (src/wetland_change/stac/catalogue.py:43), README.md 'Data sources and licences' and the AGENTS.md locked decision need to change, and T3 and T4 are filed under the licence you confirm.
