# Infrastructure

OpenTofu/Terraform module for the AWS resources the swan-wetland-change pipeline needs. The pipeline runs scheduled NDWI/NDVI change detection for Swan Coastal Plain Ramsar wetlands and publishes outputs and a STAC catalogue to S3.

## What the module creates

- A private S3 bucket for the outputs and the STAC catalogue, decided in `docs/decisions/0017-private-output-bucket-again.md` (ADR 0017), which supersedes ADR 0016 and keeps the configuration of ADR 0011. All four public access block settings are on, there is no bucket policy and no CORS rule, so objects are readable only with AWS credentials. A reader uses a DuckDB `credential_chain` secret (see README.md "Querying with DuckDB"). The 0017 apply was run on 2026-11-17 (see "Applying the private configuration"), so the deployed bucket is private. A lifecycle rule aborts incomplete multipart uploads one day after initiation, and the pipeline role needs no `s3:AbortMultipartUpload` because S3 applies the rule itself.
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

## Applying the private configuration

ADR 0017 reverses the changes ADR 0016 made to the module of the existing deployment: the access block's two policy settings go back from false to true, and the bucket policy and the CORS rule are removed. The apply is run by the operator (or by the orchestrator on Jarrod's go-ahead) after the plan is reviewed, never by an agent on its own. It was run on 2026-11-17 by the orchestrator on Jarrod's go-ahead with Terraform v1.15.8: the plan was 0 to add, 1 to change, 2 to destroy, the apply printed "Apply complete! Resources: 0 added, 1 changed, 2 destroyed.", and the check below printed 403. The result is recorded in the ADR. The decision is in `docs/decisions/0017-private-output-bucket-again.md`.

Plan with the same variables as the deployment and review the output:

```sh
terraform -chdir=infra init
terraform -chdir=infra plan -var bucket_name=<bucket> -var github_repository=jazzdos@33918812/swan-wetland-change@1438569874 -var create_oidc_provider=false -var aws_region=<region>
```

The expected plan is 0 to add, 1 to change, 2 to destroy. `aws_s3_bucket_public_access_block.outputs` is updated in place (`block_public_policy` and `restrict_public_buckets` from false to true), and `aws_s3_bucket_policy.public_read` and `aws_s3_bucket_cors_configuration.outputs` are destroyed. Refresh drift on `aws_iam_role.pipeline` and `aws_s3_bucket.outputs` (`inline_policy`, `lifecycle_rule`, `tags`) is the same noise ADR 0016 recorded, and the plan does not change it. Do not apply if the plan changes the role, its policies, the ownership controls, the lifecycle rule or the OIDC provider. Otherwise apply with the same variables:

```sh
terraform -chdir=infra apply -var bucket_name=<bucket> -var github_repository=jazzdos@33918812/swan-wetland-change@1438569874 -var create_oidc_provider=false -var aws_region=<region>
```

Then check with headers only. curl sends the request unsigned, so it is an anonymous request whatever AWS credentials the shell holds:

```sh
curl -sS -I "$(terraform -chdir=infra output -raw bucket_url)/stac/catalog.json" | grep -i -E '^HTTP/'
```

After the apply the check must print a 403 status line; on 2026-11-17 it printed 403. Before the apply it printed 200, because ADR 0016 was still applied. The check reads response headers only, not the object.

The `xfail` marker on `tests/test_live_anonymous_read.py` was removed after the apply (story st-5c05). That test is no longer an expected failure, and the weekly run now fails if an unsigned request to the bucket stops getting 403.

### Sharing one object

Someone with no AWS access can be given one object through a presigned URL. This is documented here, not built into the pipeline:

```sh
aws s3 presign s3://<bucket>/<key> --region <region> --expires-in 3600
```

The signer needs `s3:GetObject` on the object. A presigned URL stops working when the signing credentials expire, even if `--expires-in` has not elapsed.

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
- The bucket is private under ADR 0017, applied on 2026-11-17. Never add a bucket policy, a `*` principal or CORS without a new decision record that supersedes ADR 0017. Objects are readable only with AWS credentials or a presigned URL.
- The role only works from runs on `main`. A `workflow_dispatch` run from another branch cannot assume it.
- The 3 hour session duration takes effect only after an apply. An existing deployment must be applied again before the next pipeline run, because requesting a duration above the role maximum makes the role assumption fail.
