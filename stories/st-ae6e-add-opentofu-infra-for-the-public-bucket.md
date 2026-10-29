---
id: st-ae6e
title: Add OpenTofu infra for the public bucket and GitHub OIDC role
type: feature
epic: st-f849
priority: P2
depends_on: []
touches: [.gitignore, infra/.terraform.lock.hcl, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, infra/versions.tf, tests/test_infra.py]
exclusive: false
created: 2026-10-29
updated: 2026-10-29
---
## Description

Add the `infra/` OpenTofu module (design, Components): a public-read bucket with CORS, the GitHub OIDC provider, and a role for the pipeline. Validate offline only; never run `plan` or `apply` and never call AWS. `tofu` is not installed on this machine but `terraform` is; keep the HCL OpenTofu-compatible.

- Variables `bucket_name`, `github_repository` (owner/name) and `aws_region`, with no defaults that point at real resources.
- S3 bucket allowing anonymous `s3:GetObject` only: no public list, put or delete.
- CORS allowing GET and HEAD from any origin, because stac-browser on GitHub Pages reads the catalogue.
- OIDC provider `token.actions.githubusercontent.com` with audience `sts.amazonaws.com`.
- IAM role assumable only from the repository's `main` branch, with object read, write, delete and bucket list limited to this bucket.
- Outputs: role ARN and bucket https URL.
- `infra/README.md` with the apply steps and the repository variables the workflows read: `AWS_ROLE_ARN`, `OUTPUT_BUCKET`, `AWS_REGION`.

## Acceptance Criteria

- [ ] `terraform -chdir=infra init -backend=false` and `terraform -chdir=infra validate` exit 0, or the `tofu` equivalents.
- [ ] `terraform -chdir=infra fmt -check -recursive` exits 0.
- [ ] The role trust policy conditions `token.actions.githubusercontent.com:aud` on `sts.amazonaws.com` and `token.actions.githubusercontent.com:sub` on `repo:${var.github_repository}:ref:refs/heads/main`.
- [ ] The bucket policy grants anonymous principals `s3:GetObject` and nothing else.
- [ ] The CORS rule allows GET and HEAD from `*`.
- [ ] `infra/README.md` lists the apply commands and the three repository variables.
- [ ] `.gitignore` excludes `infra/.terraform/` and Terraform state files.

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-ae6e)

- `infra/` does not exist. `.gitignore` has no Terraform entries. No prerequisite story is needed (depends_on is empty in effect; st-ec32 later consumes the `AWS_ROLE_ARN`, `OUTPUT_BUCKET`, `AWS_REGION` variables this story documents).
- `terraform` v1.15.8 is at /opt/homebrew/bin/terraform; `tofu` is absent. `init -backend=false` downloads the hashicorp/aws provider from the public registry only (no AWS API calls), which is acceptable. Never run `plan` or `apply`.
- A draft of the HCL below was already run through `terraform init -backend=false`, `validate` and `fmt -check -recursive`; all exit 0. It lives at /private/tmp/claude-501/-Users-jarrodbaker-Documents-satellite-detection/a40661af-2c8a-470e-838e-31c57853b368/scratchpad/infra-draft (reference only; the one change since is the fixed role name).
- Tests run via `uv run pytest -q` (testpaths `tests`, `-m 'not live'`). Repo gates: ruff check, ruff format --check, mypy on src and scripts, pytest. CI does not install terraform, so the pytest check is plain-text assertions on the HCL (no terraform binary needed).

## Steps

1. Write `tests/test_infra.py` first (red): text-level assertions on `infra/*.tf` proving the acceptance criteria that terraform validate cannot prove (it only checks syntax and schema).
   - trust policy contains `token.actions.githubusercontent.com:aud` with `sts.amazonaws.com` and `token.actions.githubusercontent.com:sub` with `repo:${var.github_repository}:ref:refs/heads/main`;
   - the public-read policy document has exactly one statement whose only action is `s3:GetObject` and whose principal is `*`; no `s3:ListBucket`, `s3:PutObject`, `s3:DeleteObject` or `s3:*` in that document;
   - CORS has `allowed_methods = ["GET", "HEAD"]` and `allowed_origins = ["*"]`;
   - OIDC provider url is `https://token.actions.githubusercontent.com` with `client_id_list = ["sts.amazonaws.com"]`;
   - variables `bucket_name`, `github_repository`, `aws_region` exist with no `default`;
   - outputs `role_arn` and `bucket_url` exist;
   - `.gitignore` contains `infra/.terraform/` and `*.tfstate`;
   - `infra/README.md` mentions `AWS_ROLE_ARN`, `OUTPUT_BUCKET`, `AWS_REGION`, `terraform -chdir=infra` or `tofu -chdir=infra` apply commands.
2. Create `infra/versions.tf`, `infra/variables.tf`, `infra/main.tf`, `infra/outputs.tf` (content in the task prompt). Public-read via bucket policy with `block_public_policy = false` and `restrict_public_buckets = false`, ACL blocks left on, `BucketOwnerEnforced` ownership. Pipeline role policy: `s3:ListBucket` on the bucket ARN; `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on `bucket/*`.
3. `terraform -chdir=infra init -backend=false`; commit the generated `infra/.terraform.lock.hcl` (it pins the provider; do not gitignore it). Optionally add `terraform -chdir=infra providers lock -platform=linux_amd64 -platform=darwin_arm64` (registry only).
4. `.gitignore`: add `infra/.terraform/`, `*.tfstate`, `*.tfstate.*`, `*.tfvars`, `crash.log`.
5. Write `infra/README.md` with apply steps and the three repository variables.
6. Verify: `terraform -chdir=infra validate`, `terraform -chdir=infra fmt -check -recursive`, then `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. Confirm `git status` shows no `.terraform/` directory or state file staged (`git check-ignore -v infra/.terraform/x infra/terraform.tfstate`).

## Implementation Notes

- 2026-10-29T19:32:49.739Z: touches-expansion: overlaps st-1990 (LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.740Z: touches-expansion: overlaps st-8228 (LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.741Z: touches-expansion: overlaps st-afcf (LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.743Z: touches-expansion: overlaps st-d4a8 (LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split
- 2026-10-29T19:32:49.744Z: touches-expansion: overlaps st-f4d3 (LEARNINGS.md, config/pipeline.toml, docs/research/2026-10-29-polygon-calibration.csv, pyproject.toml, src/wetland_change/catalogue/search.py, src/wetland_change/change.py, src/wetland_change/cli.py, src/wetland_change/config.py, src/wetland_change/ledger.py, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/stac/__init__.py, src/wetland_change/stac/catalogue.py, src/wetland_change/stac/io.py, src/wetland_change/verify/copernicus.py, src/wetland_change/verify/run.py, tests/test_backfill.py, tests/test_catalogue.py, tests/test_change.py, tests/test_cli.py, tests/test_config.py, tests/test_ledger.py, tests/test_live_verify.py, tests/test_pipeline.py, tests/test_search.py, tests/test_verify.py, tests/test_verify_copernicus.py, uv.lock) — coordinate or split

## Questions
