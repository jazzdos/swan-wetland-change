---
id: st-5acd
title: Add missing data/SOURCES.md rows for references and fixtures
type: chore
priority: P3
depends_on: []
discovered_from: st-ff89
touches: [data/SOURCES.md, tests/test_sources.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

AGENTS.md requires a data/SOURCES.md row for every dataset in the commit that first uses it. The code reads Planetary Computer sentinel-2-l2a (src/wetland_change/verify/pixels.py:18) and Copernicus Data Space STAC sentinel-2-l2a (src/wetland_change/verify/copernicus.py:45), and README.md lists both, but data/SOURCES.md has no row for either. The committed fixtures under tests/fixtures/thomsons_20261027/ and tests/fixtures/aoi/ also have no row. Found by the st-ff89 reproducibility audit, which fixes nothing.

## Acceptance Criteria

- [ ] data/SOURCES.md has a row for Planetary Computer sentinel-2-l2a with URL
- [ ] licence
- [ ] fetch date
- [ ] checksum or n/a reason
- [ ] CRS and redistribute_public.
- [ ] data/SOURCES.md has the same row for Copernicus Data Space STAC sentinel-2-l2a.
- [ ] data/SOURCES.md has rows for tests/fixtures/thomsons_20261027/ and tests/fixtures/aoi/ with the sha256 of each file.
- [ ] A test in tests/ asserts that every host named in src and scripts appears in data/SOURCES.md.
- [ ] The four verification gates pass.

## Implementation Plan

## Findings from the worktree (verified)

- data/SOURCES.md has no row for Planetary Computer (`PC_STAC = https://planetarycomputer.microsoft.com/api/stac/v1`, src/wetland_change/verify/pixels.py:18) or Copernicus Data Space (`CDSE_STAC = https://stac.dataspace.copernicus.eu/v1`, src/wetland_change/verify/copernicus.py:45). Both pointers are correct. README.md lines 161-162 list both.
- Hosts in `src` and `scripts` *.py (regex `https?://host`): example.invalid, www.element84.com, www.esa.int, www.dbca.wa.gov.au, www.dea.ga.gov.au (provider homepage links in src/wetland_change/stac/catalogue.py), stac.dataspace.copernicus.eu, planetarycomputer.microsoft.com, public-services.slip.wa.gov.au, geoserver.dea.ga.gov.au, explorer.dea.ga.gov.au, data.dea.ga.gov.au, earth-search.aws.element84.com, dea-public-data.s3.ap-southeast-2.amazonaws.com (verify/ndvi.py:80 and verify/wo.py:55), files.pythonhosted.org (scripts/compare_dea_tools_indices.py:47, a pinned tool wheel, not a dataset). Bare `"https://"` literals (config.py, catalogue.py:115, raster/read.py) have no host and must not match the regex.
- Already in SOURCES.md: earth-search, public-services.slip, geoserver.dea, explorer.dea, data.dea. Missing: planetarycomputer, stac.dataspace.copernicus.eu, the dea-public-data.s3 https host (SOURCES only has the `s3://dea-public-data/` form).
- Fixtures (sha256 computed, `shasum -a 256`):
  - tests/fixtures/thomsons_20261027/: B03.tif 2966fe87951849c6eb16ad48d3c790e7e81d13aa40fc62b4771728ac0bfe3bcd; B04.tif 2bfa388beb4bdeed260b1e27ee3bb8ab56b20f013b35470da9f8814df7118c2b; B08.tif 3e35e46dd9fc199cd2225ae45cd0dbc416ff28da81e778765b7f8c0db950e79b; B11.tif 17c9b6224503a53a97700d76eaf23c2fc321681ff910977d59e58ca47fcb32ed; SCL.tif 5d9af5908f6c711d6ef0742768aab5a3ac2f2d49ea8c9acbeb73606bb6414e3c; item.json ddcacf2a12c283106977970177c6c98bb071f57362007806ae6b24b3f1d3812b; product_metadata.xml b6a00ed55781a5a98fddba4c00b1108cd00ade81da98f8fede1052848007dce6. Made by scripts/make_fixture.py from Earth Search item S2C_T50HLK_20261027T022351_L2A (64x64 window, EPSG:32750); committed 2026-10-29 (commit 5201589).
  - tests/fixtures/aoi/: ramsar_mini.geojson c238b19531190bfd312ddf4770e5a362e3067a10c1693a366c3fc62cb32951ca (3 hand-drawn rectangles, EPSG:4326); waterbodies_mini.geojson 6c0955dc8f70be5bbbd281a47ffd22ebd4d0177e8b51496e59636eed280bc42b (1 rectangle, EPSG:4326). Synthetic, project-authored, not downloaded; committed 2026-10-29.
  - tests/fixtures/waterbodies/ is outside the story; leave its existing row alone.
- No existing test reads SOURCES.md. tests/test_repo_hygiene.py is the natural neighbour (uses REPO_ROOT) but a new file keeps the change isolated.

## Steps (TDD)

1. RED: create tests/test_sources.py (below). Run `uv run pytest tests/test_sources.py -q`; expect failures for the planetarycomputer host, stac.dataspace.copernicus.eu, the S3 https host, and the fixture sha256 values.
   - `test_every_host_in_src_and_scripts_is_in_sources`: scans every `*.py` under `src/` and `scripts/` with `re.compile(r"(?:https?|s3)://([A-Za-z0-9][A-Za-z0-9.-]*)")`, lower-cases hosts, subtracts `NOT_A_DATASET`, and asserts each remaining host is a substring of data/SOURCES.md. The failure message names the host and the file. Proves a new data host cannot land without a SOURCES row.
   - `NOT_A_DATASET` is a dict host -> reason: `example.invalid` (reserved placeholder base URL), `www.element84.com`, `www.esa.int`, `www.dbca.wa.gov.au`, `www.dea.ga.gov.au` (provider homepage links in STAC catalogue metadata, no data read), `files.pythonhosted.org` (dea-tools wheel pinned by sha256 in scripts/compare_dea_tools_indices.py, a tool, not a dataset).
   - `test_unlisted_host_is_reported`: factor the logic into a helper `unlisted_hosts(sources_text: str, files: dict[Path, str]) -> dict[str, Path]` and assert that a fake file containing `https://not-in-sources.example.org/x` against the real SOURCES text returns that host, and that a listed host returns empty. Proves the check can fail.
   - `test_fixture_checksums_match_sources`: for every file (recursive, skipping `.DS_Store`) under tests/fixtures/thomsons_20261027 and tests/fixtures/aoi, compute `hashlib.sha256` and assert the hex digest appears in SOURCES.md. Proves the rows' checksums are current and a changed or added fixture file forces a SOURCES update.
   - Import nothing from wetland_change; use only stdlib + pytest; type-annotate for mypy (mypy covers src and scripts only, but ruff covers tests).
2. GREEN: edit data/SOURCES.md. Append rows to the table, after the last row and before the blank line and the prose paragraph. Keep the 7-column format: source | url | licence | fetched | sha256 | crs | redistribute_public.
   - Planetary Computer sentinel-2-l2a | https://planetarycomputer.microsoft.com/api/stac/v1 (collection `sentinel-2-l2a`, pixel identity reference, read by `src/wetland_change/verify/pixels.py`) | Copernicus Sentinel data terms (free, open) | per verify run | n/a (read live, signed COG reads, nothing stored; PC item id recorded in the check detail) | EPSG:32750 (tiles 50H, 50J) | true. The implementer must check pixels.py and confirm that the PC item id is in the check detail; if not, write "n/a (read live; nothing stored)" only.
   - Copernicus Data Space STAC sentinel-2-l2a | https://stac.dataspace.copernicus.eu/v1 (collection `sentinel-2-l2a`, discovery and freshness counts, read by `src/wetland_change/verify/copernicus.py`) | Copernicus Sentinel data terms (free, open) | per verify run | n/a (metadata only, read live: product names and counts, no pixels or files stored) | n/a (metadata and footprints only; no raster read) | true.
   - Fixture row 1: tests/fixtures/thomsons_20261027/ (64x64 window of Earth Search sentinel-2-c1-l2a item S2C_T50HLK_20261027T022351_L2A, made by scripts/make_fixture.py) | url https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a/items/S2C_T50HLK_20261027T022351_L2A | Copernicus Sentinel data terms (free, open) | 2026-10-29 (committed; scene acquired 2026-10-27) | the seven `file: sha256` pairs above, separated by `; ` | EPSG:32750 | true.
   - Fixture row 2: tests/fixtures/aoi/ (hand-drawn rectangles for the AOI tests; not a download) | url n/a (project-authored) | project-authored, CC0-equivalent test data, no third-party terms (write "n/a (project-authored synthetic polygons)") | 2026-10-29 (committed) | the two `file: sha256` pairs | EPSG:4326 | true.
   - To cover the S3 https host: in the existing "DEA Sentinel-2 ARD NBART" row and the "DEA Sentinel-2 Water Observations" row, extend the URL cell to also name `https://dea-public-data.s3.ap-southeast-2.amazonaws.com/` (the unsigned HTTPS form of `s3://dea-public-data/`). Edit only those cells.
   - Do not change the explanatory paragraph under the table except to add one sentence: "Fixture rows list a sha256 per file; tests/test_sources.py checks them against the files and checks that every host named in src and scripts appears in this file."
3. Run the four gates in order, one command per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. If format fails, run `uv run ruff format tests/test_sources.py`. Live tests (`-m live`) are not needed.
4. Commit: `st-5acd: Add SOURCES rows for Planetary Computer, Copernicus and the committed fixtures`.

## Notes and risks

- The host test is a substring check against the whole file, so it is deliberately loose (a host cited in prose would pass). A tighter check (host must appear inside a table row) is cheap: parse lines that start with `|`. Do this: restrict the haystack to lines starting with `|`.
- The regex yields no match for bare `"https://"` literals; confirm by running the test against the real tree.
- Scripts such as scripts/fetch_aoi.py print SOURCES rows; they do not need changes.
## Orchestrator amendments

These override the text above where they differ.

1. Agents commit nothing, including the commit step; the orchestrator commits after the run. Uncommitted work at the end of a task is expected and is not a defect, and reviewers must not report it. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**.
2. Never call AWS for the project's own bucket, never run terraform plan or apply, never run compaction against S3, and never run `-m live` tests. Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data. No network access is needed for this story.
3. Gates, one command each, judged by exit code: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`, `GITHUB_ACTIONS=true uv run pytest -q`. Never clear addopts for a gate; for a count use `-o addopts="-m 'not live'"`.
4. Story-specific:
   - Restrict the host test's haystack to SOURCES.md table rows (lines starting with `|`), as the plan's notes say.
   - Fetched cell for the Planetary Computer and Copernicus rows: give the date the code first used the host, found with `git log --diff-filter=A --format='%h %ad' --date=short -- <file>` on the file that names it, as "first used YYYY-MM-DD (commit <sha>); read live per verify run". Verify the claim in each checksum cell (for example that the PC item id is in the check detail) by reading the code; if it is not true, write "n/a (read live; nothing stored)".
   - tests/fixtures/aoi/ is not purely synthetic. ramsar_mini.geojson carries DBCA-010 attribute names and values (objectid, ram_ramsarname) on hand-drawn rectangle geometry. Read both files, then give each file its own row (or state per file in one row) with a conservative licence: ramsar_mini.geojson is "CC BY-SA 4.0 (attributes from DBCA-010; geometry is project-drawn rectangles)". For waterbodies_mini.geojson, use CC BY 4.0 with the same wording if it carries DEA Waterbodies attribute values (for example a uid), otherwise "MIT (project-authored; repository LICENSE)". Use url n/a with that reason.
   - The sha256 of each fixture file must be computed in the worktree, not copied from this prompt; skip .DS_Store files.
   - Touch only data/SOURCES.md and the new tests/test_sources.py. Do not edit README.md, src or scripts.
5. Docs are flat factual prose with no em dashes.

## Implementation Notes

- 2026-11-06T07:37:44.164Z: Commit 4af1789. SOURCES rows added for Planetary Computer and Copernicus Data Space sentinel-2-l2a (fetched = first-use date and commit; read live per verify run), thomsons_20261027 (sha256 per file) and one row per AOI fixture. AOI fixtures carry source attribute values, so ramsar_mini is CC BY-SA 4.0 and waterbodies_mini CC BY 4.0. DEA rows name the HTTPS S3 host. tests/test_sources.py checks hosts against table rows (allowlist with reasons, including the 'bucket' docstring placeholder) and fixture checksums. Gates pass, 951 passed.

## Questions
