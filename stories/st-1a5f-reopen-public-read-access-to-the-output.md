---
id: st-1a5f
title: Reopen public read access to the output bucket in code under ADR 0016
type: feature
priority: P2
complexity: hard
depends_on: [st-1a9c]
touches: [README.md, docs/decisions/0011-private-output-bucket.md, docs/decisions/0016-public-read-output-bucket.md, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, tests/aws_support.py, tests/test_aws_support.py, tests/test_infra.py, tests/test_live_anonymous_read.py, tests/test_live_credentialed_read.py, tests/test_live_private_outputs.py, tests/test_public_read_decision.py, tests/test_readme.py]
exclusive: false
gates: [test]
created: 2026-11-14
updated: 2026-11-15
---
## Description

Jarrod approved public access to the output bucket on 2026-11-14. This story carries out steps 1, 3, 4 and 5 of "Reopening public access" in `docs/decisions/0011-private-output-bucket.md`, with no apply. Step 2 (licences and attribution) is the story this one depends on; its research note `docs/research/<date>-public-release-licences.md` is the evidence the new ADR cites. Step 6 (the apply) is Jarrod's: ADR 0011 says the apply is run by the operator, never by an agent, after the plan is reviewed.

How the approval was given, for the ADR's decision-making section: on 2026-11-14 the orchestrator told Jarrod that the outputs review was the decision that unblocked spike 6 and the anonymous read test, and Jarrod replied "approved". The orchestrator then stated its reading with the proposed stories (he has reviewed the outputs and approves public access, the new ADR records that as his decision, the apply and the DBCA-010 licence confirmation stay his) and Jarrod approved that set.

What to change:

- ADR. Write `docs/decisions/0016-<slug>.md` superseding 0011. Numbers 0014 and 0015 are reserved by st-b6bf and st-dd0d. Change only the status line of 0011, to name 0016.
- Infra (`infra/main.tf`, `infra/variables.tf`, `infra/outputs.tf`). Set `block_public_policy` and `restrict_public_buckets` to false and keep `block_public_acls` and `ignore_public_acls` true. Add a bucket policy granting anonymous `s3:GetObject` on objects and anonymous `s3:ListBucket` with an `s3:prefix` condition limited to `observations/`, with `depends_on` the access block. Add a CORS rule for GET and HEAD. The pipeline role, the lifecycle rule and the outputs stay as they are. The pre-0011 public configuration is in the git history of st-bbbf (story commit 09f94a9) and of st-58e9.
- Tests. Replace the private-configuration assertions in `tests/test_infra.py` and the `credential_chain` README test in `tests/test_readme.py`. Put an anonymous live test in place of `tests/test_live_private_outputs.py` (anonymous GET of an existing object, anonymous listing under `observations/`, anonymous DuckDB read with one glob, bucket-root listing denied). `tests/aws_support.py` (st-b49e) is the credential helper the private test uses.
- Docs. `README.md` ("Querying with DuckDB", Limitations and the status paragraph), `infra/README.md` and the `infra/variables.tf` description. Four test modules read `README.md`.

Constraints:

- No agent runs `tofu plan`, `tofu apply` or any AWS call. `infra/terraform.tfstate` is not read or changed.
- The new live test is written and collected but not run: it reads observations, which the st-b6bf pre-registration in `LEARNINGS.md` bars until its decision files are committed. No output-store object is read by this story.
- The README must not say the bucket is public before the apply. The wording is that public read takes effect at the operator's apply, and that until then readers need credentials.
- No `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md` is opened, no `git diff`, `git log -p`, `git show` or search output that includes another one is read, and no run log newer than 43475454140 is opened.
- `LEARNINGS.md` is not edited; tests pin the st-b6bf and st-dd0d pre-registrations.
- The GitHub repository's visibility is outside this story.
- Build agents do not commit or push; the orchestrator commits on the story branch.

## Acceptance Criteria

- [ ] `docs/decisions/0016-*.md` exists, names 0011 as superseded, records Jarrod's approval of 2026-11-14 as described above and the result of the licence story with a link to its note, and keeps the operator-only apply and the cost note (anonymous requests are billed to the bucket owner); the status line of `docs/decisions/0011-private-output-bucket.md` names 0016 and no other line of 0011 changes
- [ ] `tests/test_infra.py` asserts `block_public_acls` and `ignore_public_acls` are true and `block_public_policy` and `restrict_public_buckets` are false
- [ ] `tests/test_infra.py` asserts anonymous `s3:GetObject` on objects, anonymous `s3:ListBucket` only with an `s3:prefix` condition limited to `observations/`, `depends_on` the access block, and a CORS rule for GET and HEAD, and fails if the list statement loses its prefix condition
- [ ] `uv run pytest --collect-only -m live -q` lists an anonymous read test and `tests/test_live_private_outputs.py` no longer exists
- [ ] `README.md`, `infra/README.md` and the `infra/variables.tf` description describe public read as taking effect at the operator's apply; `infra/README.md` gives the plan-review and apply steps and a header-only check (status line and `Access-Control-Allow-Origin` of an anonymous HEAD with an Origin header) for the operator to run afterwards
- [ ] `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts` and `uv run pytest -q` all exit 0

## Implementation Plan

# st-1a5f plan: public read on the output bucket (ADR 0016), no apply

Worktree: `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-1a5f` (branch story/st-1a5f at 743793c). Baseline checked in the worktree: ruff, ruff format, mypy and `pytest -q` all pass. `pytest --collect-only -m live -q` lists `tests/test_live_private_outputs.py: 2`.

## What I checked against the story

- `infra/main.tf` is private: all four access-block settings are true, there is no bucket policy and no CORS rule. The pipeline role, the lifecycle rule and the outputs `role_arn` and `bucket_url` match the story. The pre-0011 public HCL is at `09f94a9^:infra/main.tf` (data `public_read` with `PublicReadObjects` and `PublicListObservationPrefix` (StringLike `s3:prefix` `observations/*`), `aws_s3_bucket_policy.public_read` with `depends_on`, and CORS GET/HEAD from `*`). The pre-0011 live test is at `09f94a9^:tests/test_live_public_read.py`.
- The bucket exists. It was applied on 2026-11-06 (`docs/handoffs/2026-11-06-milestone-2.md`). `config/pipeline.toml` `catalogue.base_url` is the real bucket URL, so a live test does not skip on the `.invalid` placeholder.
- `.github/workflows/verify.yml` runs `pytest -m live -rs` every Sunday from GitHub main, with no AWS credentials at that step. An anonymous-read test that asserts success would therefore fail every weekly run between the push and the operator's apply. To prevent that, the anonymous test is marked `xfail(strict=True, raises=AssertionError)`. The project already uses this convention for deliberately red tests (AGENTS.md, and `xfail_strict = true` in pyproject). After the apply the test XPASSes and fails strictly, which forces the commit that records the apply to remove the marker. ADR 0016 and `infra/README.md` both record this.
- The four modules that read a README are `tests/test_readme.py`, `tests/test_licence.py` ("Data sources and licences", untouched), `tests/test_verify_matrix.py` (matrix rows, untouched) and `tests/test_infra.py`, which reads `infra/README.md`.
- `tests/aws_support.py` (st-b49e) gives `credential_source` and `create_credential_chain_secret`. The private test's credentialed glob test is kept and moved, because readers need credentials until the apply. This keeps the helper in use.
- "The status paragraph" in README is read as the opening paragraph of `## Deployment`, which says the bucket is private until the owner's review (ADR 0011). Three other places say the bucket is private and stay unchanged on purpose: the STAC row of the README verification matrix, the `config/pipeline.toml` `[catalogue]` comment and the `verify.yml` header comment. Each is true until the apply and sits outside the listed files. ADR 0016 assigns them to the commit that records the apply.
- The licence note `docs/research/2026-11-14-public-release-licences.md` lists T3 (st-22f1) and the objects already in the store as blocking 0011 step 3. This story writes step 3's configuration and applies nothing, so ADR 0016 turns those items into preconditions of the apply. That follows the orchestrator inputs.

## Steps

1. **Infra and its tests** (`infra/main.tf`, `infra/variables.tf`, `infra/outputs.tf`, `infra/README.md`, `tests/test_infra.py`). Four tests are replaced: the all-true access block, the no-policy check, the no-CORS check and the private-text check.
   - `test_public_access_block_keeps_acl_blocks_on_and_policy_blocks_off` proves the exact four settings: ACL blocks true, policy blocks false.
   - `test_public_read_policy_is_getobject_plus_observations_list` proves two statements: anonymous `s3:GetObject` on `${arn}/*` with no condition, and anonymous `s3:ListBucket` on the bucket ARN with exactly one StringLike `s3:prefix` `["observations/*"]` condition. It also proves there is no put, delete or `s3:*`.
   - `test_public_read_check_fails_when_the_list_statement_loses_its_prefix_condition` is parametrised over four mutations of the real policy: condition removed, prefix widened to `*`, variable changed, and `StringNotLike`. It proves that the checker raises on each.
   - `test_policy_documents_and_principals_outside_public_read` proves there are exactly three policy documents, no ACLs, and that every other principal is Federated.
   - `test_bucket_policy_attaches_public_read_after_the_access_block` proves the bucket, the policy json and `depends_on`.
   - `test_cors_allows_only_get_and_head_from_any_origin` proves `allowed_methods == ["GET", "HEAD"]` and `allowed_origins == ["*"]`.
   - `test_bucket_descriptions_tie_public_read_to_the_operator_apply` proves that the `variables.tf` and `outputs.tf` descriptions say the change takes effect when the operator applies it.
   - `test_infra_readme_records_adr_0016_and_its_limits` and `test_infra_readme_gives_plan_review_apply_and_header_check` prove the ADR link, the operator-only apply and the cost note. They also prove the plan, review, apply and curl order in `## Applying public read`, with a `-I` and `Origin` header check that reads the status line and `Access-Control-Allow-Origin`.
   - The HCL is written in terraform-fmt layout by hand, because no tofu or terraform command may run.
2. **README** (`README.md`, `tests/test_readme.py`). The edits cover "Querying with DuckDB", the `## Deployment` status paragraph and Limitations only, with no DBCA-010 licence stated. The `credential_chain` test and the private-bucket test are replaced.
   - `test_readme_credentialed_s3_query_uses_credential_chain` checks the credentialed block, found by content.
   - `test_readme_anonymous_s3_query_names_only_the_region` checks a `PROVIDER config` block that holds no key material and globs `observations/`.
   - `test_readme_ties_anonymous_read_to_the_operator_apply` proves the anonymous block comes after the credentialed block, and that the prose, the Deployment paragraph and Limitations name the operator's apply and ADR 0016.
   - `test_readme_does_not_call_the_bucket_public_before_the_apply` checks a list of forbidden phrases.
   - The aws-login route tests stay.
3. **Live tests** (`tests/aws_support.py`, `tests/test_aws_support.py`, new `tests/test_live_anonymous_read.py`, new `tests/test_live_credentialed_read.py`, delete `tests/test_live_private_outputs.py`).
   - `bucket_from_base_url` and `configured_bucket` move into `tests/aws_support.py`, with offline unit tests that prove the parsing, the `.invalid` result of None, the ValueError and the skip.
   - The anonymous test, marked xfail strict, checks a GET of `stac/catalog.json` with an Origin header, expecting 200 and `Access-Control-Allow-Origin: *`. It checks that a listing under `observations/` returns 200 with a key, that the root, `ledger/` and `observations` (no slash) listings return 403, and that an anonymous DuckDB glob count is above 0 while a `ledger/` glob errors.
   - The credentialed test is moved unchanged.
   - Neither live test is run.
4. **ADR** (new `docs/decisions/0016-public-read-output-bucket.md`, the status line of `docs/decisions/0011-private-output-bucket.md`, new `tests/test_public_read_decision.py`).
   - The tests prove that 0016 supersedes 0011 and records the 2026-11-14 approval wording. They prove that it records the licence result (0 of 3, CC BY-NC 4.0 adopted reading, the 2026-11-15 reply, T1 to T4, st-22f1) with a relative markdown link that resolves to the note.
   - They prove that it keeps "run by the operator, never by an agent, after the plan is reviewed" with the preconditions in order (st-22f1 merged, then its backfill job, then the recommended DBCA confirmation, which is Jarrod's decision) and the cost note.
   - They prove that the 0011 status paragraph names 0016, and that the rest of 0011 is byte-identical to 743793c (sha256 a838a2dc...5f03, computed in the worktree).
5. **Gates and cross-check** (batch 2).
   - Run the four gates in AGENTS order.
   - `uv run pytest --collect-only -m live -q` lists `tests/test_live_anonymous_read.py: 1` and `tests/test_live_credentialed_read.py: 1`, and does not list `test_live_private_outputs`.
   - Every new path named in the docs exists.
   - The 0011 diff touches only lines 3 and 4.
   - No `.terraform` directory or state file appears in the worktree.

## Constraints that bind every task

- No AWS call. No tofu or terraform command of any kind, including fmt and validate. `infra/terraform.tfstate` is not read.
- No output-store read, and no live test run.
- Do not open any `docs/research/verification-*.md` other than `verification-20261029T131944Z.md` and `verification-20261111T175303Z.md`. Do not read `git diff`, `git log -p`, `git show` or search output that includes another one.
- Do not open any run log newer than 43475454140.
- Do not edit `LEARNINGS.md`, `AGENTS.md`, README "Data sources and licences" or README "Attribution backfill".
- Do not touch the repository's visibility.
- Do not commit or push.
