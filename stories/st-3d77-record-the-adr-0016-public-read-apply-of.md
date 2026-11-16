---
id: st-3d77
title: Record the ADR 0016 public-read apply of 2026-11-16
type: task
priority: P2
depends_on: []
discovered_from: st-1a5f
touches: [README.md, infra/README.md, config/pipeline.toml, .github/workflows/verify.yml, docs/decisions/0016-public-read-output-bucket.md, tests/test_live_anonymous_read.py, tests/test_live_credentialed_read.py, tests/test_readme.py, tests/test_infra.py, tests/test_public_read_decision.py, tests/test_workflows.py]
exclusive: false
created: 2026-11-16
updated: 2026-11-16
---

## Description

The output bucket became publicly readable on 2026-11-16 (ADR 0016 apply; details in the 2026-11-16 note on st-1a5f). Jarrod said 'just make it public' and the orchestrator ran terraform plan and apply, a deviation from ADR 0016's 'The apply is run by the operator, never by an agent'. ADR 0016 says the commit that records the apply removes the xfail marker from tests/test_live_anonymous_read.py and updates the statements that hold only while the bucket is private: the STAC catalogue row of the README verification matrix (README.md:229), the [catalogue] comment in config/pipeline.toml (around line 50) and the header comment of .github/workflows/verify.yml. Other statements now stale: README.md 398-402, 436-440, 454, 468-469, 615-630, 673-674; infra/README.md 49, 76-78, 148; ADR 0016 status line (lines 3-5), lines 86-88 and Consequences; tests/test_live_anonymous_read.py docstring (lines 1-8) and comment line 73; tests/test_live_credentialed_read.py docstring lines 4-6. Tests pin some of the old wording: tests/test_readme.py:184-189, tests/test_infra.py:221, 231, 342, tests/test_public_read_decision.py, tests/test_workflows.py. infra/*.tf comments and descriptions ('takes effect when the operator applies this module') may stay as they are; do not change any resource. Guardrails: no agent runs terraform, tofu, aws, curl against the bucket or pytest -m live, reads infra/terraform.tfstate, or reads any output-store object; blindness rules in LEARNINGS.md for st-b6bf and st-dd0d stay in force (spike 6 and the anonymous half of spike 7 are unblocked by the apply, but agents do not read observations until those decision files are committed). LEARNINGS.md is not edited. Dated snapshots (docs/handoffs/*, docs/research/*, ADR 0011) are not edited.

## Acceptance Criteria

- [ ] tests/test_live_anonymous_read.py has no xfail marker
- [ ] and its docstring says the bucket has been publicly readable since the 2026-11-16 apply
- [ ] ADR 0016 has an 'Apply' section recording the 2026-11-16 apply: run by the orchestrator on Jarrod's instruction 'just make it public' as a deviation from the 'never by an agent' sentence
- [ ] which stays unchanged; plan 2 to add
- [ ] 1 to change
- [ ] 0 to destroy; refresh drift limited to aws_iam_role.pipeline inline_policy and tags and aws_s3_bucket.outputs lifecycle_rule and tags; header-only check 200 with Access-Control-Allow-Origin *; anonymous listing status 200 for observations/ and 403 for the root and ledger/. Its status line says public read is in effect since 2026-11-16
- [ ] README verification matrix STAC catalogue row no longer says the bucket is private; it says the catalogue is readable anonymously over https with CORS since the 2026-11-16 apply
- [ ] and does not claim stac-browser or a live STAC check has been run
- [ ] The [catalogue] comment in config/pipeline.toml and the header comment of .github/workflows/verify.yml no longer say the bucket is private or that the anonymous test is an expected failure
- [ ] README 'Querying with DuckDB'
- [ ] 'Deployment' and 'Limitations'
- [ ] and infra/README.md 'Applying public read' and 'Notes'
- [ ] state that public read took effect at the 2026-11-16 apply instead of saying the bucket is private until the operator's apply; infra/README.md keeps the plan
- [ ] apply and header-only check procedure
- [ ] Tests that pinned the private-state wording assert the new statements
- [ ] and the four gates (ruff check
- [ ] ruff format --check
- [ ] mypy
- [ ] pytest -q) pass

## Implementation Plan

## Implementation Notes

- 2026-11-16T09:03:38.235Z: The CLI split each --ac value at commas (list flag), so the checkbox list above is fragmented. The six intended acceptance criteria, which the plan and review use: (1) tests/test_live_anonymous_read.py has no xfail marker, and its docstring says the bucket has been publicly readable since the 2026-11-16 apply. (2) ADR 0016 has an 'Apply' section recording the 2026-11-16 apply: run by the orchestrator on Jarrod's instruction 'just make it public' as a deviation from the 'never by an agent' sentence, which stays unchanged; plan 2 to add, 1 to change, 0 to destroy; refresh drift limited to aws_iam_role.pipeline inline_policy and tags and aws_s3_bucket.outputs lifecycle_rule and tags; header-only check 200 with Access-Control-Allow-Origin *; anonymous listing status 200 for observations/ and 403 for the root and ledger/. Its status line says public read is in effect since 2026-11-16. (3) The README verification matrix STAC catalogue row no longer says the bucket is private; it says the catalogue is readable anonymously over https with CORS since the 2026-11-16 apply, and does not claim stac-browser or a live STAC check has been run. (4) The [catalogue] comment in config/pipeline.toml and the header comment of .github/workflows/verify.yml no longer say the bucket is private or that the anonymous test is an expected failure. (5) README 'Querying with DuckDB', 'Deployment' and 'Limitations', and infra/README.md 'Applying public read' and 'Notes', state that public read took effect at the 2026-11-16 apply instead of saying the bucket is private until the operator's apply; infra/README.md keeps the plan, apply and header-only check procedure. (6) Tests that pinned the private-state wording assert the new statements, and the four gates (ruff check, ruff format --check, mypy, pytest -q) pass.

## Questions
