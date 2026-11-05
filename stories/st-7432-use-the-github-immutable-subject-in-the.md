---
id: st-7432
title: Use the GitHub immutable subject in the deploy role trust policy
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [infra/README.md, infra/variables.tf, tests/test_infra.py]
exclusive: false
created: 2026-11-03
updated: 2026-11-05
---

## Description

GitHub OIDC tokens for this repository carry an immutable subject. The API call gh api repos/jazzdos/swan-wetland-change/actions/oidc/customization/sub returned use_immutable_subject true and sub_claim_prefix repo:jazzdos@33918812/swan-wetland-change@1438569874 on 2026-11-03. The trust policy in infra/main.tf builds repo:${var.github_repository}:ref:refs/heads/main from an owner/name value, so it yields repo:jazzdos/swan-wetland-change:ref:refs/heads/main, which never matches the token, and the pipeline role cannot be assumed. The validation on var.github_repository rejects the @ character, so the immutable form cannot be passed in as a value. Keep the :ref:refs/heads/main suffix so only main can assume the role. Change the variable so it takes the immutable form, and rename it if that reads better. create_oidc_provider stays an optional variable with its existing default; the owner passes false at apply because the AWS account already has the provider, so show that in the README apply commands. Applying is out of scope and stays local.

## Acceptance Criteria

- [ ] The trust policy sub condition resolves to repo:jazzdos@33918812/swan-wetland-change@1438569874:ref:refs/heads/main for the value documented in infra/README.md
- [ ] The variable validation accepts the immutable form and rejects plain owner/name
- [ ] tests/test_infra.py pins the new subject template and exercises the validation regex against both forms
- [ ] infra/README.md explains the immutable form and the gh api call that reads it and its apply commands pass create_oidc_provider=false
- [ ] terraform -chdir=infra validate exits 0

## Implementation Plan

## Implementation Notes

- 2026-11-05T08:54:04.990Z: Implemented by cloud session https://claude.ai/code/session_01FNRugMhxCk9NxsEcKHuGsF as 5f1c25a. Checked locally on main merged with all batch branches: ruff, ruff format, mypy pass; pytest 452 passed 1 skipped with and without GITHUB_ACTIONS=true; terraform validate rc 0; actionlint rc 0. Real Terraform regex evaluation accepts the immutable value and rejects owner/name, a missing repo id and a repo: prefix. gh api still returns sub_claim_prefix repo:jazzdos@33918812/swan-wetland-change@1438569874 on 2026-11-05. Restoring the old variables.tf fails 2 tests in tests/test_infra.py. Applying stays local and out of scope.

## Questions
