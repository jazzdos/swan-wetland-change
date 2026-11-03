---
id: st-779a
title: Align the --now help text with how a value without a zone is read
type: bug
priority: P3
depends_on: []
discovered_from: st-b983
touches: [src/wetland_change/cli.py, tests/test_cli.py]
exclusive: false
created: 2026-11-02
updated: 2026-11-03
---

## Description

The st-b983 planner found that the --now help text says UTC, but a value without a zone is read as local time. On an AWST machine that is an 8 hour difference in the run id and any date derived from it. The st-b983 driver works around this by passing local time. Out of scope in st-b983, which may not change src/.

## Acceptance Criteria

- [ ] A test passes a --now value without a zone and asserts how it is read
- [ ] The --now help text states that same reading

## Implementation Plan

## Findings (verified in the st-779a worktree)

- `src/wetland_change/cli.py` has four commands (`run` line ~113, `backfill` ~151, `score` ~200, `freshness` ~280) that each declare `now: Annotated[datetime | None, typer.Option(help="Run time, UTC")]` and compute `when = (now or datetime.now(UTC)).astimezone(UTC)`.
- The option's click type is `DateTime` with formats `%Y-%m-%d`, `%Y-%m-%dT%H:%M:%S`, `%Y-%m-%d %H:%M:%S`. Every value the CLI can receive is therefore naive; no zone-bearing value is accepted.
- `naive.astimezone(UTC)` reads a naive datetime as the machine's local time. So the behaviour is "local time, converted to UTC" and the help text "UTC" is wrong. On an AWST machine `2026-10-29T10:00:00` becomes `2026-10-29T02:00:00+00:00`.
- The st-b983 backfill driver passes local time, so the behaviour stays as is. Only the help text and a test change. No logic change.
- Existing tests in `tests/test_cli.py` use `runner`, `_patch_cli`, `FakeClient`, `_polygons`, `NOW`, and monkeypatching `cli._load` / `cli.open_client`. `freshness` tests pass `--now` as `FRESH_NOW = "2026-10-29T10:00:00"`.

## Steps

1. Test first, in `tests/test_cli.py` (append near the other `run` tests; add `import time` and `from datetime import UTC, datetime` at the top if absent):
   - A fixture `perth_tz(monkeypatch)` that does `monkeypatch.setenv("TZ", "Australia/Perth")`, `time.tzset()`, and on teardown restores the prior TZ (monkeypatch undoes the env var; call `time.tzset()` again after undo via a `yield` fixture).
   - `test_now_without_zone_is_read_as_local_time(monkeypatch, tmp_path, perth_tz)`: use `_patch_cli`-style patching (`cli._load` returns a config and polygons, `cli.open_client` returns a `FakeClient`), patch `cli.run_once` with a recorder that captures the `now` kwarg and returns an object with `to_json()` returning "{}" and `failed` falsy (a small stub class). Invoke `run --config <file> --output-root <tmp> --now 2026-10-29T10:00:00`. Assert exit code 0 and that the captured `now == datetime(2026, 10, 29, 2, 0, tzinfo=UTC)`. This proves a value without a zone is read as machine-local time (AWST, UTC+8), not UTC.
   - `test_now_help_states_local_time_reading`: parametrize over `run`, `backfill`, `score`, `freshness`; invoke `<cmd> --help`; collapse whitespace and box-drawing (`" ".join(output.replace("│", " ").split())`) and assert the phrase `without a zone is read as local time` appears. Set `COLUMNS=200` via `runner.invoke(..., env={"COLUMNS": "200"})` to avoid awkward wrapping, and still normalise whitespace.
   - Run the new tests: the help test fails (RED) while the old help says "UTC".
2. In `src/wetland_change/cli.py`, add one module constant after `OutputRootOption`:
   `NOW_HELP = "Run time as YYYY-MM-DD[THH:MM:SS]. A value without a zone is read as local time on this machine, then converted to UTC. Omitted means the current time."`
   Make sure the phrase `without a zone is read as local time` stays contiguous. Replace `help="Run time, UTC"` with `help=NOW_HELP` in all four commands. Do not change the `.astimezone(UTC)` logic. Optionally add a `NowOption = Annotated[datetime | None, typer.Option(help=NOW_HELP)]` alias and use it in all four signatures; either is fine as long as mypy passes.
3. Run the new tests (GREEN), then the full verification in order, one command per line:
   - `uv run ruff check src tests scripts`
   - `uv run ruff format --check src tests scripts` (run `uv run ruff format` on the two touched files if needed)
   - `uv run mypy src scripts`
   - `uv run pytest -q`
4. Commit on branch `story/st-779a` with message `st-779a: align the --now help text with local-time reading of values without a zone`, ending with the line `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## What each test proves

- `test_now_without_zone_is_read_as_local_time`: a `--now` value with no zone, under TZ=Australia/Perth, reaches `run_once` as 02:00 UTC for 10:00 input. Pins the local-time reading the st-b983 driver depends on.
- `test_now_help_states_local_time_reading` (4 params): each command's `--now` help states that same reading, so help and behaviour cannot drift.

## Constraints

Do not touch `.worktrees/st-b983` or `/Users/jarrodbaker/Documents/swan-wetland-change-data`. Never use pkill or pgrep patterns matching wetland-change or the driver. `data/external` in the worktree is a gitignored symlink; leave it alone. Only `src/wetland_change/cli.py` and `tests/test_cli.py` change.

## Implementation Notes

## Questions
