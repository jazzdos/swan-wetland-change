---
id: st-fbe8
title: Refuse a reused run id in the daily run
type: bug
epic: st-f849
priority: P3
depends_on: []
touches: [src/wetland_change/cli.py, src/wetland_change/pipeline.py, tests/test_cli.py, tests/test_pipeline.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-06
---

## Description

Two run calls with the same --now overwrite the earlier ledger file and manifest. Only a manual dispatch with a repeated --now reaches this. backfill_once already refuses the same case. Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md L9.

## Acceptance Criteria

- [ ] run_once raises when the run id already has a manifest or ledger file in the output root

## Implementation Plan

## Findings from the worktree (branch story/st-fbe8, from main 86f75c6)

The library half of this story already exists on main. `run_once` in `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-fbe8/src/wetland_change/pipeline.py` (line 423) calls `_refuse_reused_run_id(store, run_id, ledger=ledger, paths=paths)` right after `read_ledger_parts` and before anything is written. The helper (line 602) is shared with `backfill_once` and raises `ValueError("run id ... already has a manifest or ledger parts in the output root; rerun with a later --now ...")` when the manifest exists, a `ledger_<run_id>_*` part exists, or the run id is in the ledger table. It came in with st-5241 and st-357a. `tests/test_pipeline.py::test_run_once_refuses_reused_run_id` (line 476) and `test_run_once_refuses_a_run_id_whose_parts_were_compacted_away` (line 1378) cover it. So the acceptance criterion holds at the library level and no second mechanism is needed.

What is still missing:
1. `cli.run` (`src/wetland_change/cli.py`, line 143 onward) catches only `PlaceholderBaseUrlError`. A reused `--now` on the daily run therefore ends in a raw ValueError traceback, while `backfill`, `score` and `requeue` already turn `ValueError` into `typer.BadParameter` (exit 2). No CLI test covers a reused run id for any command.
2. The existing run_once test only checks that it raises. It does not prove nothing is overwritten, and it does not cover the "ledger parts remain but the manifest is gone" case.

Decision for the CLI: `cli.run` should turn the refusal into a clean `typer.BadParameter` (exit 2, message shown, no traceback), matching `backfill`. Do not catch bare `ValueError` in `run`, because `run_once` can raise other ValueErrors (for example `SceneGridError`, `ObservationFrameError`) that must not be mislabelled as a bad parameter. So add a tiny subclass `RunIdReusedError(ValueError)` in `pipeline.py`, raised by `_refuse_reused_run_id` with the same message. Because it subclasses ValueError, `backfill_once`, `requeue_once`, and every existing `pytest.raises(ValueError, match=...)` keep working unchanged, and the `backfill` CLI path is untouched. Exit code 2 also means "scenes failed" for `run`; that overlap already exists for `backfill` and is accepted.

## Steps (single task, one batch)

1. `src/wetland_change/pipeline.py`: define `class RunIdReusedError(ValueError)` with a one-line docstring next to `SceneGridError` (line 71). In `_refuse_reused_run_id` raise `RunIdReusedError` instead of `ValueError`, message text unchanged. Do not touch `run_once`'s signature, its `wo_lookup` / `wo_reader_factory` arguments, `_process_one`, `process_scene`, or the position of the refusal call. `score_once` (line 741) has its own inline manifest check; leave it alone.
2. `src/wetland_change/cli.py`: import `RunIdReusedError` from `wetland_change.pipeline`. In `run`, change `except PlaceholderBaseUrlError as exc:` to `except (PlaceholderBaseUrlError, RunIdReusedError) as exc:` with the same `raise typer.BadParameter(str(exc)) from exc`. Leave the `wo_lookup=find_wo_href` and `wo_reader_factory=dea_reader` arguments intact.
3. Tests, written before the source change so they fail first (kit:tdd):
   - `tests/test_pipeline.py`, strengthen `test_run_once_refuses_reused_run_id`: after the first `_run`, snapshot `{relative path: bytes}` for every file under `tmp_path / "out"`; the second `_run` with the same `NOW` must raise `RunIdReusedError` (match `already has`); the snapshot must be identical afterwards, proving no ledger part, manifest or observation file was touched. This is red against the current code only on the exception type, so also keep the byte comparison as the guard for "overwrite".
   - `tests/test_pipeline.py`, new `test_run_once_refuses_a_run_id_with_ledger_parts_but_no_manifest`: do one run, delete `runs/<new_run_id(NOW)>.json` from the store, rerun with the same `NOW`, expect `RunIdReusedError`, and expect the file listing and ledger bytes unchanged. This proves the ledger-file branch of the check independently of the manifest branch.
   - `tests/test_cli.py`, new `test_run_refuses_a_reused_run_id` using `_patch_cli`, `FakeClient([fixture_item])` and `runner.invoke(app, ["run", "--config", ..., "--output-root", str(root), "--now", "2026-10-29T10:00:00"])` twice. First exit 0. Second: `exit_code == 2`, `result.exception` is a `SystemExit` (not a raw ValueError), `"already has"` appears in the whitespace-collapsed, `click.unstyle`d output, and the file snapshot under `root` is unchanged. This proves the CLI gives a clear non-zero exit rather than a traceback and writes nothing.
   - Existing `tests/test_backfill.py` reuse tests and the golden run test stay green without regeneration; they prove behaviour is unchanged for a new run id and for backfill.
4. Run the gates, one per line, and judge each by exit code: `uv run ruff check src tests scripts`; `uv run ruff format --check src tests scripts`; `uv run mypy src scripts`; `uv run pytest -q`; `GITHUB_ACTIONS=true uv run pytest -q`. Never clear addopts; for a count use `-o addopts="-m 'not live'"`. Commit nothing; do not edit `stories/**` or `.agents/shousper-stories/local/**`.
## Orchestrator amendments

These override the text above where they differ.

1. Commit nothing; the orchestrator commits. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**. Never call AWS for the project's own bucket. Never run terraform. No live tests in the default suite. Judge pytest by exit code and never clear addopts; for a count use -o addopts="-m 'not live'". Also run GITHUB_ACTIONS=true uv run pytest -q. Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data. Docs and comments are flat factual prose with no em dashes.
2. Exit code 2 for a refused run is accepted. .github/workflows/pipeline.yml redirects the stdout of `wetland-change run` into "$RUNNER_TEMP/run-manifest.json", fails the step on any non-zero exit, and the next step treats an empty or missing manifest as processed 0 with no recovered runs. So the CLI test in step 1c must also assert that the refused second call prints nothing to stdout (the BadParameter message goes to stderr; with the project's CliRunner check `result.stdout` is empty, or if stdout and stderr are mixed in this click version, assert the output does not parse as JSON). Do not edit pipeline.yml.
3. The story's touches list names pipeline.py and tests/test_pipeline.py; cli.py and tests/test_cli.py are also in scope for this story. Change nothing else.

## Implementation Notes

- 2026-11-06T02:49:44.869Z: The library refusal already existed (_refuse_reused_run_id from st-5241, shared with backfill_once). Added RunIdReusedError(ValueError); cli.run maps it to BadParameter (exit 2, message on stderr, empty stdout so the workflow's redirected manifest stays empty). Tests: byte snapshot unchanged after a refused rerun, a rerun with ledger parts but no manifest is refused, and a CLI test for exit 2. 841 passed, 9 deselected; all five gates exit 0.

## Questions
