# Infrastructure

OpenTofu/Terraform module for the AWS resources the swan-wetland-change pipeline needs. The pipeline runs scheduled NDWI/NDVI change detection for Swan Coastal Plain Ramsar wetlands and publishes outputs and a STAC catalogue to S3.

## What the module creates

- An S3 bucket for the outputs and the STAC catalogue, with public read decided in `docs/decisions/0016-public-read-output-bucket.md` (which supersedes ADR 0011). `block_public_acls` and `ignore_public_acls` stay on, so no object or bucket ACL can make anything public. `block_public_policy` and `restrict_public_buckets` are off, so the bucket policy `public_read` can grant anonymous callers `s3:GetObject` on every object and `s3:ListBucket` only for prefixes under `observations/` (an `s3:prefix` StringLike `observations/*` condition), so a DuckDB glob over the observation files works without credentials. The bucket root and the other prefixes (`changes/`, `ledger/`, `runs/`, `stac/`, `verification/`) cannot be listed anonymously, their objects stay readable by key, and there is no public put or delete. A CORS rule allows GET and HEAD from any origin, so a browser viewer such as stac-browser can read the catalogue. Public read took effect at the 2026-11-16 apply (see "Applying public read"); anonymous readers need no AWS credentials, and a reader that holds credentials can still use a DuckDB `credential_chain` secret (see README.md "Querying with DuckDB"). Anonymous requests are billed to the bucket owner. A lifecycle rule aborts incomplete multipart uploads one day after initiation, and the pipeline role needs no `s3:AbortMultipartUpload` because S3 applies the rule itself.
- The GitHub OIDC provider `token.actions.githubusercontent.com` with audience `sts.amazonaws.com`, when `create_oidc_provider` is true (the default). An AWS account can hold only one such provider, and other repositories usually share it. If the account already has one, pass `-var create_oidc_provider=false`, as the commands below do. The module then looks the provider up with a data source and leaves it unmanaged. Do not import an existing provider into this state: a later `destroy` would delete it and break GitHub-to-AWS authentication for every other repository in the account.
- An IAM role `swan-wetland-change-pipeline`, assumable only from the repository's `main` branch. The trust policy requires `token.actions.githubusercontent.com:aud` = `sts.amazonaws.com` and `token.actions.githubusercontent.com:sub` = `repo:<owner>@<owner_id>/<name>@<repo_id>:ref:refs/heads/main`. The role has `s3:ListBucket` on the bucket and `s3:GetObject`, `s3:PutObject` and `s3:DeleteObject` on its objects, and nothing else. The role's maximum session duration is 3 hours (10800 s), and the workflow requests all of it so credentials outlast the 120 minute job.

Required variables with no defaults: `bucket_name` (globally unique), `github_repository` (`<owner>@<owner_id>/<name>@<repo_id>`, see "Immutable subject" below) and `aws_region`. `create_oidc_provider` is optional and defaults to true. Outputs are `role_arn` and `bucket_url`.

## Immutable subject

This repository has GitHub's immutable subject enabled, so its OIDC `sub` claims use `repo:<owner>@<owner_id>/<name>@<repo_id>:...` rather than `repo:<owner>/<name>:...`. A trust condition built from a plain `owner/name` value never matches the token, and the role cannot be assumed.

Read the value with:

```sh
gh api repos/jazzdos/swan-wetland-change/actions/oidc/customization/sub
```

Take `sub_claim_prefix` from the response and drop the leading `repo:`. For this repository the `github_repository` value is `jazzdos@33918812/swan-wetland-change@1438569874`. The trust condition then resolves to `repo:jazzdos@33918812/swan-wetland-change@1438569874:ref:refs/heads/main`. The variable validation rejects the plain `owner/name` form.

## Prerequisites

- OpenTofu or Terraform >= 1.6.
- AWS credentials for a human identity that can create S3 buckets, IAM roles and OIDC providers. Do not use the pipeline role for this.
- The target AWS account selected in those credentials.

## Applying the module

The commands below use `terraform`. `tofu` works identically.

```sh
terraform -chdir=infra init
terraform -chdir=infra plan -var bucket_name=<bucket> -var github_repository=jazzdos@33918812/swan-wetland-change@1438569874 -var create_oidc_provider=false -var aws_region=<region>
terraform -chdir=infra apply -var bucket_name=<bucket> -var github_repository=jazzdos@33918812/swan-wetland-change@1438569874 -var create_oidc_provider=false -var aws_region=<region>
terraform -chdir=infra output -raw role_arn
terraform -chdir=infra output -raw bucket_url
```

Drop `-var create_oidc_provider=false` for an AWS account that has no GitHub OIDC provider yet, so the module creates it.

Review the plan output before applying. The story that created this module only validated it offline; nobody ran plan or apply there. The operator runs them.

## Applying public read

ADR 0016 changed the module of the existing deployment: the access block's two policy settings went from true to false, and the bucket policy and the CORS rule were added. The ADR decided that public read takes effect at the operator's apply, and requires that the apply is run by the operator, never by an agent, after the plan is reviewed. The apply of 2026-11-16 was run by the orchestrator on Jarrod's instruction 'just make it public', a deviation recorded in the ADR's Apply section, and public read took effect then. The steps below are the procedure for a repeat apply of this module, for example on a new deployment.

Preconditions, in order (ADR 0016, "Preconditions of the apply"):

1. st-22f1 is merged to `main`, so new files carry term T3 of `docs/research/2026-11-14-public-release-licences.md` (the DBCA-010 attribution and licence notice, and the STAC collection licence field).
2. st-22f1's backfill job has run against the output store, so files written before st-22f1 carry T3 too.
3. Recommended, and Jarrod's decision: DBCA's written confirmation of the licence for public redistribution (the note's "Residual risk").

Preconditions 1 and 2 were met before the 2026-11-16 apply (st-22f1 merged; its backfill run 43714356660 on 2026-11-15 rewrote 1946 of 1946 files with no failures). Jarrod waived precondition 3 on 2026-11-15; it is parked as story st-4c87.

Plan with the same variables as the deployment and review the output:

```sh
terraform -chdir=infra init
terraform -chdir=infra plan -var bucket_name=<bucket> -var github_repository=jazzdos@33918812/swan-wetland-change@1438569874 -var create_oidc_provider=false -var aws_region=<region>
```

The plan should update `aws_s3_bucket_public_access_block.outputs` in place (`block_public_policy` and `restrict_public_buckets` from true to false) and add `aws_s3_bucket_policy.public_read` and `aws_s3_bucket_cors_configuration.outputs`. Do not apply if it destroys or replaces any resource, or changes the role, its policy or the OIDC provider. Otherwise apply with the same variables:

```sh
terraform -chdir=infra apply -var bucket_name=<bucket> -var github_repository=jazzdos@33918812/swan-wetland-change@1438569874 -var create_oidc_provider=false -var aws_region=<region>
```

Then check with headers only. curl sends the request unsigned, so it is an anonymous request whatever AWS credentials the shell holds:

```sh
curl -sS -I -H "Origin: https://example.org" "$(terraform -chdir=infra output -raw bucket_url)/stac/catalog.json" | grep -i -E '^(HTTP/|access-control-allow-origin:)'
```

The check prints a 200 status line (`HTTP/1.1 200 OK`) and `Access-Control-Allow-Origin: *`. On the 2026-11-16 apply it printed exactly that. Before an apply of public read it prints a 403 status line and no `Access-Control-Allow-Origin` line. The check reads response headers only, not the object. Also on 2026-11-16, an anonymous ListObjectsV2 returned status 200 for `observations/` and 403 for the bucket root and for `ledger/`.

The xfail marker was removed from `tests/test_live_anonymous_read.py` in the commit that recorded the 2026-11-16 apply (st-3d77), so the weekly `verify.yml` run checks anonymous read. For a repeat apply on a new deployment, remove the marker in the commit that records it.

## Offline checks

These need no AWS credentials and are safe for CI and contributors:

```sh
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
terraform -chdir=infra fmt -check -recursive
```

## Repository variables

The workflows read three GitHub repository variables. They are variables, not secrets: no long-lived AWS keys exist, because the pipeline authenticates through OIDC.

| Variable | Value | Source |
| --- | --- | --- |
| `AWS_ROLE_ARN` | Role ARN | Output `role_arn` |
| `OUTPUT_BUCKET` | Bare bucket name, no `s3://` prefix | The `bucket_name` value |
| `AWS_REGION` | Region code | The `aws_region` value |

Workflows build paths as `s3://${{ vars.OUTPUT_BUCKET }}/...`, so `OUTPUT_BUCKET` must not include the scheme.

```sh
gh variable set AWS_ROLE_ARN --body "$(terraform -chdir=infra output -raw role_arn)"
gh variable set OUTPUT_BUCKET --body "<bucket>"
gh variable set AWS_REGION --body "<region>"
```

## Set the catalogue base URL

`catalogue.base_url` in `config/pipeline.toml` ships as a placeholder on the `.invalid` host. Every link and asset href in the published catalogue starts with it, so it must be the real bucket URL before anything is published.

After `apply`, read the value:

```sh
terraform -chdir=infra output -raw bucket_url
```

Set `base_url` under `[catalogue]` in `config/pipeline.toml` to exactly that value, with no trailing slash, and commit it to `main` before the first scheduled run or any seeding command. `wetland-change run`, `backfill`, `score` and `build-catalogue` refuse an `s3://` output root while the placeholder `.invalid` host remains.

## Seeding the output root before the first scheduled run

Do the base URL step above first: seeding commands refuse an `s3://` output root until `catalogue.base_url` is set.

With an empty output root the daily run has no watermark, so its search is bounded only by `stac.initial_lookback_days` in `config/pipeline.toml` (default 30 days of `created`). The scheduled job is cancelled at 120 minutes. Seed the root from the backfill so the first scheduled run does not start from nothing.

Run these once, as an operator whose AWS identity can write the bucket (not through the pipeline role). Replace `<today>` with the current UTC date and `<bucket>` with the bucket name.

```sh
uv run python scripts/fetch_aoi.py
uv run wetland-change backfill --start 2022-12-01 --end <today> --output-root s3://<bucket>/
uv run wetland-change score --start 2022-12-01 --end <today> --output-root s3://<bucket>/
uv run wetland-change build-catalogue --output-root s3://<bucket>/
```

The backfill is resumable because it checkpoints per scene. Rerun the same command if it is interrupted.

Choose `--end` no earlier than today minus `initial_lookback_days`. Otherwise scenes acquired after the backfill end but created before the lookback start are never seen by either command.

Backfill rows are tagged `backfill`, so the daily watermark stays empty after seeding. The first scheduled run therefore applies the lookback window and skips every item already in the ledger. From the second run on it uses the watermark.

A cancelled or timed-out daily run keeps the scenes it finished, because the ledger is written after each scene. Rerun the workflow (`workflow_dispatch`) to continue. The next run does not score the observation files of the finished scenes, so run `wetland-change score --start <date> --end <date> --output-root s3://<bucket>/` over their acquisition dates.

A bucket that is not seeded still converges: each run does at most what fits in 120 minutes and the next run resumes. The first runs are bounded by the lookback window, and older history needs `backfill`.

## Notes

- State is local by default. `terraform.tfstate` is gitignored; keep it safe or add a remote backend.
- Anonymous access is limited to `s3:GetObject` on objects and `s3:ListBucket` under `observations/`, with CORS for GET and HEAD, and it has been in effect since the 2026-11-16 apply. Never add a public put or delete, an unconditioned list or a wider list prefix without a new decision record that supersedes ADR 0016. Never write private data to the bucket: every object is readable by key.
- The role only works from runs on `main`. A `workflow_dispatch` run from another branch cannot assume it.
- The 3 hour session duration takes effect only after an apply. An existing deployment must be applied again before the next pipeline run, because requesting a duration above the role maximum makes the role assumption fail.
