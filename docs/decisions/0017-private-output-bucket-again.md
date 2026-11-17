# 0017 Private output bucket again

Status: accepted, 2026-11-17, on Jarrod's direction; the apply is pending (see
Apply).
Supersedes: 0016 (`docs/decisions/0016-public-read-output-bucket.md`).

## Context

ADR 0016 (2026-11-15) made the output bucket publicly readable, and the apply
of 2026-11-16 put that in effect. The module grants anonymous `s3:GetObject` on
every object, anonymous `s3:ListBucket` under `observations/`, and CORS GET and
HEAD from any origin. The public access block has `block_public_policy` and
`restrict_public_buckets` set to false.

## Decision-making

On 2026-11-17 Jarrod directed, in these words:

> just make it password protected so its not public - im not contacting dbca

S3 has no password mode. The orchestrator read the direction as: the bucket is
readable only with AWS credentials (IAM), as under ADR 0011
(`docs/decisions/0011-private-output-bucket.md`). Sharing one object with
someone who has no AWS access is by presigned URL (see Reader access). The
orchestrator recorded the decision.

## Decision

The module returns to the 0011 private configuration. All four public access
block settings are true. The `public_read` policy document,
`aws_s3_bucket_policy.public_read` and
`aws_s3_bucket_cors_configuration.outputs` are removed. No principal `*`
appears in the module.

Unchanged: the pipeline role with OIDC trust on main, `s3:ListBucket` on the
bucket, Get, Put and Delete on objects, the ownership controls, the lifecycle
rule, and the outputs `role_arn` and `bucket_url`. `catalogue.base_url` is
unchanged; its links need credentials once the apply has run.

Out of scope: licence and attribution text inside published files, the
`redistribute_public` column of `data/SOURCES.md`, the GitHub repository's
visibility, and `src/wetland_change/raster/env.py` (anonymous reads of
third-party Earth Search COGs).

## DBCA confirmation

Written confirmation from DBCA was precondition 3 of the 0016 apply. Jarrod
waived it on 2026-11-15 and it was parked as story st-4c87. It is no longer
sought, because nothing is publicly redistributed once the bucket is private.
Story st-4c87 is superseded by this decision.

## Exposure window

From the 2026-11-16 apply until the 0017 apply, every object in the bucket was
anonymously readable by key, and anonymous listing was possible under
`observations/`. Anonymous requests were billed to the bucket owner. Copies
taken in that window cannot be withdrawn.

## Effect on the design

- Design success criteria 2 and 3 apply to credentialed readers only.
- Shelved: spike 6 and the anonymous half of spike 7 (story st-9f02).
- stac-browser on GitHub Pages cannot read a private bucket and is not used.
  The catalogue still validates offline.

## Reader access

Readers use AWS credentials. DuckDB reads through its `credential_chain`
secret (README 'Querying with DuckDB'). For one-off sharing with someone who
has no AWS access, issue a presigned URL, for example with `aws s3 presign`.
A presigned URL expires with the signing credentials. Presigned URLs are
documented in `infra/README.md` and not built. Reader IAM is granted outside
the module.

## Expected plan

0 to add, 1 to change, 2 to destroy:

- `aws_s3_bucket_public_access_block.outputs` is updated in place, with
  `block_public_policy` and `restrict_public_buckets` changing from false to
  true.
- `aws_s3_bucket_policy.public_read` is destroyed.
- `aws_s3_bucket_cors_configuration.outputs` is destroyed.

Nothing else changes. Do not apply if the plan changes the role, its
policies, the ownership controls, the lifecycle rule or the OIDC provider.

## Evidence

- `tests/test_infra.py` asserts the private configuration and fails on a
  public grant, a `*` principal, a bucket policy or CORS.
- `tests/test_live_anonymous_read.py` is live and `xfail(strict=True)` until
  the apply. After the apply it asserts that an unsigned GET of
  `stac/catalog.json` and an unsigned ListObjectsV2 under `observations/` both
  return 403.
- `tests/test_public_read_decision.py` checks this record and the 0016 status
  paragraph.

## Apply

The apply is pending. It has not been run. The operator runs it, or the
orchestrator runs it on Jarrod's go-ahead, never an agent on its own. No agent
runs tofu, terraform or aws against the bucket.

A follow-up story records the apply: the plan, the result, and the unsigned
header check expecting 403. It also removes the `xfail` marker from
`tests/test_live_anonymous_read.py` and updates the statements that hold only
until then. The st-b6bf and st-dd0d blindness rules in `LEARNINGS.md` stay in
force.
