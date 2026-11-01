---
id: st-2b8a
title: Add a freshness check for the scheduled job
type: feature
epic: st-f849
priority: P2
depends_on: [st-d4a8]
touches: [README.md, src/wetland_change/cli.py, src/wetland_change/ledger.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/freshness.py, tests/test_cli.py, tests/test_live_verify.py, tests/test_verify_freshness.py]
exclusive: false
created: 2026-10-29
updated: 2026-11-01
---
## Description

Verification matrix row "Scheduled job alive" (design): the ledger matches Earth Search and Copernicus counts per tile over 30 days, and the newest processed item is under 7 days old.

Add `src/wetland_change/verify/freshness.py` and a `wetland-change freshness` command that exits non-zero when any freshness check fails, so the weekly workflow can open an issue. Reuse the Copernicus listing from `src/wetland_change/verify/copernicus.py` (the discovery-check story). Allow 24 hours of latency: items under 24 hours old may be missing from either side.

## Acceptance Criteria

- [ ] Offline test with fake clients: when the newest processed item is 8 days old, `freshness_newest_item` fails; at 6 days it passes.
- [ ] Offline test: a tile whose 30-day ledger count differs from the Earth Search count, ignoring items under 24 hours old, fails `freshness_count_vs_earth_search`. The same holds for `freshness_count_vs_copernicus`.
- [ ] `uv run wetland-change freshness --help` exits 0, and an offline CLI test shows the command exits non-zero when any freshness check fails.
- [ ] Live test marked `live`: 30-day per-tile counts for the six tiles come back from both catalogues without error.

## Implementation Plan

# st-2b8a plan: freshness check and `wetland-change freshness`

Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-2b8a, main at 64ca0d9). The prerequisite `src/wetland_change/verify/copernicus.py` exists (`CDSE_STAC`, `CDSE_COLLECTION`, `LATENCY`, `datatake_key`, private `_Scene`, `_normalise`, `_rfc3339`). No `verify/freshness.py` and no `freshness` command exist yet. `data/external/` (AOI) is absent from the worktree, so the live test cannot load Ramsar polygons and must use a literal bbox. No weekly workflow exists yet (st-ec32 owns it), so this story does not touch `.github/`.

## Design decisions
- Checks are the existing `Check` dataclass (`verify/checks.py`). Names: `freshness_newest_item` (one check), `freshness_count_vs_earth_search` and `freshness_count_vs_copernicus` (one per tile, `detail["tile"]`).
- Window: [now - 30 days, now]. A scene's age is measured on its acquisition `datetime`; scenes sensed less than `LATENCY` (24 h) before `now` may be missing from either side and are reported under `pending_latency`, not counted as mismatches. This is the same rule `discovery_checks` uses.
- Ledger side: the latest ledger row per `item_id` with `status == "succeeded"`, `datetime` inside the window, non-null `tile`.
- ES comparison matches on `item_id`. CDSE comparison matches on `datatake_key(product_uri without .SAFE)`. The check passes when the number of mismatched items outside the latency allowance is 0. `measured` is that number and `threshold` is 0.0. `detail` carries `ledger_count`, `reference_count` (both over the whole window, latency items included), `missing_from_ledger`, `missing_from_reference`, `pending_latency`, `window_start`, `window_end`.
- ES and CDSE listings use the same filter as discovery: cloud below `cfg.cloud_cover_max` and footprint intersecting the AOI polygons, via `normalise_scenes`. Add a local re-check that the sensed time is inside the window.
- Tile universe: `SWAN_TILES = ("50HLJ","50HLK","50HMJ","50HMK","50JLL","50JML")` unioned with any tile seen on any side, so a tile with zero on every side passes (0 equals 0) and still appears.
- Newest item: age in days of the newest succeeded ledger `datetime` against `now`. Pass when under 7 days. `measured` is the age in days, `threshold` is 7.0. An empty ledger fails with `detail["reason"]`.
- A catalogue exception becomes a skipped check (`passed=None`, `detail["error"]`) rather than a crash.
- CLI exit codes: 0 all pass; 3 any check failed; 4 no failure but some check did not run (`passed is None`). Same style as `verify`.

## Steps
1. Make the reused pieces public (no behaviour change; `uv run pytest -q` stays green).
   - `src/wetland_change/verify/copernicus.py`: rename `_Scene` to `Scene`, `_normalise` to `normalise_scenes`, `_rfc3339` to `rfc3339`. Update all uses in that file. Nothing else imports them.
   - `src/wetland_change/ledger.py`: rename `_latest` to `latest_entries` (4 internal uses). Nothing outside imports it.
2. `src/wetland_change/verify/freshness.py` (TDD, tests in `tests/test_verify_freshness.py`).
   - Constants `CHECK_NEWEST = "freshness_newest_item"`, `CHECK_ES = "freshness_count_vs_earth_search"`, `CHECK_CDSE = "freshness_count_vs_copernicus"`, `WINDOW = timedelta(days=30)`, `MAX_AGE = timedelta(days=7)`, `SWAN_TILES`.
   - `newest_item_check(ledger: pa.Table, now) -> Check`.
   - `count_checks(ledger, es_client, cdse_client, cfg: StacConfig, *, bbox, polygons_4326, now) -> list[Check]` returning per-tile ES checks then per-tile CDSE checks.
   - `freshness_checks(ledger, es_client, cdse_client, cfg, *, bbox, polygons_4326, now) -> list[Check]` returning the newest-item check plus the count checks.
   - `tile_counts(client_scenes)` helper used by the live test, returning a `dict[str, int]` of per-tile counts for a listing. A thin public function `list_tile_counts(client, cfg, *, bbox, polygons_4326, start, end, cdse: bool) -> dict[str, int]` is enough.
   - Tests (offline, fakes `RecordingClient`, `es_item`, `cdse_item`, `name` from `tests/test_verify_copernicus.py`; ledger built from `LedgerEntry` and `entries_to_table`; `NOW = 2026-10-29T10:00Z`):
     - newest item 8 days old fails, 6 days old passes, empty ledger fails, a failed-status row does not count as processed, newest chosen across several rows.
     - ES count: ledger and ES agree passes; ES has an extra item sensed more than 24 h ago for one tile makes that tile's check fail while other tiles pass; the same extra item sensed under 24 h ago passes and lands in `pending_latency`; a ledger-only old item fails; items older than 30 days on either side are ignored.
     - CDSE count: same four cases, matched on datatake key despite different processing baselines; a CDSE duplicate of one datatake counts once.
     - All six `SWAN_TILES` appear even with empty listings and an empty ledger; a catalogue exception yields `passed is None` with `detail["error"]`.
3. `src/wetland_change/cli.py`: add `freshness` command (options `--config`, `--output-root`, `--now`), lazily importing `wetland_change.verify.freshness` like `verify`. It loads `_load(config)`, reads the ledger from `_store(...)`, builds `open_client(cfg.stac.endpoint)` and `open_client(CDSE_STAC)` through the module-level `open_client` (so tests can monkeypatch `cli.open_client`), calls `freshness_checks`, echoes one `pass|skip|FAIL<TAB>name<TAB>measured<TAB>tile` line per check, and exits 3 / 4 as above. Update the module docstring command list. Tests in `tests/test_cli.py`: `freshness --help` exits 0 and lists `--config`, `--output-root`, `--now`; add `freshness` to the `--output-root` parametrisation and to `test_help_lists_commands`; an offline CLI test with a ledger in `tmp_path` whose newest item is 8 days old exits 3 and prints `FAIL`; an all-green ledger and matching fake clients exits 0.
4. `tests/test_live_verify.py`: add `test_freshness_counts_for_six_tiles` (module is already `live`-marked). Use a literal bbox `(115.0, -33.2, 116.4, -31.3)` with `box(*bbox)` polygon, `end = datetime.now(UTC)`, `start = end - 30 days`. Call `list_tile_counts` against `open_client(cfg.stac.endpoint)` and `open_client(CDSE_STAC)` (config from `config/pipeline.toml`). Assert no exception and that each of `SWAN_TILES` is a key in both returned dicts with an int value. Also run `freshness_checks` with an empty ledger and assert no check has `passed is None`.
5. `README.md`: add one line naming `wetland-change freshness` beside the other commands. No `data/SOURCES.md` change (no new dataset; the CDSE row already exists via the discovery story).
6. Verify in order: ruff check, ruff format --check, mypy, pytest. Run `uv run pytest -q -m live tests/test_live_verify.py -k freshness` once before handoff.

## Implementation Notes

## Questions
