---
id: st-1a9c
title: Check dataset licences and attribution in published files for public release
type: spike
priority: P2
complexity: hard
depends_on: []
touches: [data/SOURCES.md, docs/research/*-public-release-licences.md]
exclusive: false
gates: [test]
created: 2026-11-14
updated: 2026-11-14
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

# st-1a9c plan: public-release licence evidence

## Checked in the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-1a9c, branch story/st-1a9c at e3890a6, clean)

- `data/SOURCES.md`: one 7-column table (source, url, licence, fetched, sha256, crs, redistribute_public). Every row splits into exactly 7 cells on `|`. The DBCA-010 row says `CC BY-SA 4.0 (data.gov.au)` with the SLIP MapServer/9/query URL. Every row has `true`. `tests/test_sources.py` checks only hosts and fixture checksums, so changing a licence or flag cell breaks nothing.
- `docs/decisions/0011-private-output-bucket.md`, "Reopening public access", step 2 matches the story. `docs/handoffs/2026-11-06-milestone-2.md:173` holds the open "DBCA-010 licence confirmation" follow-up. `AGENTS.md` has the locked decision. `LICENSE` is MIT (st-aa46). `README.md` "## Data sources and licences" must keep "CC BY-SA 4.0" and "CC BY 4.0" (`tests/test_licence.py`), and it is not changed.
- Writers (line numbers at e3890a6; the build task re-checks them):
  - Observation Parquet: `src/wetland_change/outputs/geoparquet.py:29` (columns), `:88` write_observations. Footer keys: `src/wetland_change/outputs/provenance.py:74` FOOTER_KEYS (9 keys, none for licence or attribution; `tests/test_footer_backfill.py:111-112`) and `:94` footer_metadata. Polygons come from `src/wetland_change/aoi.py:56` `_to_polygons`: geometry_4326, site=ram_ramsarname, polygon_id from the objectid or uid; load_ramsar is at `:83`, load_waterbodies at `:105`.
  - Change rows: `src/wetland_change/outputs/changes.py:24` and `:75`, with the same footer. Geometry comes from observations at `src/wetland_change/pipeline.py:346-348` and `:375-378`, so both DBCA and DEA polygons appear.
  - STAC: `src/wetland_change/stac/catalogue.py:43` LICENSE="CC-BY-SA-4.0", `:61` PROVIDERS (Element 84, ESA, DBCA and GA, homepages only), `:185-198` Collection, `:211-216` Catalog (no licence field), `:99` `_item` (no licence; derived_from link at `:113-119`), items.parquet at `:222` and `:272-278`, write-index at `:305-310`. An offline build from an empty ledger gives collection license CC-BY-SA-4.0 and links root, self and parent only (no rel=license link). The catalog keys are description, id, links, stac_version, title and type.
  - Run manifests: `src/wetland_change/manifest.py:30` and `:94`. Ledger: `src/wetland_change/ledger.py:45` schema and `:117` source_item (the full Earth Search item JSON). Verification JSON: `src/wetland_change/verify/checks.py:187` write_report, payload at `:215-230`.
- The baseline `uv run pytest -q` passes.
- I checked the outside URLs on 2026-11-14 with a generic User-Agent:
  - The Earth Search C1 collection has license "proprietary" and links to the Copernicus legal notice. The `sentinel.esa.int` host did not resolve; the same PDF is at https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice and requires "Contains modified Copernicus Sentinel data [Year]".
  - DEA STAC collections have license CC-BY-4.0. The DEA Waterbodies product page says CC BY 4.0 and gives "© Commonwealth of Australia (Geoscience Australia)" and citations.
  - Planetary Computer: "proprietary", linking to a SciHub T&C PDF. CDSE: "other", linking to the sentinels.copernicus.eu legal notice.
- **Pre-check of DBCA-010 (for the orchestrator only; do not give it to the verifiers).**
  - The SLIP layer 9 copyrightText is empty.
  - The publisher's catalogue entry (`https://catalogue.data.wa.gov.au/api/3/action/package_show?id=ramsar-sites`, organisation DBCA, metadata_modified 2026-11-13) gives license_id `cc-nc`, license_title "Creative Commons Attribution Non-Commercial 4.0" and license_url by-nc/4.0.
  - data.gov.au gives the same license_id `cc-nc` but titles it "Creative Commons Attribution Share Alike 4.0 International".
  - So the claim will probably not be promoted. The story already covers that case (park with the question), so the story can still be implemented.

## Orchestrator steps (build agents cannot do these)

**O1. Claim check.** Dispatch three `claim-verifier` agents in parallel, model opus, effort xhigh. Give each the same prompt, word for word:

> Claim: "DBCA-010 Ramsar Sites is licensed CC BY-SA 4.0, and that licence applies to public redistribution of the data and of products derived from it."
>
> Context: DBCA-010 Ramsar Sites is a dataset of the Western Australian Department of Biodiversity, Conservation and Attractions (DBCA). It is fetched from the SLIP Public Services ArcGIS REST endpoint https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Environment/MapServer/9/query. So far the only recorded source for CC BY-SA 4.0 is a data.gov.au listing. data.gov.au is an aggregator, not the primary source, and on its own does not confirm the claim.
>
> Primary sources to find and read yourself:
> (1) The publisher's own catalogue entry for DBCA-010: DBCA's dataset record in the Western Australian government data catalogue (data.wa.gov.au), and any DBCA page for the dataset.
> (2) The terms of the service the data is fetched from: the SLIP layer metadata (for example .../MapServer/9?f=pjson) and the SLIP or data.wa.gov.au terms of use or licence that govern data taken from that service.
>
> To return isReal true you must find, in a primary source you fetched, (a) a statement that DBCA-010 is under CC BY-SA 4.0, and (b) nothing in the publisher's entry or the service terms that names a different licence or restricts public redistribution or derived products. A primary source that names a different licence refutes the claim. Primary sources that conflict mean the claim is not confirmed.
>
> Return the claim-verifier JSON plus these fields: "fetchedAt" (the UTC date YYYY-MM-DD of your fetches), "licenceStated" (a list of {url, statement}, quoted exactly from each source you read), and "derivedProducts" (a quote on redistribution or derived products, or null).
>
> Rules: send no user name, email address or project name in any request; use a generic User-Agent; do not search for the project's name. You need no repository file, so open none. Make no AWS call.

The claim is promoted when at least 2 of the 3 verdicts are isReal true. Record `Promoted: yes|no (N of 3)`.

**O2. File the unmet-term stories** with `story create --discovered-from st-1a9c --type feature --priority P2` before the batch runs.
- T1 and T2 are always filed. T3 and T4 are filed only when the claim is promoted. When it is not, they wait for Jarrod's answer.
- In each description, `<note>` is `docs/research/2026-11-14-public-release-licences.md` (use the UTC date of the work).
- Every story ends its description with "Blocks ADR 0011 step 3 (opening the bucket)", and its last AC is "uv run pytest -q passes".

**T1: Add the DEA CC BY 4.0 attribution to the published files**
- Touches: `src/wetland_change/outputs/provenance.py`, `src/wetland_change/stac/catalogue.py`, `src/wetland_change/verify/checks.py`.
- Description:
  - st-1a9c (<note>, term T1) found that the published files carrying Geoscience Australia DEA data under CC BY 4.0 carry no attribution.
  - Observation Parquet holds DEA Waterbodies v3 polygons, their uids and the DEA Water Observations agreement score. Change files hold the same polygons. The verification JSON holds values derived from DEA Water Observations, DEA Sentinel-2 ARD NBART and the DEA Waterbodies time series.
  - The Parquet footer keys (`outputs/provenance.py` FOOTER_KEYS) and the report payload (`verify/checks.py` write_report) have no licence or attribution field. The STAC collection names Geoscience Australia as licensor with a homepage only.
  - CC BY 4.0 section 3(a) requires the attribution and copyright notice the licensor supplies (the DEA product page gives "© Commonwealth of Australia (Geoscience Australia)" and citations), a licence notice with its URI, a link to the material, and an indication of modification. Section 3(a)(2) lets a link to a resource holding these satisfy it.
  - Files already in the bucket lack it. `src/wetland_change/outputs/footer_backfill.py` is the existing footer rewrite path.
- ACs:
  - Observation and change Parquet files carry the section 3(a) DEA attribution, directly or by a link, and a test reads it back from a written file.
  - The verification JSON carries it, and a test asserts it.
  - The STAC collection carries it and a link to the licence text, and the catalogue still validates.
  - Existing bucket files get it through a documented backfill path that the operator runs.

**T2: Add the Copernicus Sentinel data notice to the published files**
- Touches: provenance.py, catalogue.py, checks.py, `src/wetland_change/ledger.py`.
- Description:
  - st-1a9c (<note>, term T2) found that no published file carries the notice the Copernicus Sentinel data legal notice requires on distribution: "Contains modified Copernicus Sentinel data [Year]" (https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice).
  - Observation and change Parquet hold values computed from Earth Search sentinel-2-c1-l2a reflectance. The STAC items and the ledger hold Earth Search item footprints and properties. The verification JSON holds values read from Earth Search, Planetary Computer and Copernicus Data Space.
  - The STAC collection names ESA as producer and licensor but carries no notice.
- ACs:
  - Observation and change Parquet footers carry the notice with the acquisition year or years, and a test reads it back.
  - The STAC collection carries the notice, and the catalogue still validates.
  - The ledger and verification JSON carry the notice (for example in file metadata), and a test asserts it.

**T3 (promoted only): Add the DBCA-010 CC BY-SA 4.0 attribution to the published files**
- Touches: provenance.py, catalogue.py.
- Description:
  - st-1a9c (<note>, term T3) confirmed CC BY-SA 4.0 at <primary URL>.
  - Observation and change Parquet hold DBCA-010 polygons, site names (ram_ramsarname) and object ids (in polygon_id), and carry no attribution. The STAC collection names DBCA as licensor with a homepage only.
  - CC BY-SA 4.0 section 3(a) requires the creator identification and any copyright notice DBCA supplies, the licence notice and URI, a link to the dataset, and an indication of modification (reprojected to EPSG:4326, selected by site).
- ACs:
  - Parquet files carry the attribution, directly or by a link, and a test reads it back.
  - The STAC collection links to the DBCA-010 catalogue entry and the licence text, and the catalogue still validates.

**T4 (promoted only): Meet the CC BY-SA 4.0 ShareAlike terms in the published files**
- Touches: provenance.py, catalogue.py.
- Description:
  - st-1a9c (<note>, term T4) found that observation and change Parquet, which are adapted material of DBCA-010, carry no licence notice. A file read on its own, for example through the DuckDB glob over observations/, states no licence.
  - The STAC collection declares CC-BY-SA-4.0 (catalogue.py LICENSE) with no link to the licence text.
  - Section 3(b) requires CC BY-SA 4.0 or a compatible licence, the text of that licence or its URI, and no added terms.
- ACs:
  - Parquet footers name CC BY-SA 4.0 with its URI, and a test reads it back.
  - The collection has a rel=license link to the CC BY-SA 4.0 legal code, and the catalogue still validates.

**O2b.** Append an `## Orchestrator inputs` block to the batch task prompt. It holds the three verifier JSON objects (labelled Verifier 1, 2 and 3), the `Promoted:` line, and `Stories: T1=st-.... T2=st-.... T3=st-....|deferred T4=st-....|deferred`.

**O3. After the batch, and before any commit:**
- If the summary reports a term judged met everywhere, archive its story.
- If it reports a file kind added to a term, add that kind to the story.
- Run the gates from the worktree, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
- Commit on story/st-1a9c with the attribution line.

**O4. Close or park.**
- Promoted: close through the test gate. The decision that the licence is acceptable stays Jarrod's, and the note says so.
- Not promoted: `story park` st-1a9c with the note's "## Question for Jarrod" text.
- On unpark:
  - File T3 and T4 under the licence Jarrod confirms.
  - Replace the two `deferred: question to Jarrod` cells with their ids in an "Update <date>" paragraph and in the table.
  - Set the DBCA-010 licence and redistribute_public in both files to match.
  - Rerun the gates and close.
  - The `tests/fixtures/aoi/ramsar_mini.geojson` row in SOURCES.md, which inherits DBCA-010, also follows the answer.

## Batch 1 (one task): note, SOURCES.md edits and consistency test

Files:
- `tests/test_public_release_licences.py` (new)
- `docs/research/2026-11-14-public-release-licences.md` (new)
- `data/SOURCES.md` (DBCA-010 row; other rows only if a primary source states a different licence)

What the tests prove:
1. `test_note_is_dated_and_has_no_em_dash`: the newest note matches `<YYYY-MM-DD>-public-release-licences.md` and follows the writing standard.
2. `test_note_covers_every_dataset_that_reaches_a_published_file` (AC1): all 8 SOURCES.md rows whose data reaches a bucket object are listed, once each. The 8 rows are Earth Search C1, DBCA-010, DEA Waterbodies polygons, DEA NBART, DEA Waterbodies CSV, DEA S2 WO, Planetary Computer and CDSE.
3. `test_dataset_rows_name_licence_primary_source_and_fetch_date` (AC1): each row has a licence, a flag, an https primary-source URL and a YYYY-MM-DD fetch date.
4. `test_note_licence_and_redistribute_public_match_sources` (AC5): for each note row, the SOURCES.md row with the identical source cell has the identical licence and redistribute_public.
5. `test_rows_not_true_are_named_blocking` (AC1): every row whose flag is not `true` is named under "## Blocking".
6. `test_three_claim_verdicts_with_source_urls_and_promotion_count` (AC2): there are exactly 3 verdict rows, each with an https source URL and a fetch date. The `Promoted: yes|no (N of 3)` line equals the count of confirmed rows, and "yes" holds only when N is at least 2.
7. `test_promotion_outcome_is_reflected_in_sources_and_stories` (AC2): if the claim is not promoted, DBCA-010's flag is not `true`, DBCA-010 is blocking and the question is non-empty. If it is promoted, no story is deferred.
8. `test_every_published_file_kind_is_judged_with_a_writer_citation` (AC3): there is a row for each of observation Parquet, change rows, STAC catalog, STAC collection, STAC items, run manifests, ledger and verification JSON. Each row cites a writer `src/...py:<line>` that exists, and each of the four term columns is `met`, `n/a` or `unmet (Tn[, Tn])`.
9. `test_every_unmet_term_is_referenced_and_has_a_story_or_a_deferral` (AC4): the term ids are unique, the ids referenced in the table equal the ids in "## Unmet terms", and each row has a story id `st-xxxx` or `deferred: question to Jarrod`.

Gates: the four AGENTS.md commands above, in order, one per line.

## Implementation Notes

- 2026-11-14T15:08:45.884Z: 2026-11-14: evidence committed as 02276c1 on story/st-1a9c (docs/research/2026-11-14-public-release-licences.md, data/SOURCES.md DBCA-010 row, tests/test_public_release_licences.py). Not merged to main. Gates run from the worktree after the build: ruff check, ruff format --check, mypy and pytest -q all exit 0. Claim 'DBCA-010 is CC BY-SA 4.0' confirmed by 0 of 3 claim-verifiers, so data/SOURCES.md records the licence as unresolved and redistribute_public as unconfirmed. T1 is st-8856 and T2 is st-d5c1. T3 and T4 are deferred to the licence answer; the plan's unpark steps apply.

## Questions

- 2026-11-14T15:08:45.960Z: DBCA-010 licence. Three checks against DBCA's catalogue entry and the SLIP service terms confirmed CC BY-SA 4.0 in 0 of 3. The primary sources state: "Creative Commons Attribution Non-Commercial 4.0" (https://catalogue.data.wa.gov.au/dataset/ramsar-sites, 2026-11-14); "You are not permitted to, in any form, reproduce, distribute, commercialise or create derivative works of this data without the data custodians prior written permission." (https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Environment/MapServer?f=pjson, 2026-11-14). The only CC BY-SA 4.0 label is on the data.gov.au aggregator (https://data.gov.au/data/dataset/ramsar-sites, 2026-11-14). Which licence applies to public redistribution of DBCA-010 and of the observation and change files that carry its polygons and site names? Until this is answered, DBCA-010 is blocking in data/SOURCES.md and the bucket stays private. If the answer is not CC BY-SA 4.0, the STAC collection licence (src/wetland_change/stac/catalogue.py:43), README.md 'Data sources and licences' and the AGENTS.md locked decision need to change, and T3 and T4 are filed under the licence you confirm.
