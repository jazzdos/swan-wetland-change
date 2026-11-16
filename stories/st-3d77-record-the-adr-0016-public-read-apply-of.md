---
id: st-3d77
title: Record the ADR 0016 public-read apply of 2026-11-16
type: task
priority: P2
depends_on: []
discovered_from: st-1a5f
touches: [.github/workflows/verify.yml, README.md, config/pipeline.toml, docs/decisions/0016-public-read-output-bucket.md, infra/README.md, stories/st-1a5f-reopen-public-read-access-to-the-output.md, stories/st-3d77-record-the-adr-0016-public-read-apply-of.md, tests/test_infra.py, tests/test_live_anonymous_read.py, tests/test_live_credentialed_read.py, tests/test_public_read_decision.py, tests/test_readme.py, tests/test_workflows.py]
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

## Findings from verifying the story pointers in the worktree

All pointers hold; st-22f1 and its backfill have merged. Facts that shape the plan:
- tests/test_workflows.py pins no private-state wording today (it reads verify.yml only for secrets and actionlint). The only stale text in verify.yml is the word "private" in header comment line 22 ("in the private, unversioned bucket"). verify.yml has no "expected failure" wording; the xfail is described in the ADR, infra/README.md, README.md and the anonymous test. So tests/test_workflows.py gets NEW assertions (verify.yml header and the config/pipeline.toml [catalogue] comment no longer call the bucket private) instead of edits.
- tests/test_readme.py:178-189 (test_readme_ties_anonymous_read_to_the_operator_apply) pins "operator's apply" in Querying with DuckDB, Deployment and Limitations, plus "credential" and "0016-public-read-output-bucket". tests/test_readme.py:192 forbids the strings "bucket is public", "public bucket", "public-read bucket", "public s3", "intentionally public", "is publicly readable", "public_outputs" anywhere in the README. New README prose must avoid these exact strings ("readable anonymously" and "public read" are fine).
- tests/test_infra.py:221 pins the .tf descriptions (stay unchanged because .tf files stay). :231 requires infra/README.md to contain "operator's apply", "never by an agent", "billed to the bucket owner", "observations/" (case-insensitive) and forbids "the bucket is public" and "intentionally public". :342 requires the Applying public read section to keep the plan line, apply line and header-only curl line in that order and to contain: review, st-22f1, backfill, 200, "Access-Control-Allow-Origin: *", 403, xfail.
- tests/test_public_read_decision.py requires ADR 0016 status to start "Status: accepted, 2026-11-15", the "Preconditions of the apply" section to keep "run by the operator, never by an agent" and the other precondition phrases, and ADR 0011 to stay byte-identical outside its status line (do not touch 0011).

Guardrails for every step: do not run terraform, tofu, aws, curl or pytest -m live; do not read infra/terraform.tfstate or any output-store object; do not open docs/research/verification-*.md; do not edit any .tf file, LEARNINGS.md, docs/handoffs/*, docs/research/* or docs/decisions/0011-private-output-bucket.md. README must not say spike 6 or spike 7 has run. Flat factual prose, no em dashes.

## Steps (one batch, four independent tasks on disjoint files; TDD: edit tests first, see them fail, then edit prose)

1. ADR 0016 (docs/decisions/0016-public-read-output-bucket.md) and tests/test_public_read_decision.py.
   - Test first: extend test_adr_0016_supersedes_0011 so the flattened status contains "in effect since 2026-11-16" (still starts with "Status: accepted, 2026-11-15"); add test_adr_0016_records_the_2026_11_16_apply that reads the "Apply" section and asserts the facts below; keep test_adr_0016_keeps_the_operator_only_apply_and_its_preconditions unchanged (proves the original sentence survives). Update the module docstring (the apply is no longer only the operator's).
   - Prose: status line says public read in effect since the 2026-11-16 apply; add "## Apply" section after "Preconditions of the apply"; rewrite lines 86-88 and the Consequences bullets that describe the pre-apply state in past tense / as current; leave the "never by an agent" sentence unchanged.
2. README.md and tests/test_readme.py. Test proves the README says public read took effect at the 2026-11-16 apply in Querying with DuckDB, Deployment and Limitations, the STAC row no longer says the bucket is private, and no claim that stac-browser or a live STAC check ran.
3. infra/README.md and tests/test_infra.py. Test proves the section and Notes state that public read took effect at the 2026-11-16 apply while the plan, apply and header-check procedure is kept.
4. tests/test_live_anonymous_read.py (remove xfail, update docstring and comment), tests/test_live_credentialed_read.py docstring, config/pipeline.toml [catalogue] comment, .github/workflows/verify.yml header comment, and new assertions in tests/test_workflows.py. Test proves verify.yml header and the [catalogue] comment contain neither "private" nor "expected failure"; the live test module has no xfail (assert via source text, do not run it).

Final gate (run by the implementer after all tasks, one command per line): uv run ruff check src tests scripts; uv run ruff format --check src tests scripts; uv run mypy src scripts; uv run pytest -q.

## Implementation Notes

- 2026-11-16T09:03:38.235Z: The CLI split each --ac value at commas (list flag), so the checkbox list above is fragmented. The six intended acceptance criteria, which the plan and review use: (1) tests/test_live_anonymous_read.py has no xfail marker, and its docstring says the bucket has been publicly readable since the 2026-11-16 apply. (2) ADR 0016 has an 'Apply' section recording the 2026-11-16 apply: run by the orchestrator on Jarrod's instruction 'just make it public' as a deviation from the 'never by an agent' sentence, which stays unchanged; plan 2 to add, 1 to change, 0 to destroy; refresh drift limited to aws_iam_role.pipeline inline_policy and tags and aws_s3_bucket.outputs lifecycle_rule and tags; header-only check 200 with Access-Control-Allow-Origin *; anonymous listing status 200 for observations/ and 403 for the root and ledger/. Its status line says public read is in effect since 2026-11-16. (3) The README verification matrix STAC catalogue row no longer says the bucket is private; it says the catalogue is readable anonymously over https with CORS since the 2026-11-16 apply, and does not claim stac-browser or a live STAC check has been run. (4) The [catalogue] comment in config/pipeline.toml and the header comment of .github/workflows/verify.yml no longer say the bucket is private or that the anonymous test is an expected failure. (5) README 'Querying with DuckDB', 'Deployment' and 'Limitations', and infra/README.md 'Applying public read' and 'Notes', state that public read took effect at the 2026-11-16 apply instead of saying the bucket is private until the operator's apply; infra/README.md keeps the plan, apply and header-only check procedure. (6) Tests that pinned the private-state wording assert the new statements, and the four gates (ruff check, ruff format --check, mypy, pytest -q) pass.

## Questions
