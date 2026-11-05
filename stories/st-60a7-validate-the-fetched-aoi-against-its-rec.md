---
id: st-60a7
title: Validate the fetched AOI against its recorded source
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [README.md, scripts/fetch_aoi.py, tests/test_fetch_aoi.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

fetch_aoi calls only raise_for_status (scripts/fetch_aoi.py:84-89), so an HTTP 200 error body is written as the AOI file. If SLIP renumbers objectids the ramsar-15, ramsar-28 and ramsar-56 overrides silently attach to other polygons. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md L3.

## Acceptance Criteria

- [ ] fetch_aoi fails when the response is not a GeoJSON feature collection
- [ ] fetch_aoi fails or warns when the polygon ids used by water overrides are missing or renamed

## Implementation Plan

## Verification of story pointers (done in worktree .worktrees/st-60a7)

- `scripts/fetch_aoi.py` `fetch()` (lines ~78-89) only calls `raise_for_status`, then `checksum(content)`, then `dest.write_bytes`. The Ramsar fetch uses the default `raw_sha256` checksum, which accepts any bytes, so an HTTP 200 ArcGIS error body (`{"error": {...}}`) or HTML is written as `data/external/dbca_010_ramsar_sites.geojson`. The Waterbodies fetch already rejects non-JSON and non-object bodies through `stable_geojson_checksum`, but accepts any JSON object, including `{"error": ...}`.
- Polygon ids are `ramsar-<objectid>` (`src/wetland_change/aoi.py` `load_ramsar`, filtered by `ram_ramsarname` startswith `aoi.site_prefixes`) and `dea-<uid>` (`load_waterbodies`). Overrides are `water.overrides` keys in `config/pipeline.toml` (ramsar-15, ramsar-28, ramsar-56 today), loaded by `wetland_change.config.load_config` (the `wetland_change` package is importable from scripts).
- `scratch/verify_aoi/repro_objectid.py` named in the review does not exist in the worktree; ignore it.
- `tests/test_fetch_aoi.py` exists with a `_collection()` helper and a `_Response` stub. `test_main_prints_stable_waterbodies_and_raw_ramsar_checksums` uses an empty Ramsar FeatureCollection and must be updated, because the new checks reject it.
- Fixtures: `tests/fixtures/aoi/ramsar_mini.geojson` has objectids 52, 56 (Forrestdale & Thomsons Lakes) and 5 (Lake Warden System).

## Design

All changes are in `scripts/fetch_aoi.py` plus tests and one doc line. No change to `src/`.

1. `require_feature_collection(content: bytes) -> dict[str, Any]`: parse JSON (ValueError "payload is not valid JSON"), require a dict (ValueError "payload is not a JSON object"), require `payload.get("type") == "FeatureCollection"` and `features` to be a non-empty list of dicts (ValueError naming what is wrong). If an `error` key is present, include its text in the message.
2. `check_override_ids(ramsar_payload, waterbodies_payload, overrides, site_prefixes)`: derive the expected present ids: for Ramsar, `ramsar-{properties["objectid"]}` for features whose `properties["ram_ramsarname"]` starts with any site prefix (same selection as `aoi.load_ramsar`); for Waterbodies, `dea-{properties["uid"]}`. Every override key must be in the union. Otherwise raise ValueError listing the missing ids and a hint that SLIP/DEA ids changed and `config/pipeline.toml` `[water.overrides.*]` must be reviewed. Hard failure (not a warning), since a silent mis-attach is a scientific error.
3. `fetch()` gains `validate: Callable[[bytes], None] | None = None`. Order: GET, `raise_for_status`, `require_feature_collection(content)` always, then `validate(content)` if given, then `checksum`, then write. The file is still written only after every check passes, so a prior good file survives a bad response.
4. `main()`: load `CONFIG = Path("config/pipeline.toml")` via `load_config`. Fetch Ramsar to a staging approach is not needed: Ramsar override ids need the Ramsar body, Waterbodies override ids need the Waterbodies body, and both are needed together for the union. So fetch both with only the feature-collection check, but write after the cross check: simplest correct approach is to restructure into `fetch_bytes(url, params) -> bytes` (GET, raise_for_status, require_feature_collection) and `write_checked(content, dest, checksum) -> str`. `main` fetches both bodies, runs `check_override_ids`, then writes both files and prints the rows. If any ValueError occurs, `main` prints `error: <message>` to stderr and returns 1 without writing either file. Keep `fetch()` as a thin wrapper (fetch_bytes + write_checked) so existing tests and callers keep working.

## Steps (TDD, tests first)

1. In `tests/test_fetch_aoi.py` add failing tests (see below), run `uv run pytest tests/test_fetch_aoi.py -q`, confirm red.
2. Implement in `scripts/fetch_aoi.py`; confirm green.
3. Update the existing `test_main_prints_stable_waterbodies_and_raw_ramsar_checksums` to use a realistic Ramsar collection (features with `objectid` and `ram_ramsarname` matching a prefix, ids matching the monkeypatched config's overrides) and monkeypatch `fetch_aoi.CONFIG` to a tmp pipeline TOML (or to a config copy with overrides matching the fixture ids).
4. README.md line ~176 area: add one sentence that `fetch_aoi.py` fails on a non-FeatureCollection response and when an id used by `[water.overrides.*]` is absent from the fetched layers.
5. Run the full verification in order: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. Do not run `-m live`.

## Tests (what each proves)

- `test_require_feature_collection_rejects_arcgis_error_body`: `{"error":{"code":400,"message":"Invalid query"}}` raises ValueError mentioning the error (AC1, the HTTP 200 error body case).
- `..._rejects_html_and_non_object_json`, `..._rejects_wrong_type` (`{"type":"Feature"}`), `..._rejects_missing_or_empty_features`: each shape fails.
- `..._accepts_valid_collection`: returns the parsed dict.
- `test_fetch_rejects_error_body_without_checksum_arg_and_keeps_destination`: Ramsar-style `fetch(url, {}, dest)` with an error body raises and leaves a pre-existing dest unchanged (proves the default raw checksum path is now guarded).
- `test_check_override_ids_passes_when_all_present`: overrides `ramsar-52`, `dea-r3f0` against fixture-like payloads.
- `test_check_override_ids_fails_when_ramsar_id_missing`: objectids renumbered (e.g. 152, 156) makes `ramsar-52` missing; message lists it.
- `test_check_override_ids_ignores_ramsar_features_outside_site_prefixes`: override pointing at an id that exists only on a non-prefix site (objectid 5, Lake Warden System) fails, proving the prefix filter matches `load_ramsar`.
- `test_check_override_ids_fails_when_dea_uid_missing`.
- `test_main_returns_1_and_writes_nothing_when_override_id_missing`: main with renumbered Ramsar ids returns 1, stderr names the missing id, neither output file exists.
- `test_main_returns_1_on_error_body`: Ramsar error body, returns 1, nothing written.
- Updated `test_main_prints_...` still proves checksums rows and bytes written (AC regression).

## Amendment by the worker before build-flow

The planner's check tests only that each override id exists. That misses the story's failure case and the "renamed" half of the second acceptance criterion. The Peel-Yalgorup System alone holds 16 of the fetched polygons (objectids 12 to 16 and 19 to 28), so renumbered objectids would very likely still exist, on a different polygon with the same site name, and a presence check or a name check would both pass.

The check therefore also pins each Ramsar override's identity in `scripts/fetch_aoi.py`: the site name and the polygon bounding box, within 0.001 degrees. Values come from the local DBCA-010 copy at `.worktrees/feature/wetland-change-pipeline/data/external/dbca_010_ramsar_sites.geojson`:

- ramsar-15: Peel-Yalgorup System, (115.7098, -32.688, 115.7165, -32.6734)
- ramsar-28: Peel-Yalgorup System, (115.6838, -32.5718, 115.7086, -32.5599)
- ramsar-56: Forrestdale & Thomsons Lakes, (115.9283, -32.1677, 115.9459, -32.1499)

A Ramsar override with no pinned identity also fails, so a new override has to record one. DEA uids are geohashes of the polygon, so a presence check is enough for `dea-` ids. A one-off run of the script against the live sources confirms the pinned values do not raise a false alarm.

## Implementation Notes

- 2026-11-05T10:38:03.692Z: Gates on the story branch at ab6619e: ruff check, ruff format --check and mypy pass; pytest exits 0 in default mode and with GITHUB_ACTIONS=true. The implementer ran scripts/fetch_aoi.py once against live SLIP and DEA: exit 0, so the pinned site names and bounding boxes raise no false alarm; that result is the implementer's report, not re-run here. The planner's check tested only that override ids exist, so the worker amended the plan to pin site name and bounding box (see the plan's amendment). A legitimate DBCA boundary edit of more than 0.001 degrees on these three polygons will fail the fetch until OVERRIDE_POLYGONS is reviewed, which is intended. src/wetland_change/aoi.py was not changed; README.md was.

## Questions
