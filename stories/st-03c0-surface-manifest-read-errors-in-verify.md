---
id: st-03c0
title: Surface manifest read errors in verify
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [README.md, src/wetland_change/cli.py, src/wetland_change/verify/run.py, tests/test_cli.py, tests/test_verify.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

latest_run_id catches OSError and continues (src/wetland_change/verify/run.py:89), so a permission or credential failure reading a manifest is silent and verify checks an older run or exits 2. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md L5.

## Acceptance Criteria

- [ ] An OSError while reading a run manifest makes verify exit non-zero with the path in the message

## Implementation Plan

Verified in worktree /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-03c0 (HEAD 73f4de0). The pointer is still accurate: `src/wetland_change/verify/run.py:89` has `except (ValueError, TypeError, OSError): continue` inside `latest_run_id`. The only caller is `verify` in `src/wetland_change/cli.py` (~L247-266), which currently turns None into `typer.BadParameter` (exit 2). Existing verify exit codes: 2 usage, 3 failed check, 4 nothing scored. Existing test of `latest_run_id`: `tests/test_verify.py::test_scenes_for_run_and_latest_run_id` (~L503). CLI test pattern: `tests/test_cli.py::test_verify_reads_the_override_root` (uses `_patch_cli`, `runner`, `_polygons`). OutputStore.read_bytes (src/wetland_change/store.py) raises OSError subclasses from pyarrow on permission/credential failure.

Design: stop swallowing OSError. `latest_run_id` wraps the read in try/except OSError and raises a new `ManifestReadError(OSError)` whose message names the manifest path (and the store URI). Malformed JSON (ValueError/TypeError) is still skipped, as before. The `verify` CLI command catches `ManifestReadError`, prints the message to stderr and exits with code 5 (new, distinct from 2/3/4).

Steps (TDD):
1. tests/test_verify.py: add `test_latest_run_id_raises_on_manifest_oserror`. Build a store in tmp_path with `runs/20261029T100000Z.json` = '{"processed": 1}' and a newer `runs/20261030T100000Z.json`. Monkeypatch `OutputStore.read_bytes` to raise `PermissionError("denied")` for the newer path and delegate otherwise. Assert `pytest.raises(ManifestReadError)` and that `"runs/20261030T100000Z.json"` is in `str(exc)`. Proves the error is not skipped and an older run is not silently chosen. Also add a test that a malformed-JSON newer manifest is still skipped (guards the narrowed except). Run: red.
2. tests/test_cli.py: add `test_verify_exits_nonzero_when_a_manifest_cannot_be_read`: same setup as `test_verify_reads_the_override_root` (two manifests under an override root, patch `OutputStore.read_bytes` to raise PermissionError for the newest manifest, patch `wetland_change.verify.run.verify_run` to raise AssertionError if called). Invoke verify; assert `exit_code == 5` and the manifest relative path in `result.output`. Proves the AC end to end. Red.
3. src/wetland_change/verify/run.py: add `class ManifestReadError(OSError)`; change `latest_run_id` as designed (read inside `try/except OSError as exc: raise ManifestReadError(f"cannot read run manifest {path} under {store.uri}: {exc}") from exc`; the int/json parse stays in its own try with `except (ValueError, TypeError): continue`). Update docstring. Green for step 1.
4. src/wetland_change/cli.py `verify`: import `ManifestReadError`; wrap `target = run_id or latest_run_id(store)` in try/except ManifestReadError -> `typer.echo(str(exc), err=True)`; `raise typer.Exit(code=5)`. Green for step 2.
5. Run the full verification sequence from AGENTS.md, one per line: ruff check, ruff format --check, mypy, pytest -q. Fix any lint/format.

## Implementation Notes

- 2026-11-05T11:43:52.733Z: Commit 53dfb2b. pytest exit 0 in default mode and with GITHUB_ACTIONS=true; build-flow verification reported ruff, format and mypy clean. verify gains exit 5 for an unreadable manifest, recorded in README.md. Only the automatic latest-run lookup is covered: an explicit --run-id does not read manifests through latest_run_id.

## Questions
