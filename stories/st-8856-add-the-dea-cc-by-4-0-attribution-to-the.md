---
id: st-8856
title: Add the DEA CC BY 4.0 attribution to the published files
type: feature
priority: P2
complexity: hard
depends_on: []
discovered_from: st-1a9c
touches: [README.md, src/wetland_change/attribution.py, src/wetland_change/cli.py, src/wetland_change/outputs/attribution_backfill.py, src/wetland_change/outputs/changes.py, src/wetland_change/outputs/footer_backfill.py, src/wetland_change/outputs/geoparquet.py, src/wetland_change/stac/catalogue.py, src/wetland_change/verify/checks.py, tests/test_attribution.py, tests/test_attribution_backfill.py, tests/test_catalogue.py, tests/test_change_outputs.py, tests/test_cli.py, tests/test_footer_backfill.py, tests/test_geoparquet.py, tests/test_sources.py, tests/test_verify.py]
exclusive: false
created: 2026-11-14
updated: 2026-11-15
---
## Description

st-1a9c (`docs/research/2026-11-14-public-release-licences.md`, term T1) found that the published files carrying Geoscience Australia DEA data under CC BY 4.0 carry no attribution.

- Observation Parquet holds DEA Waterbodies v3 polygons, their uids and the DEA Water Observations agreement score. Change files hold the same polygons. The verification JSON holds values derived from DEA Water Observations, DEA Sentinel-2 ARD NBART and the DEA Waterbodies time series.
- The Parquet footer keys (`src/wetland_change/outputs/provenance.py`, `FOOTER_KEYS`) and the report payload (`src/wetland_change/verify/checks.py`, `write_report`) have no licence or attribution field. The STAC collection (`src/wetland_change/stac/catalogue.py`, `PROVIDERS`) names Geoscience Australia as licensor with a homepage only.
- CC BY 4.0 section 3(a) requires the attribution and copyright notice the licensor supplies (the DEA product page gives "© Commonwealth of Australia (Geoscience Australia)" and citations), a licence notice with its URI, a link to the material, and an indication of modification. Section 3(a)(2) lets a link to a resource holding these satisfy it.
- Files already in the bucket lack it. `src/wetland_change/outputs/footer_backfill.py` is the existing footer rewrite path.

Constraints: no agent makes an AWS call or reads any object in the output store (st-b6bf and st-dd0d pre-registrations in `LEARNINGS.md`); the backfill of existing bucket files is documented for the operator and not run by an agent. Build agents do not commit or push; the orchestrator commits on the story branch.

Blocks ADR 0011 step 3 (opening the bucket).

## Acceptance Criteria

- [ ] Observation and change Parquet files carry the CC BY 4.0 section 3(a) DEA attribution, directly or by a link, and a test reads it back from a written file
- [ ] The verification JSON carries it, and a test asserts it
- [ ] The STAC collection carries it and a link to the licence text, and the catalogue still validates
- [ ] Existing bucket files get it through a documented backfill path that the operator runs
- [ ] `uv run pytest -q` passes

## Implementation Notes

- 2026-11-14T23:59:38.835Z: Planning constraints from the orchestrator, 2026-11-15: (1) Additive only. Do not rename, remove or change the value of any existing key, column or field in a published file; the pre-registered analyses of st-b6bf and st-dd0d read observation, change and verification outputs written by the scheduled runs. (2) Read the st-b6bf and st-dd0d pre-registrations in LEARNINGS.md first. If either forbids a pipeline or writer change before its decision files are committed, park this story with that rule quoted. (3) The licence note is on main at docs/research/2026-11-14-public-release-licences.md. DBCA-010 terms (T3, T4) are out of scope here and wait on Jarrod's licence answer. (4) Blindness applies to every agent: no output-store read, no AWS call, no wetland-change run, backfill, score or verify command, no -m live test, no docs/research/verification-*.md other than 20261029T131944Z and 20261111T175303Z, no git log -p or git show over docs/research, no CI run log.

## Implementation Plan

## st-8856: CC BY 4.0 attribution for the DEA data in published files

Worktree: `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-8856` (branch `story/st-8856`, at 296043d, tree clean, default suite green at planning time).

### Pre-registration check (planning constraint 2)
I read the st-dd0d and st-b6bf sections of `LEARNINGS.md` (lines 314 to 442). Neither forbids a pipeline or writer change before its decision files are committed.
- st-dd0d reads the `## Advisory` row of the markdown reports. The JSON report is used only for unrounded values where `generated_at` matches. The rule lists commits that change `src/wetland_change/verify/` as "Reported, not decision inputs ... listed and not corrected for", so this story's change to `verify/checks.py` is expected and allowed.
- st-b6bf bars reading output-store objects and running wetland-change commands over confirmatory scenes. It does not bar writer code.
- This plan leaves the markdown report (`_markdown`) unchanged. It keeps `generated_at` and every other JSON field unchanged in fresh and backfilled reports.

### Verified file pointers
- `src/wetland_change/outputs/provenance.py` has `FOOTER_KEYS` (9 keys) and `footer_metadata`. `tests/test_footer_backfill.py:111` pins `len(FOOTER_KEYS) == 9`, and `footer_backfill._has_all_keys` keys off it. So the attribution goes in a separate key. `FOOTER_KEYS` is not extended, because extending it would make `add-observation-footers` recompute (and possibly change) `water_settings` on every existing file.
- `src/wetland_change/outputs/geoparquet.py` (`write_observations`, `to_geoparquet_bytes`, `observation_paths`) and `src/wetland_change/outputs/changes.py` (`write_changes`) are the Parquet writers.
- `src/wetland_change/outputs/footer_backfill.py` rebuilds each file from the frame. As written it would drop any footer key other than geo, pandas and the nine provenance keys. That would remove the new attribution key if the operator ran it after the attribution backfill, so it is changed to keep the other keys.
- `src/wetland_change/verify/checks.py` `write_report` builds the JSON payload at line 215.
- `src/wetland_change/stac/catalogue.py`: `LICENSE` is "CC-BY-SA-4.0" and is left unchanged (T4 is deferred). `PROVIDERS` is unchanged. `build_catalogue` is where the collection is built. A prototype with `extra_fields` and a `rel=license` link passed `validate_all`.
- `tests/test_sources.py`: `NOT_A_DATASET` must list the new hosts (creativecommons.org, knowledge.dea.ga.gov.au, dx.doi.org). explorer.dea.ga.gov.au is already in `data/SOURCES.md`.
- `tests/test_readme.py` runs `--help` on every `uv run wetland-change <cmd>` in the README's Running locally code blocks. It forbids the strings "public bucket", "public s3", "cors" and "public-read".

### Design
1. New module `src/wetland_change/attribution.py`. It holds the constants and `dea_attribution(kind)` for kind in {observation, change, verification, collection}. The block has: notice, creator, copyright "© Commonwealth of Australia (Geoscience Australia)", licence name, licence URI `https://creativecommons.org/licenses/by/4.0/`, licence text URI `.../legalcode.en`, a disclaimer notice (section 5), `modified: true`, and a `datasets` list. Each dataset entry has name, sources (links to the material), content, modification and, for Waterbodies, the citation the licensor supplies. `dea_attribution_footer(kind)` returns `{"dea_attribution": json.dumps(block, sort_keys=True)}`. This satisfies CC BY 4.0 3(a)(1)(A)(i) to (v), (B) and (C) directly; no link-only route under 3(a)(2) is needed.
2. Parquet writers merge `dea_attribution_footer(kind)` into the footer. The provenance keys and their values are unchanged.
3. `write_report` appends `"dea_attribution": dea_attribution("verification")` as the last payload key. The markdown is not touched.
4. The STAC collection gains `extra_fields["dea_attribution"] = dea_attribution("collection")` and one link `rel=license` to the CC BY 4.0 legal code. Existing links, `license` and providers stay unchanged. Existing bucket collections update on the next `build-catalogue`, because the write-index digest changes.
5. New `src/wetland_change/outputs/attribution_backfill.py` and CLI command `add-dea-attribution`. For each `observations/**/obs_*.parquet`, `changes/**/chg_*.parquet` and `verification/<run_id>.json` that lacks `dea_attribution`, it adds `dea_attribution` and `dea_attribution_added_after_the_fact` ({commit, date}). Everything else is kept: table, Arrow schema and every existing metadata key and value; for JSON, every existing key in the same order with equal values. Each rewrite is checked before it is written. Files that already have the key are skipped, there is a dry-run mode, and one failure does not stop the others. It prints only paths and counts.
6. `footer_backfill._backfill_one` keeps every existing footer key other than geo, pandas, ARROW:schema, the nine provenance keys and `footer_added_after_the_fact`. `_verify` checks that those keys are unchanged.
7. README documents the new key, field and command, and an operator-only backfill procedure in Deployment: footers, then attribution, then `build-catalogue`, each with a dry run first, run when no workflow is running and before ADR 0011 step 3. No agent runs it.

Out of scope: T2 Copernicus notice (st-d5c1), T3 and T4 DBCA-010, the dated licence note, ADR edits, markdown reports.

### Steps and what each test proves
1. (Batch 1, task A) `src/wetland_change/attribution.py` plus `tests/test_attribution.py`. The tests prove that every kind carries every 3(a) element (copyright, licence name, URI, legal-code URI, disclaimer, modified flag, per-dataset source links and modification), that the per-kind dataset lists are exact, that the Waterbodies citation is verbatim, that results are fresh copies, and that the footer JSON is deterministic. `tests/test_sources.py` allowlists the three hosts, which keeps the host test green.
2. (Batch 2, task B) Parquet writers and footer backfill. Tests read `dea_attribution` back from files written by `write_observations` and `write_changes` (AC 1) and check that the nine provenance keys are unchanged. A footer-backfill test proves an existing `dea_attribution` survives `add_missing_footers`.
3. (Batch 2, task C) Verification JSON. A test proves `payload["dea_attribution"] == dea_attribution("verification")`, that it is the last key and that all earlier keys keep their order (AC 2).
4. (Batch 2, task D) STAC collection. Tests prove the collection carries `dea_attribution` and a `rel=license` link to the CC BY 4.0 legal code, that `license` and providers are unchanged, and that `validate_all` and stac-check still pass (AC 3).
5. (Batch 2, task E) Attribution backfill, CLI and README. Tests prove the backfill is additive for observation, change and JSON files (old keys, values, order, table and `generated_at` unchanged), plus skip, idempotency, dry run, failure isolation, refusal of a mismatched rewrite, the file filters and the content types. CLI tests cover summary lines and exit codes. The README test proves the new command answers `--help` (AC 4).
6. Final: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q` (AC 5).

Constraints for every task: no commit or push; no AWS call or output-store read (tests use `tmp_path` stores only); no `-m live`; no wetland-change run, backfill, score or verify against real data; no `docs/research/verification-*.md` other than 20261029T131944Z and 20261111T175303Z; no `git log -p` or `git show` over docs/research; no CI logs.
