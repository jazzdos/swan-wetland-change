---
id: st-ae6e
title: Add OpenTofu infra for the public bucket and GitHub OIDC role
type: feature
epic: st-f849
priority: P2
depends_on: []
touches: [infra/**, .gitignore]
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

## Implementation Notes

## Questions
