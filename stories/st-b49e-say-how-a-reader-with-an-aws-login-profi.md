---
id: st-b49e
title: "Say how a reader with an aws login profile gives DuckDB credentials, and make the live test report it"
type: bug
priority: P3
depends_on: []
discovered_from: st-bbbf
touches: [README.md, tests/test_live_private_outputs.py]
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

## Implementation Notes

## Questions
