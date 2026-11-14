---
id: st-b49e
title: "Say how a reader with an aws login profile gives DuckDB credentials, and make the live test report it"
type: bug
priority: P3
depends_on: []
discovered_from: st-bbbf
touches: [README.md, tests/aws_support.py, tests/test_aws_support.py, tests/test_live_private_outputs.py, tests/test_readme.py]
exclusive: false
created: 2026-11-14
updated: 2026-11-14
---

## Description

Found on 2026-11-14 while running the live suite on merged main (a0693ba) with AWS_PROFILE=accu-tracker. Both tests in tests/test_live_private_outputs.py failed with '_duckdb.Error: Secret Validation Failure: during create using the following: Profile: accu-tracker, Credential Chain: config' at the CREATE SECRET (TYPE s3, PROVIDER credential_chain) statement. The profile holds only region, output and login_session, which is what 'aws login' (aws-cli 2.36.19) writes; aws configure list shows the key type as login. The AWS CLI resolves it (aws sts get-caller-identity works) but the DuckDB 2.0.0 aws extension does not. With the same credentials exported to the environment (eval of 'aws configure export-credentials --profile accu-tracker --format env', AWS_PROFILE unset) both tests pass, so the bucket policy and the tests' assertions are sound. Two defects follow. (1) README.md lines 326 to 330 say the credential_chain secret uses the standard AWS chain including a shared profile and SSO, and give no route for a login-session profile, so the documented reader query fails for that reader with an opaque error. (2) _aws_credentials_discoverable in tests/test_live_private_outputs.py treats AWS_PROFILE as proof of usable credentials, so the tests fail inside DuckDB with no hint of the cause. Out of scope when found: it was seen during merge verification, not inside a claimed story. No file under src changes. Do not print or commit any credential.

## Acceptance Criteria

- [ ] The README reader section states that a profile created by aws login is not read by the DuckDB credential chain and gives the export-credentials command that makes the documented query work
- [ ] When DuckDB cannot build the secret from the discoverable credentials the two live tests fail or skip with a message that names the credential source and the export-credentials route and never print a credential
- [ ] With credentials exported to the environment both tests in tests/test_live_private_outputs.py pass under -m live
- [ ] ruff check and ruff format --check and mypy and pytest all exit 0

## Implementation Plan

## Verified against the worktree (`.worktrees/st-b49e`, HEAD 033fdba)

- `README.md` "Querying with DuckDB" (lines ~326 to 330) has the prose paragraph about `credential_chain` ("environment variables, a shared profile, SSO, or an assumed role") followed by two ```sql blocks. `tests/test_readme.py::test_readme_s3_query_uses_credential_chain` takes `blocks[1]` as the S3 query, so the new text MUST NOT add another ```sql block before it; use a ```sh fence. The same test forbids `key_id`, `secret_key`, `session_token`, `provider config` inside that sql block only. `test_readme_describes_a_private_bucket` forbids the substrings `cors`, `public-read`, `public bucket`, `public s3`, `intentionally public`, `public_outputs` anywhere in README.
- `tests/test_live_private_outputs.py` has module-level `pytestmark = pytest.mark.live`, so nothing defined as a test there runs in the default suite. `_aws_credentials_discoverable()` returns True on any of AWS_ACCESS_KEY_ID, AWS_PROFILE, AWS_WEB_IDENTITY_TOKEN_FILE or `~/.aws/credentials`. Two call sites run `CREATE OR REPLACE SECRET ... PROVIDER credential_chain`: `_existing_key` (used by `test_anonymous_reader_is_denied`, before it deletes env vars) and `test_credentialed_reader_globs_observations`. Both currently surface an opaque `duckdb.Error`.
- `pyproject.toml` has `addopts = "-q -m 'not live'"`; mypy checks only `src scripts`; ruff checks `src tests scripts`. No file under `src` changes.
- No existing README or test mentions export-credentials. `LEARNINGS.md` line ~558 already records the finding; no edit needed there.

## Design

Put the secret creation and its diagnostics in a small helper module `tests/aws_support.py` (importable as `tests.aws_support`, same pattern as `tests.conftest`) so it can be unit-tested in the default suite with a fake connection (the live test module cannot host default-suite tests because of its module-level live marker).

`tests/aws_support.py`:
- `credential_source() -> str | None`: names the first discoverable source, in this order: `AWS_ACCESS_KEY_ID` (environment keys), `AWS_PROFILE=<name>` (shared profile; the profile name is not a credential), `AWS_WEB_IDENTITY_TOKEN_FILE`, `~/.aws/credentials`; None if none. Same marker set and same truth value as today's `_aws_credentials_discoverable`.
- `EXPORT_COMMAND`: the string `eval "$(aws configure export-credentials --profile <profile> --format env)" && unset AWS_PROFILE`.
- `create_credential_chain_secret(con, name, region) -> None`: runs `CREATE OR REPLACE SECRET <name> (TYPE s3, PROVIDER credential_chain, REGION '<region>')`. On `duckdb.Error` calls `pytest.fail(message, pytrace=False)` where the message names the credential source from `credential_source()`, states that DuckDB could not build the secret from it (an `aws login` profile is not read by the DuckDB credential chain), gives the export-credentials route including `unset AWS_PROFILE`, and appends the DuckDB error text after scrubbing: any non-empty value of AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN in the environment is replaced with `<redacted>` in the text. It never prints a credential value.

Chosen outcome is fail (not skip): credentials were discoverable but unusable is an environment fault the reader must see. The existing skip for "no credentials discoverable" is unchanged.

`tests/test_live_private_outputs.py`: replace `_aws_credentials_discoverable` body with `return credential_source() is not None` (keep the name so call sites and the skip message stay), and replace both inline `CREATE OR REPLACE SECRET ... credential_chain` executes with `create_credential_chain_secret(con, "key_probe", region)` and `create_credential_chain_secret(con, "outputs_s3", region)`. Leave the anonymous `PROVIDER config` secret as is.

README: in "Querying with DuckDB" after the sentence about the credential chain, narrow the claim and add the login-session route (prose plus a ```sh block, no new sql block placed before the S3 sql block).

## Steps (TDD)

1. Write `tests/test_aws_support.py` (default suite, not live) first and watch it fail on import:
   - `test_credential_source_names_env_keys_profile_and_none`: monkeypatch env and `Path.home` (tmp_path) so each marker alone yields the right label, and with none set returns None; precedence env keys over profile.
   - `test_secret_failure_names_source_and_export_route`: a fake con whose `execute` raises `duckdb.Error("Secret Validation Failure ... Profile: p")`, env `AWS_PROFILE=p`; `pytest.raises(pytest.fail.Exception)`; assert message contains `AWS_PROFILE=p`, `aws configure export-credentials`, `--format env`, `unset AWS_PROFILE`.
   - `test_secret_failure_never_prints_credentials`: set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN to distinctive sentinels and make the fake error text embed them; assert none of the sentinels appear in the failure message and `<redacted>` does.
   - `test_secret_success_issues_credential_chain_statement`: fake con records the SQL; assert it contains `TYPE s3`, `PROVIDER credential_chain`, `REGION 'ap-southeast-2'` and the secret name, and no failure raised.
2. Implement `tests/aws_support.py` to make them pass.
3. Edit `tests/test_live_private_outputs.py` as above (imports `from tests.aws_support import create_credential_chain_secret, credential_source`).
4. Add a README assertion first (red), then edit `README.md`: extend `tests/test_readme.py` with `test_readme_documents_aws_login_profile_route`: the "Querying with DuckDB" section contains `aws login`, `aws configure export-credentials`, `--format env`, and `unset AWS_PROFILE`; and the section's first sql block count and `blocks[1]` S3 block remain unchanged (existing test covers). Then edit the README prose: replace "environment variables, a shared profile, SSO, or an assumed role" with a statement that the chain reads environment variables, a shared profile with keys, SSO or an assumed role, and that a profile created by `aws login` (login_session in `~/.aws/config`, key type `login` in `aws configure list`) is not read by the DuckDB credential chain even though the AWS CLI resolves it; then add a ```sh block:
   ```sh
   eval "$(aws configure export-credentials --profile <profile> --format env)"
   unset AWS_PROFILE
   ```
   followed by one sentence that the exported variables are short-lived, hold secrets, and must not be printed or committed; run the sql after this in the same shell. Place this before the existing S3 ```sql block.
5. Verification, one per line, each must exit 0:
   `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts` (run `uv run ruff format tests` if needed), `uv run mypy src scripts`, `uv run pytest -q`.
6. Live check (acceptance criterion 3), without printing credentials: in a subshell `eval "$(aws configure export-credentials --profile accu-tracker --format env)"; unset AWS_PROFILE; uv run pytest -m live tests/test_live_private_outputs.py` and confirm both pass; then with only `AWS_PROFILE=accu-tracker` set confirm both fail with the new message naming `AWS_PROFILE=accu-tracker` and the export route and containing no key material. If the implementer has no AWS profile available, report that this step was not run rather than claiming it.
7. Commit on the story branch with the standard trailer. Do not touch `src`, `LEARNINGS.md` or the story file.

## Implementation Notes

## Questions
