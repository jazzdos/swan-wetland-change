---
id: st-1381
title: Name expired exported AWS credentials in the credentialed live test
type: bug
priority: P2
depends_on: []
touches: [README.md, tests/aws_support.py, tests/test_aws_support.py, tests/test_live_credentialed_read.py, tests/test_readme.py]
exclusive: false
created: 2026-11-16
updated: 2026-11-17
---
## Description

The live suite on main ebea401 (2026-11-16, started 11:35:52Z, 27m39s) failed one test: `tests/test_live_credentialed_read.py::test_credentialed_reader_globs_observations`. DuckDB raised `HTTP 400 Bad Request ... ExpiredToken: The provided token has expired.` followed by its generic hint "this can be caused by the S3 region being set incorrectly. Provided region is: ap-southeast-2". The region is correct.

Root cause: the suite used the README route for an `aws login` profile (`login_session` in `~/.aws/config`): `eval "$(aws configure export-credentials --profile <profile> --format env)"` and `unset AWS_PROFILE`. Credentials exported from an `aws login` profile expire 15 minutes after they are minted (export at 12:04:13Z gave `AWS_CREDENTIAL_EXPIRATION=2026-11-16T12:19:13+00:00`), and nothing refreshes them once they are environment variables. pytest collects `tests/test_backfill.py` and `tests/test_live_anonymous_read.py` before the credentialed test, and the credentials were past their lifetime when it ran. Rerun alone with a fresh export at 12:04:48Z, the test passed in 19.2 s. The other nine live tests passed.

The test reports the failure as a raw DuckDB error whose last line points at the region, and the README says only that the exported variables are short-lived. The README limitations bullet on the credentialed S3 query also still says no agent has run `tests/test_live_anonymous_read.py`; it passed in this run.

Found while running the live suite for Jarrod's 'approve all' on 2026-11-16. No claimed story covers it.

## Acceptance Criteria

- [ ] When the S3 read in `tests/test_live_credentialed_read.py` raises an error whose text contains `ExpiredToken`, the test fails with a message that names expired environment credentials, the 15 minute lifetime of credentials exported from an `aws login` profile and the re-export command from "Querying with DuckDB" in README.md.
- [ ] A non-live test covers that message with a stubbed DuckDB error and no network access.
- [ ] README.md "Querying with DuckDB" states that credentials exported from an `aws login` profile expire 15 minutes after they are minted and are not refreshed in the environment.
- [ ] README.md gives a live-suite invocation that runs `tests/test_live_credentialed_read.py` on its own, directly after a fresh export.
- [ ] The README limitations bullet that says no agent has run `tests/test_live_anonymous_read.py` keeps its sentence and gains a dated 2026-11-16 update stating it passed in the live run on main ebea401.
- [ ] uv run ruff check src tests scripts exits 0.
- [ ] uv run ruff format --check src tests scripts exits 0.
- [ ] uv run mypy src scripts exits 0.
- [ ] uv run pytest -q exits 0.

## Implementation Plan

Verified in worktree /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-1381 (HEAD 0a328d2, which descends from ebea401). All pointers hold: tests/test_live_credentialed_read.py, tests/aws_support.py (has EXPORT_COMMAND, credential_source, _redact, create_credential_chain_secret), tests/test_aws_support.py (has _FakeConnection, clean_env fixture), tests/test_readme.py (test_readme_documents_aws_login_profile_route, _section helper), README.md "Querying with DuckDB" (~line 391-425) and the limitations bullet (~line 631-643). Default addopts is `-m 'not live'`, so a test in test_aws_support.py runs in the default suite.

Steps (TDD, one batch, two tasks that touch disjoint files):

1. Test first, tests/test_aws_support.py: add
   - `test_expired_token_guard_names_lifetime_and_reexport`: wrap `raise duckdb.Error("HTTP 400 Bad Request ... ExpiredToken: The provided token has expired. ... Provided region is: ap-southeast-2")` in `with fail_on_expired_credentials():` and assert `pytest.fail.Exception` with message containing "expired", "15 minutes", "aws login", `aws configure export-credentials`, "--format env", "unset AWS_PROFILE" (i.e. EXPORT_COMMAND), and not containing "region is" advice-as-cause (optionally include DuckDB text redacted). Proves the message content with no network.
   - `test_expired_token_guard_redacts_credentials_and_does_not_chain`: sentinel env creds in the error text are replaced by `<redacted>`; `__cause__` None and context None or suppressed (same pattern as test_secret_failure_never_prints_credentials).
   - `test_expired_token_guard_passes_other_errors_through`: `duckdb.Error("Secret Validation Failure")` and a non-duckdb ValueError propagate unchanged (pytest.raises(duckdb.Error)), and no exception means no failure.
   - `test_live_credentialed_test_reports_expired_token`: import `tests.test_live_credentialed_read as live_mod`; monkeypatch `live_mod.configured_bucket` to return ("h","b","ap-southeast-2"), `live_mod.credential_source` to return "AWS_ACCESS_KEY_ID (environment keys)", `live_mod.create_credential_chain_secret` to a no-op, and `live_mod.duckdb.connect` to return a stub connection whose `execute` returns an object for INSTALL/LOAD statements and raises `duckdb.Error("... ExpiredToken ...")` for any statement containing "read_parquet". Call `live_mod.test_credentialed_reader_globs_observations()` inside `pytest.raises(pytest.fail.Exception)` and assert the message names expired environment credentials, "15 minutes" and the export command. Proves the live test itself is wired to the guard, with no network. (monkeypatching `live_mod.duckdb.connect` patches the global duckdb module; use monkeypatch.setattr so it is undone.)
   Run `uv run pytest -q tests/test_aws_support.py` and see these fail (ImportError of fail_on_expired_credentials).
2. Implement in tests/aws_support.py: add `EXPIRED_TOKEN_MARKER: Final = "ExpiredToken"` and a `@contextmanager def fail_on_expired_credentials() -> Iterator[None]` (import `contextlib.contextmanager`, `collections.abc.Iterator`). It yields inside try; `except duckdb.Error as err:` if `EXPIRED_TOKEN_MARKER in str(err)` build message ("The AWS credentials in the environment have expired (DuckDB reported ExpiredToken). Credentials exported from an `aws login` profile expire 15 minutes after they are minted and are not refreshed once they are environment variables. Export fresh credentials and rerun this test on its own: {EXPORT_COMMAND}. DuckDB error: {_redact(str(err))}. The region hint in that error is not the cause when the region is correct.") else `raise`. Same pattern as create_credential_chain_secret: record the message in a variable inside the except, and call `pytest.fail(message, pytrace=False)` outside the except block so the unredacted error is not chained. Careful with re-raising non-matching errors (bare `raise` inside except is fine). Update the module docstring to mention the helper.
3. Wire it in tests/test_live_credentialed_read.py: import `fail_on_expired_credentials`; wrap the two `con.execute(...).fetchone()` S3 reads (row count and glob count) in `with fail_on_expired_credentials():`. Keep asserts outside the with block. Keep the module docstring, and add the standalone run line `Run with: uv run pytest -q -m live tests/test_live_credentialed_read.py` (already present; keep). Do not wrap INSTALL/LOAD/secret creation (secret failures keep their st-b49e message).
4. README, test first in tests/test_readme.py: add `test_readme_documents_credential_expiry` asserting within "Querying with DuckDB" prose (SQL blocks stripped) the strings "15 minutes", "aws login", "not refreshed", and `test_readme_gives_standalone_credentialed_live_command` asserting the section contains `uv run pytest -q -m live tests/test_live_credentialed_read.py` and that the line sits in a ```sh block after the `export-credentials` line (index compare). Add `test_readme_limitations_dates_anonymous_live_pass` asserting the Limitations section (use `_section(_readme(), "Limitations")` if that heading exists; check with grep of `^## ` first) contains both "no agent has run it" and "2026-11-16" and "ebea401" near "test_live_anonymous_read". Run and see them fail.
5. README.md edits:
   a. In "Querying with DuckDB", replace the sentence "The exported variables are short-lived secrets. Do not print, log or commit them." with: exported variables are secrets, do not print/log/commit them; credentials exported from an `aws login` profile expire 15 minutes after they are minted (`AWS_CREDENTIAL_EXPIRATION` in the exported environment gives the time) and are not refreshed once they are environment variables; an expired export makes DuckDB fail with `HTTP 400 ... ExpiredToken` followed by a hint about the S3 region, which is misleading when the region is correct; re-run the export command and the query within 15 minutes.
   b. After that, add a sh block giving the standalone live invocation: the `eval "$(aws configure export-credentials --profile <profile> --format env)"` line, `unset AWS_PROFILE`, then `uv run pytest -q -m live tests/test_live_credentialed_read.py`, with one sentence saying to run it directly after a fresh export, and that running the whole `-m live` suite from one export can outlast 15 minutes (the 2026-11-16 run took 27m39s) so the credentialed test should run first or alone. Also tweak the Verification-area sentence on live tests (~line 388) only if needed; not required.
   c. In the limitations bullet (~line 631-643), keep the existing sentence "...and no agent has run it (the weekly `verify.yml` run executes it)." intact and add a following sentence: "Update 2026-11-16: `tests/test_live_anonymous_read.py` passed in the live run on main ebea401 (started 11:35:52Z, 27m39s); the only live failure in that run was the credentialed test, from expired exported credentials (README 'Querying with DuckDB')." Do not reword the earlier sentence. Also optionally append "and, on ExpiredToken, names expired environment credentials (st-1381)" to the credentialed-live-test clause.
6. Verify in order, one command per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts` (run `uv run ruff format tests` if it needs it), `uv run mypy src scripts`, `uv run pytest -q`. All must exit 0. Do not run live tests. No new datasets, so data/SOURCES.md is untouched. Commit on the story branch.
