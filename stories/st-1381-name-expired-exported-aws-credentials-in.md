---
id: st-1381
title: Name expired exported AWS credentials in the credentialed live test
type: bug
priority: P2
depends_on: []
touches: [tests/test_live_credentialed_read.py, README.md]
exclusive: false
created: 2026-11-16
updated: 2026-11-16
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
