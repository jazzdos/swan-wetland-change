---
id: st-5c05
title: Record the ADR 0017 private-bucket apply of 2026-11-17
type: chore
priority: P1
depends_on: [st-90b4]
touches: [.github/workflows/verify.yml, README.md, config/pipeline.toml, docs/decisions/0016-public-read-output-bucket.md, docs/decisions/0017-private-output-bucket-again.md, infra/README.md, infra/outputs.tf, infra/variables.tf, tests/test_infra.py, tests/test_live_anonymous_read.py, tests/test_public_read_decision.py, tests/test_readme.py, tests/test_workflows.py]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

The output bucket became private on 2026-11-17 when the ADR 0017 apply ran (`docs/decisions/0017-private-output-bucket-again.md`, story st-90b4, merged to main as 313aba8). The repository still describes that apply as pending. This story records it and updates every statement that held only until the apply. It is documentation and test markers only; no infra resource changes.

Facts of the apply, for the ADR 0017 `## Apply` section (record them as written here):

- Run by the orchestrator on Jarrod's go-ahead. On 2026-11-17 Jarrod chose "Approve, do it all (Recommended)" for a plan that read: merge st-90b4, run terraform plan with the accu-tracker profile, apply only if the plan is exactly 1 change and 2 destroys, check that an anonymous request gets 403, record the apply in a follow-up story, push.
- Tooling: Terraform v1.15.8, profile `accu-tracker` after `aws login`, credentials exported to the environment. Run from main at 313aba8 with `-var bucket_name=swan-wetland-change-outputs-263051716913 -var github_repository=jazzdos@33918812/swan-wetland-change@1438569874 -var create_oidc_provider=false -var aws_region=ap-southeast-2`, as a saved plan.
- Plan: 0 to add, 1 to change, 2 to destroy. `aws_s3_bucket_public_access_block.outputs` updated in place (`block_public_policy` and `restrict_public_buckets` false to true, 3 attributes unchanged); `aws_s3_bucket_policy.public_read` and `aws_s3_bucket_cors_configuration.outputs` destroyed because they are no longer in configuration. No refresh drift was reported and nothing else changed.
- Apply: "Apply complete! Resources: 0 added, 1 changed, 2 destroyed." Finished by 2026-11-17T12:19:58Z.
- Unsigned check about 5 seconds later, status codes only, bodies discarded, AWS credential variables unset: GET `stac/catalog.json` returned 403; ListObjectsV2 with prefix `observations/` returned 403.
- Exposure window: every object was readable by key without credentials from the 2026-11-16 apply until 2026-11-17 about 12:20 UTC.
- No output-store object was read. The st-b6bf and st-dd0d blindness rules in `LEARNINGS.md` stay in force.

What to change:

- `docs/decisions/0017-private-output-bucket-again.md`: status line says accepted and in effect since the 2026-11-17 apply; `## Apply` holds the facts above in place of "pending"; Evidence and any sentence that says the apply is pending or the test is an expected failure is updated. `docs/decisions/0016-public-read-output-bucket.md`: only its status paragraph changes, to say 0017 was applied on 2026-11-17 (its rest-of-file sha256 pinned in `tests/test_public_read_decision.py` must stay as is).
- `tests/test_live_anonymous_read.py`: remove the `xfail` marker and update its docstring; it stays marked `live` and keeps both 403 assertions.
- Statements that held only until the apply: `README.md` (around lines 405-410, 478-482, 630-645), `infra/README.md` (around lines 7 and 72, the "Applying the private configuration" section: say it was applied and the check printed 403), `infra/variables.tf` and `infra/outputs.tf` description text only, the `[catalogue]` comment in `config/pipeline.toml`, and the header comment of `.github/workflows/verify.yml` (the anonymous test is no longer an expected failure; the weekly run now fails if the bucket becomes anonymously readable again).
- Tests that pin the pending wording (`tests/test_public_read_decision.py`, `tests/test_workflows.py`, `tests/test_readme.py`, `tests/test_infra.py`) are updated to pin the applied state, including a check that `tests/test_live_anonymous_read.py` carries no `xfail` marker.

Out of scope: any infra resource, block or argument other than description strings; the README line about a decision "pending Jarrod's review" (around line 715), which concerns a different decision.

Guardrails: no agent runs `terraform`, `tofu`, `aws`, `curl` against the bucket or `pytest -m live`, reads `infra/terraform.tfstate`, or reads any output-store object. `LEARNINGS.md`, `docs/handoffs/*`, `docs/research/*` and ADR 0011 are not edited.

## Acceptance Criteria

- [ ] `docs/decisions/0017-private-output-bucket-again.md` has an `## Apply` section that contains "0 to add, 1 to change, 2 to destroy", "Apply complete", "2026-11-17", "403" and "Terraform v1.15.8", and no sentence in the file says the apply is pending
- [ ] The only change to `docs/decisions/0016-public-read-output-bucket.md` is its status paragraph, which no longer says 0017's apply is pending, and the rest-of-file sha256 test in `tests/test_public_read_decision.py` passes unchanged
- [ ] `tests/test_live_anonymous_read.py` has no `xfail` marker, is marked `live`, and asserts 403 for the unsigned GET of `stac/catalog.json` and the unsigned listing under `observations/`; a test in `tests/test_workflows.py` fails if an `xfail` marker returns
- [ ] `grep -rniE "apply is pending|apply pending|once its apply is done|until then the deployed bucket|still has the ADR 0016" README.md infra/README.md infra/*.tf config/pipeline.toml .github/workflows/verify.yml tests/test_live_anonymous_read.py docs/decisions/0017-private-output-bucket-again.md` prints nothing (dated history such as "from the 2026-11-16 apply until the 0017 apply" may stay)
- [ ] `git diff main -- infra/*.tf` changes only `description` strings
- [ ] `terraform -chdir=infra fmt -check` passes
- [ ] `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts` and `uv run pytest -q` pass

## Implementation Plan

# st-5c05 plan: record the ADR 0017 private-bucket apply

All file pointers in the story were checked in the worktree `/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-5c05` (HEAD 313aba8, st-90b4 merged). They hold. Extra stale statements found beyond the story's list: `README.md` line 233 ("once the 0017 apply is done"), `README.md` line 694-695 region is unrelated and stays, `infra/README.md` lines 49, 70, 72 and 152, `infra/outputs.tf` line 7, `infra/variables.tf` line 2. `docs/decisions/0016-public-read-output-bucket.md` status paragraph says "0017's apply is pending".

Documentation and test markers only. No agent runs terraform, tofu, aws, curl against the bucket or `pytest -m live`, reads `infra/terraform.tfstate`, or reads an output-store object. `terraform fmt -check` is the operator's check; the only `.tf` edits are single-line `description` strings, which cannot change formatting. `LEARNINGS.md`, `docs/handoffs/*`, `docs/research/*` and ADR 0011 are not edited.

Steps, all in one batch because the four tasks touch disjoint files:

1. ADR 0016 and 0017 plus `tests/test_public_read_decision.py`.
   - 0017: Status line says accepted and in effect since the 2026-11-17 apply; `## Apply` replaced with the recorded facts (Terraform v1.15.8, profile `accu-tracker` after `aws login`, saved plan from main at 313aba8 with the four -var flags, plan 0 to add, 1 to change, 2 to destroy, "Apply complete! Resources: 0 added, 1 changed, 2 destroyed.", finished by 2026-11-17T12:19:58Z, unsigned check 403 and 403, exposure window to about 12:20 UTC, no output-store object read); Evidence bullet 2 rewritten (live test is no longer xfail); the "once the apply has run" sentence in Decision rewritten; the word "pending" appears nowhere in the file.
   - 0016: only the status paragraph (between `Status:` and `Supersedes:`) changes. Its rest-of-file sha256 test passes unchanged.
   - Tests: replace `test_adr_0017_says_the_apply_is_pending` with `test_adr_0017_records_the_apply` (Apply section contains the required strings, whole file has no "pending"); update the module docstring; extend `test_adr_0016_status_names_0017` to require "applied on 2026-11-17" and no "pending".
2. `tests/test_live_anonymous_read.py` plus `.github/workflows/verify.yml` header plus `tests/test_workflows.py`.
   - Remove the `xfail` marker (pytestmark becomes a list with only `pytest.mark.live`), rewrite the docstring, keep both 403 assertions.
   - verify.yml header lines 20-23 rewritten: the anonymous test is no longer an expected failure, and the weekly run fails if the bucket becomes anonymously readable again.
   - Tests: `test_verify_header_comment_names_adr_0017_and_no_public_read` now requires "no longer an expected failure" and "fails" and drops the "xfail" requirement; `test_anonymous_live_test_is_a_strict_xfail_naming_the_0017_apply` replaced by `test_anonymous_live_test_is_live_with_no_xfail_marker` (AST: pytestmark holds `pytest.mark.live`, no xfail call anywhere in the module, "xfail" absent from source other than none, two `== 403` assertions, `stac/catalog.json`, `prefix=observations/`, no `.read(`).
3. `README.md` plus `tests/test_readme.py`.
   - Lines 233, 403-410, 478-482, 630-645 rewritten as applied-state statements (bucket private since the 2026-11-17 apply; anonymous GET of catalog.json and listing under observations/ returned 403 about 5 seconds after the apply; test no longer xfail; exposure window; copies cannot be withdrawn; no agent has run the live test and the weekly verify.yml run executes it). The line about a decision "pending Jarrod's review" (about line 715) is untouched.
   - Tests: `test_readme_records_adr_0017` drops the "pending" requirements and instead requires "applied" or "2026-11-17" in Deployment and "no longer" style wording absent a "pending"; asserts "pending" not near 0017; `test_readme_limitations_dates_anonymous_live_pass` keeps "xfail" (text says the marker was removed) and "403".
4. `infra/README.md`, `infra/variables.tf`, `infra/outputs.tf`, `config/pipeline.toml` plus `tests/test_infra.py` and the catalogue-comment test in `tests/test_workflows.py` (only if its assertions break).
   - infra/README.md lines 7, 49, 70, 72, 152 rewritten (applied 2026-11-17, check printed 403, xfail marker removed, weekly run fails if anonymously readable again).
   - Descriptions: variables.tf and outputs.tf say private under ADR 0017 and reads need AWS credentials; no "until the 0017 apply" or "pending" text. `git diff main -- infra/*.tf` shows `description` lines only.
   - pipeline.toml `[catalogue]` comment: says links need AWS credentials or a presigned URL under ADR 0017 (applied 2026-11-17); must not contain "is private", "without credentials", "publicly readable", "anonymously readable", "readable anonymously".
   - Tests: rename `test_bucket_descriptions_say_private_and_name_the_pending_apply` to `test_bucket_descriptions_say_private_under_adr_0017` asserting "ADR 0017", "AWS credentials", and absence of "pending", "until the 0017 apply" and "ADR 0016"; `test_infra_readme_gives_plan_review_apply_and_header_check` keeps its checks, requires "403" and "2026-11-17" and "Apply complete", and drops "xfail"-requirement in favour of "no longer".

Final verification (task 5 is part of the last batch step, run by the implementer after all four tasks): the acceptance grep prints nothing, then in order `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`.
