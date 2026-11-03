---
id: st-56b8
title: Make the DEA Waterbodies checksum stable across fetches
type: bug
priority: P3
depends_on: []
discovered_from: st-b983
touches: [data/SOURCES.md, scripts/fetch_aoi.py, tests/test_fetch_aoi.py]
exclusive: false
created: 2026-11-02
updated: 2026-11-03
---

## Description

data/SOURCES.md records DEA Waterbodies sha f89e7b98 (fetched 2026-10-29), but scripts/fetch_aoi.py returned af28cf9d and then c395428f on 2026-11-02. The WFS GeoJSON carries a top-level timeStamp field that changes on every request, so the checksum changes on every fetch. A content comparison of f89e7b98 against c395428f found 1404 features in both, the same uids in the same order, and zero differences in geometry or properties. The recorded checksum therefore cannot detect a real change in the polygon set. Out of scope in st-b983, which may not change data/ or scripts.

## Acceptance Criteria

- [ ] Two payloads that differ only in timeStamp produce the same recorded checksum
- [ ] shown by a test
- [ ] Two payloads that differ in one feature's geometry produce different checksums
- [ ] shown by a test
- [ ] The DEA row in data/SOURCES.md records the stable checksum and says what it covers

## Implementation Plan

## Findings

- `scripts/fetch_aoi.py` `fetch()` returns sha256 of the raw response bytes. The DEA WFS GeoJSON has a top-level `timeStamp` (for example `2026-10-29T11:21:48.987Z`) that changes per request. Other top-level keys: `type`, `features`, `totalFeatures`, `numberMatched`, `numberReturned`, `crs`. These are stable and stay in the hash.
- `tests/test_fetch_aoi.py` does not exist. `scripts` is a package (`scripts/__init__.py`) and `tests` is a package, so `from scripts.fetch_aoi import ...` works under pytest from the repo root.
- `data/SOURCES.md` line 7 is the DEA Waterbodies v3 (Swan subset) row, sha `f89e7b98...`. The file on disk at `data/external/dea_waterbodies_v3_swan.geojson` (a symlink to a shared copy) is the 2026-10-29 fetch and its raw sha256 matches `f89e7b98e6f03ab9ae8bca3f29f14c5deda92db71f98554ebba8b4dee6be39df`. So the stable checksum can be computed from it read-only, with no refetch.
- Constraint: do NOT run `scripts/fetch_aoi.py` or write anything through `data/external` (it would overwrite the shared copy). Do not touch `.worktrees/st-b983` or `/Users/jarrodbaker/Documents/swan-wetland-change-data`. No pkill/pgrep on wetland-change or driver patterns.

## Design

Add `stable_geojson_checksum(content: bytes) -> str` to `scripts/fetch_aoi.py`: parse JSON, drop the top-level `timeStamp` key, re-serialise with `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, UTF-8 encode, sha256 hex. Key-order and whitespace invariance is a side benefit. Anything else (feature geometry, properties, `numberMatched`, `crs`) still changes the hash.

Change `fetch()` so the file is still written as the raw bytes, but it returns the raw sha256. Add a `checksum` parameter (a `Callable[[bytes], str]`, default raw sha256) so the Ramsar call is unchanged and the waterbodies call passes `stable_geojson_checksum`. The printed DEA row notes the checksum covers the payload minus `timeStamp`. Update the module docstring accordingly.

## Steps

1. Create `tests/test_fetch_aoi.py` first (TDD, red):
   - `test_checksum_ignores_timestamp`: two payloads built with `json.dumps`, identical except top-level `timeStamp`, give equal `stable_geojson_checksum`. Proves AC1. Also assert the raw sha256 of the two byte strings differ, so the test would fail under the old behaviour.
   - `test_checksum_changes_with_one_feature_geometry`: payload with 2 features; second payload moves one vertex of one feature's geometry; checksums differ. Proves AC2.
   - `test_checksum_changes_with_property_change` (one property value edited): checksums differ.
   - `test_checksum_ignores_key_order_and_whitespace`: same payload dumped with `indent=2` and reversed key order gives the same checksum.
   - `test_fetch_writes_raw_bytes_and_returns_given_checksum`: monkeypatch `scripts.fetch_aoi.requests.get` to return a stub with `.content` and `raise_for_status()`; call `fetch(url, params, tmp_path / "x.geojson", checksum=stable_geojson_checksum)`; assert the file bytes equal the raw content and the returned value equals the stable checksum (not the raw sha). Use `tmp_path` only; never write to `data/external`.
   - `test_stable_checksum_rejects_non_json`: invalid bytes raise `ValueError` (json.JSONDecodeError is a subclass).
   Run `uv run pytest tests/test_fetch_aoi.py -q` and confirm it fails with ImportError.
2. Implement in `scripts/fetch_aoi.py`: `import json`, `from collections.abc import Callable`, the `stable_geojson_checksum` function with a docstring explaining the WFS `timeStamp`, the `checksum` parameter on `fetch`, the waterbodies call passing the stable function, and the printed DEA row text. Keep mypy strict clean (full annotations). Run the test file green.
3. Compute the stable checksum of the existing on-disk file read-only, with the same function: `uv run python -I -c "from pathlib import Path; from scripts.fetch_aoi import stable_geojson_checksum as s; print(s(Path('data/external/dea_waterbodies_v3_swan.geojson').read_bytes()))"` (run from the worktree root so `scripts` imports; if `-I` blocks the cwd import, use `PYTHONPATH=. uv run python -c ...`). Read-only, no network. Optionally cross-check on any other local copy of the c395428f/af28cf9d payload if one exists under `scratch/` or the shared data directory (read only), expecting the same value, which shows the AC claim on real data. Do not refetch.
4. Edit `data/SOURCES.md` line 7: set fetched date to `2026-10-29`, replace the sha256 cell with the stable checksum, and say what it covers in the row (for example in the sha256 cell: `<64-hex> (sha256 of the canonical JSON, sorted keys and compact separators, with the top-level timeStamp removed; raw-bytes sha256 of the 2026-10-29 file was f89e7b98..., which changes per fetch)`). Keep the 7-column table shape. Add a short note under the table if the cell becomes unwieldy.
5. Add a "How checksums are computed" note below the table in `data/SOURCES.md` (one or two lines) pointing at `scripts/fetch_aoi.py::stable_geojson_checksum`. Ramsar row stays raw-bytes (the SLIP ArcGIS GeoJSON has no timestamp field; leave unchanged and note this).
6. Run the verification commands in order, one per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. Fix any failure. Commit on the story branch.

## What the tests prove

- AC1: payloads differing only in `timeStamp` have equal recorded checksums while raw sha256s differ.
- AC2: a one-vertex geometry change in one feature gives a different checksum.
- AC3: the SOURCES.md DEA row holds the value computed by the shipped function from the real 1404-feature file, with a coverage statement.
- `fetch()` still writes the unmodified response bytes, so the downloaded file is untouched by the change.

## Implementation Notes

## Questions
