# Infrastructure

OpenTofu/Terraform module for the AWS resources the swan-wetland-change pipeline needs. The pipeline runs scheduled NDWI/NDVI change detection for Swan Coastal Plain Ramsar wetlands and publishes outputs and a STAC catalogue to S3.

## What the module creates

- A public-read S3 bucket. Anonymous callers get `s3:GetObject` only; there is no public list, put or delete. CORS allows GET and HEAD from any origin because stac-browser on GitHub Pages reads the STAC catalogue from the bucket.
- The GitHub OIDC provider `token.actions.githubusercontent.com` with audience `sts.amazonaws.com`, when `create_oidc_provider` is true (the default). An AWS account can hold only one such provider, and other repositories usually share it. If the account already has one, pass `-var create_oidc_provider=false`, as the commands below do. The module then looks the provider up with a data source and leaves it unmanaged. Do not import an existing provider into this state: a later `destroy` would delete it and break GitHub-to-AWS authentication for every other repository in the account.
- An IAM role `swan-wetland-change-pipeline`, assumable only from the repository's `main` branch. The trust policy requires `token.actions.githubusercontent.com:aud` = `sts.amazonaws.com` and `token.actions.githubusercontent.com:sub` = `repo:<owner>@<owner_id>/<name>@<repo_id>:ref:refs/heads/main`. The role has `s3:ListBucket` on the bucket and `s3:GetObject`, `s3:PutObject` and `s3:DeleteObject` on its objects, and nothing else.

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

## Seeding the output root before the first scheduled run

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
- The bucket is intentionally public-read for objects. Never write private data to it.
- The role only works from runs on `main`. A `workflow_dispatch` run from another branch cannot assume it.
