---
id: st-bbbf
title: Make the output bucket private until Jarrod's review
type: task
priority: P2
depends_on: []
discovered_from: st-58e9
touches: [.github/workflows/verify.yml, README.md, docs/decisions/0011-private-output-bucket.md, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, src/wetland_change/ledger.py, tests/test_infra.py, tests/test_live_private_outputs.py, tests/test_live_public_read.py, tests/test_readme.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

On 2026-11-06 Jarrod directed that everything stays private until he has reviewed it; he will consider public access later. The infra module in infra/main.tf still makes the output bucket public-read: anonymous s3:GetObject on every object, anonymous s3:ListBucket under observations/ (added by st-58e9), CORS GET and HEAD from any origin for stac-browser on GitHub Pages, and a public access block with block_public_policy and restrict_public_buckets set to false. Nothing has been applied, so no bucket exists yet; this is a code and documentation change only. Make the module create a private bucket. The pipeline role (OIDC trust on main, ListBucket plus Get, Put and Delete on objects) stays unchanged. Readers use AWS credentials: DuckDB through a credential_chain secret, the catalogue through signed or local access. Record the decision in a new ADR that names what it supersedes (the design's public-read bucket and stac-browser on GitHub Pages, and st-58e9's anonymous listing) and what reopening public access would take. Offline only: terraform or tofu fmt and validate are allowed; never run plan or apply, never call AWS. The repository itself was made private on 2026-11-06 and is out of scope here. src/wetland_change/raster/env.py refers to anonymous reads of third-party Earth Search COGs and is out of scope.

## Acceptance Criteria

- [ ] infra/main.tf sets all four aws_s3_bucket_public_access_block settings (block_public_acls
- [ ] ignore_public_acls
- [ ] block_public_policy
- [ ] restrict_public_buckets) to true
- [ ] infra/main.tf grants no principal '*' or anonymous access: the public_read policy document and aws_s3_bucket_policy are removed
- [ ] and no statement allows anonymous s3:GetObject or s3:ListBucket
- [ ] infra/main.tf has no aws_s3_bucket_cors_configuration resource
- [ ] The pipeline role trust policy
- [ ] its permissions
- [ ] the lifecycle rule and the outputs role_arn and bucket_url are unchanged
- [ ] tests/test_infra.py asserts the private configuration and fails if any public grant
- [ ] public-policy allowance or CORS rule is reintroduced
- [ ] tests/test_live_public_read.py is replaced by a live test (marked live
- [ ] not run here) that checks an anonymous reader is denied and a credentialed DuckDB reader can glob observations/
- [ ] README.md and infra/README.md describe a private bucket only: the DuckDB example uses a credential_chain secret
- [ ] nothing says the bucket or catalogue is public
- [ ] and infra/variables.tf no longer describes the bucket as public-read; tests/test_readme.py checks the new example
- [ ] A new ADR docs/decisions/0011-*.md records Jarrod's 2026-11-06 direction
- [ ] what it supersedes
- [ ] the effect on design success criteria 2 and 3 (they now apply to credentialed readers)
- [ ] and the steps to reopen public access later
- [ ] terraform (or tofu) -chdir=infra fmt -check and validate pass offline
- [ ] and the five project gates pass

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-bbbf, HEAD 0e9045a)

Every pointer in the story matches reality. Nothing is unimplementable. terraform v1.15.8 is at /opt/homebrew/bin/terraform (no tofu). Latest ADR is 0010, so the new one is `docs/decisions/0011-*.md`. Existing files that carry public wording:

- `infra/main.tf`: public access block (block_public_policy and restrict_public_buckets false), `data "aws_iam_policy_document" "public_read"`, `aws_s3_bucket_policy.public_read`, `aws_s3_bucket_cors_configuration.outputs`.
- `infra/variables.tf` line 2 ("public-read S3 bucket"); `infra/outputs.tf` bucket_url description ("public bucket").
- `infra/README.md` lines 7 and 115; `README.md` lines 187, 314-326, 335, 373-376, 409-414.
- `tests/test_infra.py` (`test_public_read_policy_is_getobject_plus_observations_list`, `test_cors_allows_only_get_and_head_from_any_origin`); `tests/test_readme.py` (`_public_list_prefixes`, `test_readme_anonymous_s3_query_matches_public_list_policy`); `tests/test_live_public_read.py`.
- Comment-only wording ("public, unversioned bucket"): `.github/workflows/verify.yml` line 22, `src/wetland_change/ledger.py` line 16. `src/wetland_change/raster/env.py` is out of scope and untouched. The design doc is historical and is superseded by the ADR, not edited.

## Steps

Batch 1 has four tasks that touch disjoint files, so they run in parallel. Batch 2 is the final gate.

1. **T1 infra and test_infra.** Edit `infra/main.tf`, `infra/variables.tf`, `infra/outputs.tf`, `infra/README.md` and `tests/test_infra.py`. Set all four public access block settings true. Delete the public_read policy document, the bucket policy and the CORS resource. Leave the pipeline role, trust, permissions, lifecycle, ownership controls and the output names and values untouched. The tests prove four things.
   - All four block settings are true.
   - The only policy documents are `pipeline_trust` and `pipeline_access`.
   - No bucket policy, ACL, `"*"` principal or CORS resource exists.
   - `infra/README.md` and the variable and output descriptions describe a private bucket.
   Existing pipeline trust and access tests stay as the proof that the role is unchanged.
2. **T2 live test.** `git mv tests/test_live_public_read.py tests/test_live_private_outputs.py` and rewrite it (marked live). It proves that an anonymous HTTPS GET and an anonymous DuckDB glob are denied, and that a credentialed DuckDB reader (credential_chain secret) can glob `observations/`.
3. **T3 README and test_readme.** Rewrite the README sections for a private bucket with a `credential_chain` DuckDB example. In `tests/test_readme.py`, replace the public-list-prefix helper and anonymous test with a credential_chain test, and add a no-public-wording test. The existing local-query test stays untouched.
4. **T4 ADR 0011.** Add `docs/decisions/0011-private-output-bucket.md` and nudge the two comment lines that say "public" (verify.yml, ledger.py).
5. **T5 final gates (batch 2).** Run `terraform -chdir=infra fmt -check -recursive`, `terraform -chdir=infra init -backend=false` and `terraform -chdir=infra validate`. Then run the four project gates (ruff check, ruff format --check, mypy, pytest). Never run plan or apply, and never call AWS.
## Orchestrator amendments (override anything above that conflicts)

1. Agents commit nothing. The orchestrator commits after the run. Uncommitted work is expected and is not a defect; reviewers must not report it. Put notes and results in the summary. Never edit `stories/**` or `.agents/**`.
2. No AWS calls of any kind, no terraform or tofu plan or apply, no S3 compaction, no `-m live` test runs. `terraform -chdir=infra fmt`, `init -backend=false` (registry download only) and `validate` are allowed. `infra/.terraform.lock.hcl` is tracked: it must not change; if init changes it, restore it with `git checkout -- infra/.terraform.lock.hcl` and report that. Nothing is written under `/Users/jarrodbaker/Documents/swan-wetland-change-data` or in the main checkout `/Users/jarrodbaker/Documents/swan-wetland-change`; work only in the worktree.
3. Gates, one command per line, judged by exit code: `uv run ruff check src tests scripts`; `uv run ruff format --check src tests scripts`; `uv run mypy src scripts`; `uv run pytest -q`; `GITHUB_ACTIONS=true uv run pytest -q`. Never clear or override pytest addopts.
4. Story-specific:
   - ADR 0011 also records, as context, that the GitHub repository was made private on the same day under the same direction, and that design spike 6 (a hand-written catalogue on a public bucket with CORS, opened in stac-browser) no longer applies while the bucket is private; spike 7 (DuckDB reads observations from S3 with one glob) now means a credentialed reader. ADR 0011 status line: "accepted, 2026-11-06, on Jarrod's direction; reversible by a superseding ADR".
   - Do not edit the design doc `docs/plans/2026-10-29-swan-wetland-change-design.md` or earlier ADRs; ADR 0011 supersedes the relevant parts.
   - `src/wetland_change/raster/env.py` stays untouched.
5. Docs are flat factual prose with no em dashes.

## Implementation Notes

- 2026-11-06T09:20:31.586Z: Acceptance criteria as written (the CLI split them at commas):
1. infra/main.tf sets all four aws_s3_bucket_public_access_block settings (block_public_acls, ignore_public_acls, block_public_policy, restrict_public_buckets) to true.
2. infra/main.tf grants no principal '*' or anonymous access: the public_read policy document and aws_s3_bucket_policy are removed, and no statement allows anonymous s3:GetObject or s3:ListBucket.
3. infra/main.tf has no aws_s3_bucket_cors_configuration resource.
4. The pipeline role trust policy, its permissions, the lifecycle rule and the outputs role_arn and bucket_url are unchanged.
5. tests/test_infra.py asserts the private configuration and fails if any public grant, public-policy allowance or CORS rule is reintroduced.
6. tests/test_live_public_read.py is replaced by a live test (marked live, not run here) that checks an anonymous reader is denied and a credentialed DuckDB reader can glob observations/.
7. README.md and infra/README.md describe a private bucket only: the DuckDB example uses a credential_chain secret, nothing says the bucket or catalogue is public, and infra/variables.tf no longer describes the bucket as public-read; tests/test_readme.py checks the new example.
8. A new ADR docs/decisions/0011-*.md records Jarrod's 2026-11-06 direction, what it supersedes, the effect on design success criteria 2 and 3 (they now apply to credentialed readers), and the steps to reopen public access later.
9. terraform (or tofu) -chdir=infra fmt -check and validate pass offline, and the five project gates pass.
- 2026-11-06T09:46:15.167Z: Committed 09f94a9 on story/st-bbbf. Gates green in the worktree: ruff check, ruff format, mypy, pytest (default and GITHUB_ACTIONS=true), 970 passed, 10 deselected. terraform fmt, init -backend=false and validate pass; .terraform.lock.hcl unchanged. No terraform plan or apply and no AWS calls were made. ADR 0011 added. Push not yet approved by Jarrod.

## Questions
