---
id: st-1731
title: Strip terminal styling from the CLI help assertions so CI passes
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [tests/test_change_outputs.py, tests/test_cli.py]
exclusive: false
created: 2026-11-03
updated: 2026-11-04
---

## Description

The tests workflow fails on main at 2049247 (run 41657810532) with 10 failures: test_score_help_lists_range_and_output_root in tests/test_change_outputs.py and nine help tests in tests/test_cli.py. A fresh local clone passes. Typer forces a Rich terminal when GITHUB_ACTIONS is set (typer/rich_utils.py:80 in the locked 0.27.3), so help output carries ANSI styling that splits option names, for example an escape code between the two leading dashes of --start. The assertions compare raw output. Reproduce with GITHUB_ACTIONS=true uv run pytest -q, which gives the same 10 failures. click.unstyle on the help output restores the option names under that variable. The product is not affected: no workflow reads help output. The earlier run 40896766197 on 2026-10-29 also failed at the pytest step and includes test_run_help_mentions_config.

## Acceptance Criteria

- [ ] GITHUB_ACTIONS=true uv run pytest -q exits 0
- [ ] uv run pytest -q exits 0
- [ ] The change touches only test files
- [ ] The tests workflow passes on main after the next push

## Implementation Plan

## Implementation Notes

- 2026-11-04T00:10:00.611Z: Implemented by cloud session https://claude.ai/code/session_01FNRugNj1V9qyTgewLVHeDc as e478498 and merged into story/st-1731 as 67c4d2f. Local gates on that merge: ruff, ruff format and mypy pass; pytest 438 passed and 1 skipped with and without GITHUB_ACTIONS=true. Before the merge the same help tests gave 10 failures under GITHUB_ACTIONS=true. The fourth criterion, the tests workflow on main, is checked after the push.

## Questions
