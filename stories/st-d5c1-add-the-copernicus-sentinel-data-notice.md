---
id: st-d5c1
title: Add the Copernicus Sentinel data notice to the published files
type: feature
priority: P2
complexity: hard
depends_on: []
discovered_from: st-1a9c
touches: [README.md, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/ledger.py, src/wetland_change/outputs/changes.py, src/wetland_change/outputs/geoparquet.py, src/wetland_change/outputs/notice_backfill.py, src/wetland_change/pipeline.py, src/wetland_change/sentinel_notice.py, src/wetland_change/stac/catalogue.py, src/wetland_change/verify/checks.py, src/wetland_change/verify/run.py, tests/test_catalogue.py, tests/test_change.py, tests/test_change_outputs.py, tests/test_cli.py, tests/test_geoparquet.py, tests/test_ledger.py, tests/test_notice_backfill.py, tests/test_readme.py, tests/test_sentinel_notice.py, tests/test_sources.py, tests/test_verify.py]
exclusive: false
created: 2026-11-14
updated: 2026-11-15
---
## Description

st-1a9c (`docs/research/2026-11-14-public-release-licences.md`, term T2) found that no published file carries the notice the Copernicus Sentinel data legal notice requires on distribution: "Contains modified Copernicus Sentinel data [Year]" (https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice).

- Observation and change Parquet hold values computed from Earth Search `sentinel-2-c1-l2a` reflectance. The STAC items and the ledger hold Earth Search item footprints and properties. The verification JSON holds values read from Earth Search, Planetary Computer and Copernicus Data Space.
- The STAC collection (`src/wetland_change/stac/catalogue.py`, `PROVIDERS`) names ESA as producer and licensor but carries no notice.
- Writers: `src/wetland_change/outputs/provenance.py` (Parquet footer), `src/wetland_change/stac/catalogue.py`, `src/wetland_change/verify/checks.py` (`write_report`), `src/wetland_change/ledger.py`.

Constraints: no agent makes an AWS call or reads any object in the output store (st-b6bf and st-dd0d pre-registrations in `LEARNINGS.md`). Build agents do not commit or push; the orchestrator commits on the story branch.

Blocks ADR 0011 step 3 (opening the bucket).

## Acceptance Criteria

- [ ] Observation and change Parquet footers carry the notice with the acquisition year or years, and a test reads it back
- [ ] The STAC collection carries the notice, and the catalogue still validates
- [ ] The ledger and verification JSON carry the notice (for example in file metadata), and a test asserts it
- [ ] `uv run pytest -q` passes

## Implementation Notes

- 2026-11-14T23:59:38.905Z: Planning constraints from the orchestrator, 2026-11-15: (1) Additive only. Do not rename, remove or change the value of any existing key, column or field in a published file; the pre-registered analyses of st-b6bf and st-dd0d read observation, change and verification outputs written by the scheduled runs. (2) Read the st-b6bf and st-dd0d pre-registrations in LEARNINGS.md first. If either forbids a pipeline or writer change before its decision files are committed, park this story with that rule quoted. (3) The licence note is on main at docs/research/2026-11-14-public-release-licences.md. DBCA-010 terms (T3, T4) are out of scope here and wait on Jarrod's licence answer. (4) Blindness applies to every agent: no output-store read, no AWS call, no wetland-change run, backfill, score or verify command, no -m live test, no docs/research/verification-*.md other than 20261029T131944Z and 20261111T175303Z, no git log -p or git show over docs/research, no CI run log.
- 2026-11-15T00:55:36.699Z: Planning facts from st-8856, merged to main as ac065f7 on 2026-11-15: (1) src/wetland_change/attribution.py holds the DEA block. Writers add it as the separate key dea_attribution: Parquet footers through dea_attribution_footer, the last key of the verification JSON, and an extra field plus a license link on the STAC collection. FOOTER_KEYS stays at nine. Follow the same pattern with a separate key for the Copernicus notice. Do not change the dea_attribution block or any existing key. (2) src/wetland_change/outputs/attribution_backfill.py and the add-dea-attribution command add the DEA block to existing files and skip any file that already holds dea_attribution, so a later change to a block does not reach files already written. Files already in the bucket also lack the Copernicus notice. Plan the path by which they get it, run by the operator only, and keep README 'Attribution backfill (operator only)' as one procedure that covers both blocks whatever order the operator runs the commands in. The operator has not run the st-8856 backfill yet. (3) The notice wording must match the Sentinel Data Legal Notice exactly. The orchestrator is having the wording checked against the primary source while you plan and will correct the plan text if it differs. State in the plan where each year comes from for each file type (Parquet footer, STAC collection, ledger, verification JSON).
- 2026-11-15T01:13:57.584Z: Notice wording check, 2026-11-15: three independent checks against the primary PDF (https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice, SHA-256 fa2955ff48a1d82e77fc7296d63681670ecdb9d2811a0505ae60d0683b62fa64, fetched 2026-11-15) confirm 3 of 3 that the modified-data notice is exactly 'Contains modified Copernicus Sentinel data [Year]'. The notice and Delegated Regulation (EU) No 1159/2013 Art. 8 do not define [Year]; filling it with UTC acquisition years is this project's reading and the common convention, not an official rule. No newer notice with different wording was found. Art. 8(2) adds a non-endorsement duty and Art. 8(3) a clear statement that the data were modified. Verdicts: scratchpad copernicus-verifier-{a,b,c}.json.

## Implementation Plan

# st-d5c1 plan: Copernicus Sentinel data notice in published files

## Prerequisite check (done at planning time, in the worktree)
- The worktree is on `story/st-d5c1` at aec1bcb. st-8856 is merged (ac065f7). `src/wetland_change/attribution.py`, `outputs/attribution_backfill.py`, the `add-dea-attribution` command and README "Attribution backfill (operator only)" all exist. The default suite passes at baseline.
- Every file pointer in the story checks out. `outputs/provenance.py` is not edited: `FOOTER_KEYS` stays at nine, and footers are assembled in `outputs/geoparquet.py` and `outputs/changes.py`, as for `dea_attribution`. The ledger writer is `ledger.py` (`write_ledger`, `compact_ledger`). The verification JSON writer is `verify/checks.py` (`write_report`), called only from `verify/run.py` (`verify_run`).
- Pre-registrations (LEARNINGS.md, st-dd0d and st-b6bf). Neither forbids a pipeline or writer change before its decision files are committed.
  - st-dd0d bars reads of sample reports and output-store objects. It lists "the commits between 2db25a1 and the head commit of the last sample run that change a file under `src/wetland_change/verify/` ..." as reported, "listed and not corrected for". This story's commit will be on that list.
  - st-dd0d also reads the JSON `generated_at` against the Markdown report. Both stay unchanged: the Markdown report is untouched, and new JSON keys are appended last.
  - st-b6bf bars reads only.
  - This plan reads no output-store object and runs no pipeline or live command.

## Design
- New single source `src/wetland_change/sentinel_notice.py`. It holds the key `copernicus_notice`, the backfill marker `copernicus_notice_added_after_the_fact`, and the notice text "Contains modified Copernicus Sentinel data <years>".
  - Years: consecutive runs are written "first-last" and runs are joined by ", ". So 2026 becomes "2026", 2020 to 2026 becomes "2020-2026", and 2020, 2021, 2022 and 2024 become "2020-2022, 2024".
  - The block holds: notice, years, years_from, modified, sources, legal_notice, legal_notice_uri (https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice).
  - The modified form is used for every kind. Each file holds values computed from Earth Search C1 data, or metadata that Element 84 reformatted from ESA products and this pipeline reformats again, and the story names the modified notice.
  - The wording sits in one constant (`NOTICE_PREFIX`) and one formatter (`notice_text`). If the orchestrator's check of the primary source differs, only `sentinel_notice.py` and the literal strings in the tests change.
- Separate key. `dea_attribution` is never touched, and every existing key, column and field keeps its value and position.
- A file carries the notice only when its content comes from at least one Sentinel-2 acquisition with a known UTC year. Otherwise the key is absent: a ledger file of rejected rows only, a verification report of a run with no succeeded scene, or an empty collection.
- Values depend only on the years, so reruns stay byte-identical.

## Where each year comes from
| file | years |
|---|---|
| observation Parquet footer | UTC year of `datetime` of the file's rows (one item, so one year) |
| change Parquet footer | UTC year of the file's rows, plus the UTC years of the history rows its baseline is built from: same polygon, same calendar month, strictly earlier UTC date. This is the `history` that `score_changes` passes to `build_baseline`, via the new `change.baseline_source_years`. |
| STAC collection | UTC years of `datetime` of the collection's items (latest succeeded ledger entries with a source item) |
| STAC item JSON and items.parquet | UTC year of the item's `datetime`. The property `copernicus_notice` holds the notice text only; the collection holds the full block. This covers the "STAC items" row of T2. |
| ledger file (Parquet schema metadata) | UTC years of the file's non-null `datetime` column. Parts and compacted files are each computed over their own rows. |
| verification JSON (last key) | UTC years of the run's succeeded ledger rows, plus every latest succeeded ledger entry with an observation file acquired at or before the newest of them. That second set is the history `_history_paths` gives the waterbody checks. New `verify.run.verification_years(ledger, run_id)`. |
| backfill of existing files | Same rules, applied to the stored file. Observation and ledger files use their own rows. A change file uses its rows plus the stored observation history; it can list a year that a later-stored earlier observation adds, which over-states and never under-states. A verification report uses the current ledger. |

Run manifests, the root catalog and `stac/write-index.json` hold no Sentinel content (licence note, n/a) and get nothing.

## Steps
1. `src/wetland_change/sentinel_notice.py` (new) and `tests/test_sentinel_notice.py`. The tests prove the exact text for one year, a run, a gap, duplicates and an empty input (raises); the UTC conversion in `utc_years` (null, NaT, offset and naive values); the block fields for each kind; and `copernicus_notice_footer` returning {} for no years and stable JSON otherwise. `tests/test_sources.py` gains `sentinels.copernicus.eu` in NOT_A_DATASET, so the host scan passes.
2. Parquet writers.
   - `outputs/geoparquet.py` `write_observations` merges `copernicus_notice_footer("observation", years of rows)`.
   - `outputs/changes.py` `write_changes` gains `baseline_years: Collection[int] = ()` and merges the footer for row years plus baseline years.
   - `change.py` gains `baseline_source_years(observations, *, polygon_ids, day)`.
   - `pipeline.py` `score_changes` passes `baseline_source_years(history, polygon_ids=group polygons, day=day)`.
   - Tests read the footer back through `pq.read_schema` and `pq.read_metadata`. They prove 2026 on observation files, 2020-2026 on a change file scored against 2020 to 2025 history, and that history of another month, another polygon or a later date adds no year. They also prove the nine provenance keys and `dea_attribution` are unchanged. The two exact key-set assertions in `tests/test_geoparquet.py` and `tests/test_change_outputs.py` gain "copernicus_notice".
3. Ledger.
   - `ledger.py` `write_ledger` and `compact_ledger` write the schema metadata `copernicus_notice` for the years of the written rows; a file with none gets no metadata.
   - `read_ledger` is unchanged, because `_conform` casts to LEDGER_SCHEMA and drops file metadata. That was checked with pyarrow 26.
   - Tests prove: years 2025-2026 on a part; no key on a rejected-only part; `read_ledger` rows and schema unchanged; a compacted file carries the union of its parts' years; and identical bytes across two stores.
4. STAC.
   - `stac/catalogue.py` adds item property `copernicus_notice` (notice text for the item's year) and collection extra field `copernicus_notice` (the block over the item years, absent with no items).
   - It adds no new link, so the st-8856 one-licence-link tests stand.
   - Tests prove: the collection block equals `copernicus_notice("collection", years)`; a 2025 item gives 2025-2026; each item's property is set and the items.parquet column holds the same text; an empty ledger gives no key; `dea_attribution`, `license` and the single licence link are unchanged; and `validate_all` and stac-check still pass.
5. Verification JSON.
   - `verify/run.py` gains `verification_years`, and `verify_run` passes it to `write_report`.
   - `verify/checks.py` `write_report` gains `copernicus_years: Collection[int] = ()` and appends `copernicus_notice` after `dea_attribution` when the years are non-empty.
   - Tests prove: the key is last with the expected block; the earlier keys and their order are unchanged; there is no key without years; the Markdown report is identical with and without years; `verify_run` writes 2026 for the fixture run; and the `verification_years` rules (history included, later or failed or rejected rows excluded, a run without succeeded rows gives ()).
6. Backfill, CLI and README.
   - New `outputs/notice_backfill.py` `add_missing_notice(store, *, commit, on, dry_run)`. It adds `copernicus_notice` and `copernicus_notice_added_after_the_fact` (commit and date) to each observation file, change file, `verification/<run_id>.json` and ledger file that lacks `copernicus_notice` and has at least one year. It skips files that hold the key or have no year, and verifies each rewrite against the original. Existing rows, columns, footer keys and JSON fields are unchanged, including `generated_at` and their order.
   - New CLI command `add-copernicus-notice`, which mirrors `add-dea-attribution`.
   - README:
     - Run stages 6, 8 and 9 and the data sources paragraph describe the notice.
     - "Running locally" lists `add-copernicus-notice --dry-run`, and the CLI bullet documents the command.
     - "Attribution backfill (operator only)" stays one procedure covering both blocks: footers, DEA, Copernicus, then `build-catalogue`. It states that the DEA and Copernicus backfills are independent and can run in any order relative to each other and to `add-observation-footers`.
   - Tests prove: per-kind additions; skips; second run writes nothing; dry run writes nothing; one bad file does not stop the others. For order independence, all six orders of the three backfills on an unfooted observation file give the same non-geo footer entries, and both orders of the DEA and Copernicus backfills on a report give the same fields with `generated_at` unchanged. They also cover the CLI output and exit codes, and README naming of the commands.
7. Verify: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.

## Operator path for files already in the bucket (not run by any agent)
After merge, the operator runs README "Attribution backfill (operator only)", then `build-catalogue`. The scheduled pipeline also rewrites the collection and every item on its first build after main is pushed. ADR 0011 step 3 stays blocked by T3 and T4 (DBCA-010), which are out of scope.

## Batches
1. T1 sentinel_notice (every later task imports it).
2. T2 Parquet writers, T3 ledger, T4 STAC, T5 verification JSON (no shared files).
3. T6 backfill, CLI and README (needs `baseline_source_years` from T2, `verification_years` from T5 and the writers' behaviour from T3 and T4).
