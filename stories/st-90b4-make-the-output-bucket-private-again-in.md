---
id: st-90b4
title: Make the output bucket private again in code under ADR 0017
type: feature
priority: P1
depends_on: []
touches: [.github/workflows/verify.yml, README.md, config/pipeline.toml, docs/decisions/0016-public-read-output-bucket.md, docs/decisions/0017-private-output-bucket-again.md, infra/README.md, infra/main.tf, infra/outputs.tf, infra/variables.tf, tests/test_infra.py, tests/test_live_anonymous_read.py, tests/test_public_read_decision.py, tests/test_readme.py, tests/test_workflows.py]
exclusive: false
created: 2026-11-17
updated: 2026-11-17
---
## Description

On 2026-11-17 Jarrod directed: "just make it password protected so its not public - im not contacting dbca". The output bucket has been publicly readable since the 2026-11-16 apply under `docs/decisions/0016-public-read-output-bucket.md` (anonymous `s3:GetObject` on every object, anonymous `s3:ListBucket` under `observations/`, CORS GET and HEAD from any origin). S3 has no password mode; "password protected" is read as: readable only with AWS credentials (IAM), as it was under ADR 0011. One-off sharing with someone who has no AWS access is by presigned URL, which this story documents but does not build.

This story makes the module private again in code and records the decision. It applies nothing. The apply is run afterwards by the orchestrator on Jarrod's go-ahead, and a follow-up story records it.

What to change:

- Infra (`infra/main.tf`, `infra/variables.tf`, `infra/outputs.tf`). Set all four `aws_s3_bucket_public_access_block.outputs` settings to true. Remove `aws_s3_bucket_policy.public_read`, the `public_read` policy document and `aws_s3_bucket_cors_configuration.outputs`. The pipeline role (OIDC trust on `main`, `s3:ListBucket` on the bucket, Get, Put and Delete on objects), the ownership controls, the lifecycle rule and the outputs `role_arn` and `bucket_url` stay exactly as they are. The private configuration of record is ADR 0011 and the st-bbbf story commit `09f94a9`.
- ADR. Write `docs/decisions/0017-<slug>.md` superseding 0016 (0014 and 0015 stay reserved for st-b6bf and st-dd0d). Change only the status line of 0016, to name 0017. 0017 records: Jarrod's direction quoted verbatim with its date; that DBCA's written confirmation (st-4c87, ADR 0016 precondition 3) is no longer sought because nothing is publicly redistributed; that every object was anonymously readable by key from the 2026-11-16 apply until the 0017 apply, and copies taken then cannot be withdrawn; the effect on design success criteria 2 and 3 (credentialed readers only); that spike 6 and the anonymous half of spike 7 (st-9f02) are shelved; how readers get access (AWS credentials through DuckDB's `credential_chain` secret, presigned URLs for one-off sharing); the expected plan; and an `## Apply` section stating the apply is pending.
- Live test. Replace the checks in `tests/test_live_anonymous_read.py` with a live test (marked `live`, and `xfail(strict=True)` with a reason naming the pending 0017 apply) that sends unsigned requests and asserts a GET of `stac/catalog.json` and a ListObjectsV2 under `observations/` both return 403, reading status codes only and discarding bodies. `tests/test_live_credentialed_read.py` stays as it is.
- Offline tests. `tests/test_infra.py` asserts the private configuration. Replace `tests/test_public_read_decision.py` with a test of ADR 0017 and of the 0016 status line. Update `tests/test_readme.py` and `tests/test_workflows.py` wherever they pin public-read wording.
- Docs. `README.md` (the DuckDB section around lines 400-480, the access history around 480-525, the verification matrix STAC row, and lines 640-705), `infra/README.md` (replace "Applying public read" with a section on applying the private configuration: the expected plan and an unsigned header-only check that expects 403), the `[catalogue]` comment in `config/pipeline.toml` (around line 50) and the header comment of `.github/workflows/verify.yml`. `catalogue.base_url` stays unchanged; its links need credentials once the apply is done.

Out of scope: licence and attribution text inside published files (harmless on a private bucket); the `redistribute_public` column of `data/SOURCES.md` (it records what a source permits, not what this project does); the GitHub repository's visibility; `src/wetland_change/raster/env.py` (unsigned reads of third-party Earth Search COGs).

Guardrails: no agent runs `terraform`, `tofu plan`, `tofu apply`, `aws`, `curl` against the bucket, or `pytest -m live`, reads `infra/terraform.tfstate`, or reads any output-store object. The st-b6bf and st-dd0d blindness rules in `LEARNINGS.md` stay in force. `LEARNINGS.md` is not edited. Dated snapshots (`docs/handoffs/*`, `docs/research/*`, ADR 0011) are not edited, and ADR 0016 changes only on its status line.

## Acceptance Criteria

- [ ] `infra/main.tf` sets `block_public_acls`, `ignore_public_acls`, `block_public_policy` and `restrict_public_buckets` to true on `aws_s3_bucket_public_access_block.outputs`
- [ ] `infra/main.tf` contains no `aws_s3_bucket_policy` resource, no `public_read` policy document, no `aws_s3_bucket_cors_configuration` resource, and no statement whose principal is `*`
- [ ] `git diff main -- infra/` shows no change to the pipeline role, its trust or permission policies, the ownership controls, the lifecycle rule, or the outputs `role_arn` and `bucket_url`
- [ ] `tests/test_infra.py` fails when any access-block setting is false, a bucket policy or `*` principal is added, or a CORS configuration is added
- [ ] `tests/test_live_anonymous_read.py` holds one or more tests marked `live` and `xfail(strict=True)` whose reason names the pending 0017 apply, asserting 403 for an unsigned GET of `stac/catalog.json` and an unsigned ListObjectsV2 with prefix `observations/`
- [ ] `docs/decisions/0017-*.md` exists, says it supersedes 0016, quotes Jarrod's 2026-11-17 direction verbatim, and has an `## Apply` section that says the apply is pending; the only change to `docs/decisions/0016-public-read-output-bucket.md` is its status line, which names 0017
- [ ] `tests/test_public_read_decision.py` is replaced by a test that checks ADR 0017's supersession, quote and Apply section and the 0016 status line
- [ ] `README.md` has no anonymous DuckDB secret example, its DuckDB example uses a `credential_chain` secret, and `tests/test_readme.py` fails if a sentence says the bucket, catalogue or observations are publicly or anonymously readable
- [ ] `infra/README.md` has no "Applying public read" section, and a section on applying the private configuration names the expected plan (0 to add, 1 to change, 2 to destroy: `aws_s3_bucket_public_access_block.outputs` updated, `aws_s3_bucket_policy.public_read` and `aws_s3_bucket_cors_configuration.outputs` destroyed) and an unsigned header-only check that expects 403
- [ ] The `[catalogue]` comment in `config/pipeline.toml` and the header comment of `.github/workflows/verify.yml` do not say the bucket is anonymously or publicly readable
- [ ] `terraform -chdir=infra fmt -check` passes
- [ ] `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts` and `uv run pytest -q` pass

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-90b4, at 905de12)

All story pointers hold. Findings that shape the plan:
- `infra/main.tf` still has `aws_s3_bucket_public_access_block.outputs` with `block_public_policy=false` and `restrict_public_buckets=false`, `data.aws_iam_policy_document.public_read`, `aws_s3_bucket_policy.public_read` and `aws_s3_bucket_cors_configuration.outputs`. ADR 0011 and commit 09f94a9 hold the private form.
- `docs/decisions/` has 0001-0013 and 0016; 0014 and 0015 stay reserved. ADR 0016's status paragraph is lines 3-5 (up to the `Supersedes:` line). The sha256 of 0016 with that paragraph removed is `f927c6309f7782cb0b9d853206e5c3f1ec5d036e5d64b48960de2eea5eb4c3ed`, computed with the same split logic as the existing `_status_split` in `tests/test_public_read_decision.py`. Use it to pin "only the status line changed".
- Existing tests pin public-read wording and must be rewritten, not merely deleted:
  - `tests/test_infra.py`: `_assert_public_read`, the prefix mutations, the access-block test (expects false/false), the policy-document test, the bucket-policy test, the CORS test, the description test (needs "ADR 0016"), the infra-README tests (section "Applying public read", an Origin header curl, 200 and `Access-Control-Allow-Origin: *`).
  - `tests/test_readme.py`: the anonymous `PROVIDER config` block test, `test_readme_records_public_read_since_the_2026_11_16_apply`, the STAC row test (needs "readable anonymously over https", "cors"), and the Limitations test (pins "no agent has run it (the weekly", "Update 2026-11-16", "ebea401", "test_live_anonymous_read.py` passed"). The test pinning the "Attribution backfill" section (ADR 0016 gate) stays as is, and that README section is historical and is not edited.
  - `tests/test_workflows.py` lines ~1066-1106: the verify.yml header test (forbids "private" and "xfail"), the `[catalogue]` comment test (needs "2026-11-16" or "adr 0016"), and `test_anonymous_live_test_is_not_marked_xfail`.
  - `tests/test_public_read_decision.py`: the whole file pins ADR 0016's public content.
- `verify.yml` runs `pytest -m live` before assuming AWS credentials, so the new unsigned-request test runs credential-free. With `xfail(strict=True)` it is XFAIL while the bucket is still public and XPASS-strict (a failure) after the apply, until the follow-up story removes the marker. That is intended.
- `tests/aws_support.configured_bucket()` skips on the `.invalid` placeholder. `tests/test_live_credentialed_read.py` stays untouched.
- The verify.yml header does not currently say the bucket is public (its "public COGs" refers to Earth Search). The plan adds an accurate sentence about the 0017 expectation, and the test then pins it.
- Judgement call: the story says `bucket_url` stays "exactly as it is" but also lists `infra/outputs.tf` for change. Plan: keep the output name and value byte-identical and edit only its `description` text, which currently states that anonymous read takes effect at the ADR 0016 apply. A description is metadata, so it does not alter the tofu plan (still 0 to add, 1 to change, 2 to destroy). The `bucket_name` variable description gets the same treatment.
- Guardrail on `terraform fmt -check` (an acceptance criterion): implementers must not run `terraform` or `tofu` at all. The HCL change is pure deletion plus `true` flips and comments, so keep the existing indentation and alignment by hand. The orchestrator runs `terraform -chdir=infra fmt -check` afterwards, since it is offline and touches no AWS resource.

## Shared constants

- ADR file: `docs/decisions/0017-private-output-bucket-again.md`, title `# 0017 Private output bucket again`.
- Jarrod's quote, verbatim, dated 2026-11-17: `just make it password protected so its not public - im not contacting dbca`.
- Expected plan: 0 to add, 1 to change, 2 to destroy: `aws_s3_bucket_public_access_block.outputs` updated (`block_public_policy` and `restrict_public_buckets` false to true), `aws_s3_bucket_policy.public_read` and `aws_s3_bucket_cors_configuration.outputs` destroyed.

## Steps (one batch; the four tasks touch disjoint files and share only the constants above)

1. Infra plus offline infra tests (task A): `infra/main.tf`, `infra/variables.tf`, `infra/outputs.tf`, `infra/README.md`, `tests/test_infra.py`.
   - main.tf: all four access-block settings true, comment updated. Remove the `public_read` policy document, the bucket policy and the CORS resource. Nothing else changes.
   - `_assert_private(main_text)` helper in test_infra.py asserts:
     - all four settings are true;
     - there is no `aws_s3_bucket_policy`, no `aws_s3_bucket_cors_configuration` and no `public_read`;
     - the policy documents are exactly `pipeline_access` and `pipeline_trust`;
     - every principals block is `Federated`;
     - there is no `"*"` identifier or principal type;
     - no ACL resource.
   - It is used by the real test and by parametrised mutation tests (flip each flag to false, append a bucket policy, append a `*` principal statement, append a CORS resource), each of which must raise AssertionError. That proves AC 4.
   - Keep the trust, pipeline-access, lifecycle, OIDC, outputs and variable-validation tests unchanged.
   - Descriptions test: the `bucket_name` and `bucket_url` descriptions mention ADR 0017, AWS credentials and the pending apply.
   - infra/README.md: rewrite the first "What the module creates" bullet as private. Replace "Applying public read" with "Applying the private configuration", containing:
     - the plan and apply commands;
     - the expected plan;
     - a do-not-apply-if-anything-else-changes rule;
     - an unsigned header-only `curl -sS -I "$(terraform -chdir=infra output -raw bucket_url)/stac/catalog.json" | grep -i -E '^HTTP/'` expecting a 403 status line (before the apply it prints 200);
     - a note that the follow-up story removes the xfail marker from `tests/test_live_anonymous_read.py`;
     - a "Sharing one object" subsection documenting `aws s3 presign` (a presigned URL expires with the signing credentials; this is documented, not built).
     Rewrite the Notes bullet on anonymous access. Add a test that the section exists, orders plan < apply < check, names the three resources and counts, and that "Applying public read" is absent.
   - Proves: the private configuration is enforced offline, and any public regression fails.

2. ADR plus decision test (task B): create `docs/decisions/0017-private-output-bucket-again.md`, edit only the status paragraph of `docs/decisions/0016-public-read-output-bucket.md`, and rewrite `tests/test_public_read_decision.py`.
   - Sections of 0017: Status/Supersedes, Context, Decision-making (quote and date, and the reading of "password protected" as IAM credentials because S3 has no password mode), Decision, DBCA confirmation no longer sought (st-4c87, 0016 precondition 3), Exposure window, Effect on the design (criteria 2 and 3 for credentialed readers only; spike 6 and the anonymous half of spike 7 shelved under st-9f02), Reader access, Expected plan, Evidence, `## Apply` (pending).
   - The test checks:
     - the supersession line;
     - the verbatim quote and date;
     - the Apply section says pending and does not claim completion;
     - the 0016 status line names 0017;
     - the 0016 rest-of-file sha256 is unchanged;
     - ADR 0011 stays unchanged (keep the two existing 0011 tests).
   - Proves: the record exists and says what the story requires, and 0016 changed only on its status line.

3. Live test, workflow and config comments (task C): `tests/test_live_anonymous_read.py` (replaced), `tests/test_workflows.py`, `config/pipeline.toml`, `.github/workflows/verify.yml`.
   - The live module has `pytestmark = [pytest.mark.live, pytest.mark.xfail(strict=True, reason=...)]` and the reason names the pending ADR 0017 apply. It has two tests using `configured_bucket()`, sending unsigned `urllib` requests and reading status codes only (never `.read()` a body): GET `/stac/catalog.json` is 403, and GET `/?list-type=2&prefix=observations/&max-keys=1` is 403.
   - test_workflows replaces the three public-wording tests:
     - the verify.yml header must mention ADR 0017 and must not say the bucket is publicly or anonymously readable;
     - the `[catalogue]` comment must mention ADR 0017 and credentials and must not say anonymous or public readable or "resolve without credentials";
     - an AST-based test that the anonymous live test carries `xfail(strict=True)` with "0017" in its reason and asserts 403 for the two requests.
   - Proves: AC 5, AC 10.

4. README and README tests (task D): `README.md`, `tests/test_readme.py`.
   - README changes:
     - Verification matrix STAC row: ADR 0017, credentials, spike 6 shelved, and still "No live STAC check is implemented".
     - "Querying with DuckDB" (~lines 391-480): drop the anonymous `PROVIDER config` block and its prose, keep the `credential_chain` block and the aws-login and expiry prose, add a presigned-URL paragraph, and make the changes/ sentence credentialed.
     - "Deployment" (~478-493): private 2026-11-06, public 2026-11-16, ADR 0017 directs private again on 2026-11-17, apply pending.
     - "Limitations" (~640-657 and ~702-705): rewrite the STAC bullet, the public-read bullet (exposure window, copies cannot be withdrawn, apply pending), the live-test bullet, and the spike paragraph.
     - Leave "Attribution backfill" alone.
   - test_readme changes:
     - Delete the anonymous-block test.
     - Add a test that README has no `provider config` or `anonymous_outputs`.
     - Replace the 2026-11-16 record test with an ADR 0017 record test (DuckDB prose has "0017", "credential", "presigned"; Deployment and Limitations name 0017 and 2026-11-17).
     - Add a sentence-level public-claim detector (`_claims_public_read`) with regexes for `(publicly|anonymously) readable`, `readable (publicly|anonymously)` and `public-read bucket`. Test it on positive and negative sample sentences, then assert no README sentence matches. Keep the existing banned-phrase test.
     - Rewrite the STAC row test and the Limitations live-test test (pin "Update 2026-11-16", "ebea401", "xfail" and "0017" instead).
   - Proves: AC 8.

5. Orchestrator after the batch (not an implementer task): run the four verification commands in AGENTS.md order, and `terraform -chdir=infra fmt -check`. Confirm `git diff main -- infra/` touches only the intended resources (AC 3). Confirm `LEARNINGS.md`, `docs/handoffs/*`, `docs/research/*` and ADR 0011 are unchanged, and that `git diff` of ADR 0016 shows only the status paragraph.
