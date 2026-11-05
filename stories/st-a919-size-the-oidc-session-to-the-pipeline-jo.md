---
id: st-a919
title: Size the OIDC session to the pipeline job
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [.github/workflows/pipeline.yml, infra/README.md, infra/main.tf, tests/test_infra.py, tests/test_workflows.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

aws_iam_role.pipeline (infra/main.tf:106) sets no max_session_duration and pipeline.yml sets no role-duration-seconds, so credentials last the 3600 s default against a 120 minute job and are never refreshed. A run reaching S3 past 60 minutes writes no ledger and repeats. This changes infra, so land it before the first apply or apply again afterwards. Verdict PLAUSIBLE: the AWS defaults and expiry behaviour were not exercised against AWS. Evidence: docs/research/2026-11-04-milestone-2-review.md finding 3.

## Acceptance Criteria

- [ ] aws_iam_role.pipeline sets max_session_duration to at least the pipeline job timeout
- [ ] pipeline.yml sets role-duration-seconds equal to the role maximum
- [ ] tests/test_infra.py and tests/test_workflows.py assert both values

## Implementation Plan

Verified in worktree /Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-a919 (HEAD 73f4de0): the story pointers are accurate. infra/main.tf:106 `resource "aws_iam_role" "pipeline"` has only `name` and `assume_role_policy`. .github/workflows/pipeline.yml has `timeout-minutes: 120` (7200 s) at job level and the `aws-actions/configure-aws-credentials` step (with `role-to-assume`, `aws-region`) has no `role-duration-seconds`. verify.yml has its own credentials step in a 60 minute job; it is out of scope (the story names pipeline.yml only, and it assumes the same role, which is unaffected by a higher role maximum). The IAM role maximum may be 3600..43200 s.

Design choice: role max_session_duration = 10800 (3 h) and role-duration-seconds = 10800. 7200 would equal the job timeout but credentials are minted after checkout, uv install and `uv sync`, so they would expire before a job that runs the full 120 minutes ends. 10800 covers the 120 minute job plus setup with margin, is within the IAM limit of 43200, and equals the role maximum as the acceptance criteria require.

Steps (TDD, tests first):
1. tests/test_infra.py: add `test_pipeline_role_max_session_duration_covers_the_job_timeout`. Take `_block(_read("main.tf"), 'resource "aws_iam_role" "pipeline"')`, regex `max_session_duration\s*=\s*(\d+)`, assert present, int value between 3600 and 43200, and >= 120*60 (the pipeline job timeout; read it from pipeline.yml via yaml or hard-code 7200 with a comment naming the workflow). Proves the role can issue credentials that last as long as the job. Run it and see it fail (no attribute).
2. tests/test_workflows.py: add `test_aws_credentials_step_requests_the_role_maximum_duration`. Load the single configure-aws-credentials step in pipeline.yml, read `with["role-duration-seconds"]` (accept int or numeric string, convert with int), assert it is >= `_job(doc)["timeout-minutes"] * 60`, and assert it equals the `max_session_duration` parsed from infra/main.tf's aws_iam_role.pipeline block (regex on `(REPO / "infra" / "main.tf").read_text()`). Proves the workflow requests the full role maximum and the two files cannot drift. Run and see it fail.
3. infra/main.tf: add `max_session_duration = 10800` to aws_iam_role.pipeline, with a comment: the pipeline job runs up to 120 minutes (timeout-minutes in pipeline.yml), the default 3600 s expires mid-run, and pipeline.yml role-duration-seconds must equal this value.
4. .github/workflows/pipeline.yml: add `role-duration-seconds: 10800` under `with:` of the credentials step, with a comment that it must equal max_session_duration in infra/main.tf. Update the header comment lightly if useful.
5. infra/README.md: in the "What the module creates" role bullet, add that the role's maximum session duration is 3 hours (10800 s) and the workflow requests all of it. In the notes section, add: the change takes effect only after `tofu apply`/`terraform apply`; if infra was already applied, apply again before the next run, otherwise AssumeRoleWithWebIdentity with a duration above the role maximum (3600 default) fails.
6. Run verification in order, one per line: `uv run ruff check src tests scripts`; `uv run ruff format --check src tests scripts`; `uv run mypy src scripts`; `uv run pytest -q`. Commit on the story branch.

## Implementation Notes

- 2026-11-05T11:08:23.606Z: Gates on the story branch at c18e13f: ruff check, ruff format --check and mypy pass; terraform fmt -check on infra passes; pytest exits 0 in default mode and with GITHUB_ACTIONS=true. max_session_duration and role-duration-seconds are both 10800 s, and a test parses both files so they cannot drift. The values were not exercised against AWS. verify.yml assumes the same role with its default 3600 s in a 60 minute job and was left alone.

## Questions
