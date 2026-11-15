# 0016 Public read on the output bucket

Status: accepted, 2026-11-15; public access approved by Jarrod on 2026-11-14.
Takes effect at the operator's apply of `infra/`; until then the bucket stays
private.
Supersedes: 0011 (`docs/decisions/0011-private-output-bucket.md`).

## Context

ADR 0011 (2026-11-06) made the output bucket private until Jarrod had reviewed
the outputs, and listed the steps for reopening public access. The bucket has
existed since the 2026-11-06 apply (`docs/handoffs/2026-11-06-milestone-2.md`)
with all four public access block settings on, no bucket policy and no CORS
rule. The pipeline writes to it through its OIDC role.

Spike 6 (the catalogue opened in stac-browser) and the anonymous half of spike
7 (DuckDB reading the observations from S3 with one glob and no credentials)
are blocked while the bucket is private (README "Limitations", `LEARNINGS.md`).

This record carries out steps 1, 3, 4 and 5 of 0011's "Reopening public
access" (story st-1a5f). Step 2 is st-1a9c, summarised under Licences. Step 6,
the apply, is the operator's. Step 7, the cost note, is kept under Cost.

## Decision-making

On 2026-11-14 the orchestrator told Jarrod that the outputs review was the
decision that unblocked spike 6 and the anonymous read test, and Jarrod replied
"approved". The orchestrator then stated its reading with the proposed
stories: he has reviewed the outputs and approves public access, this ADR
records that as his decision, and the apply and the DBCA-010 licence
confirmation stay his. Jarrod approved that set. The decision is Jarrod's; the
orchestrator recorded it.

## Licences

Step 2 of 0011 is story st-1a9c. Its note is
[`docs/research/2026-11-14-public-release-licences.md`](../research/2026-11-14-public-release-licences.md),
with an "Update 2026-11-15" section.

- Three claim-verifiers confirmed DBCA-010 as CC BY-SA 4.0 in 0 of 3. The
  custodian's catalogue entry states CC BY-NC 4.0, and the SLIP service terms
  require the custodian's prior written permission.
- On 2026-11-15 Jarrod replied "stories work. approved recommended that
  unblock stories", and the orchestrator's recommendation was recorded as
  approved: DBCA-010 and the files that carry its polygons, site names and
  object ids are published under CC BY-NC 4.0, non-commercial use only. That
  is the project's adopted reading, not a confirmation from DBCA.
- Every `data/SOURCES.md` row the note covers has `redistribute_public` true.
- T1 (DEA CC BY 4.0 attribution, st-8856) and T2 (the Copernicus Sentinel data
  notice, st-d5c1) are met in the writers. Objects already in the output store
  carry T1 and T2 after the backfill workflow ran on 2026-11-15 (run
  43677125903, all jobs succeeded; only its summary counts were read).
- T3 (the DBCA-010 CC BY-NC 4.0 attribution and licence notice, and the STAC
  collection `license` field) is st-22f1, which is not yet done. Objects
  written before st-22f1 carry T3 only after its backfill job runs.
- T4 (ShareAlike) is n/a: CC BY-NC 4.0 has no ShareAlike term.

The note lists T3 and the objects already in the store as blocking 0011 step
3. This record writes step 3's configuration but applies nothing, and an
unapplied change publishes nothing, so those items become preconditions of
the apply below.

## Decision

The module in `infra/` grants anonymous read:

- Public access block: `block_public_acls` and `ignore_public_acls` stay true,
  so no ACL can make anything public. `block_public_policy` and
  `restrict_public_buckets` are false, so the bucket policy can be public.
- Bucket policy `aws_s3_bucket_policy.public_read`, built from the
  `public_read` policy document, with `depends_on` the access block. Statement
  `PublicReadObjects` grants principal `*` `s3:GetObject` on every object.
  Statement `PublicListObservationPrefix` grants principal `*`
  `s3:ListBucket` on the bucket only when `s3:prefix` matches
  `observations/*` (StringLike), so DuckDB can glob the observation files.
  Listing the bucket root or any other prefix (`changes/`, `ledger/`, `runs/`,
  `stac/`, `verification/`) is denied; those objects stay readable by key.
  There is no public put or delete.
- CORS: one rule allowing GET and HEAD from any origin, so a browser viewer
  such as stac-browser can read the STAC catalogue.

Unchanged: the pipeline role (OIDC trust on `main`, `s3:ListBucket` on the
bucket, Get, Put and Delete on objects), the ownership controls, the lifecycle
rule and the outputs `role_arn` and `bucket_url`.

Readers: after the apply, DuckDB reads the observations with an anonymous
secret (README "Querying with DuckDB") and the STAC catalogue is read over
https. Until the apply, readers use AWS credentials as under 0011.

The GitHub repository's visibility is outside this decision.

## Preconditions of the apply

The apply is run by the operator, never by an agent, after the plan is
reviewed. No agent runs `tofu plan`, `tofu apply` or `terraform` against AWS,
or reads `infra/terraform.tfstate`. Before the apply, in order:

1. st-22f1 is merged to `main`.
2. st-22f1's backfill job has run against the output store.
3. Recommended, and Jarrod's decision: DBCA's written confirmation that CC
   BY-NC 4.0 applies to public redistribution of DBCA-010 and of products
   derived from it (the note's residual risk).
4. The operator runs the plan, reviews it and then applies
   (`infra/README.md`, "Applying public read").

After the apply the operator runs the header-only check in `infra/README.md`.
The commit that records the apply removes the `xfail` marker from
`tests/test_live_anonymous_read.py` and updates the statements that hold only
while the bucket is private: the STAC catalogue row of the README verification
matrix, the `[catalogue]` comment in `config/pipeline.toml` and the header
comment of `.github/workflows/verify.yml`.

## Cost

Anonymous requests are billed to the bucket owner: the request charges for
every anonymous GET, HEAD and LIST, and data transfer out of AWS. Nothing in
the module caps them.

## Effect on the design

- Success criteria 2 (the catalogue opens in stac-browser and validates) and
  3 (DuckDB reads the observations from S3 with one query) apply to anonymous
  readers again from the apply.
- Spike 6 and the anonymous half of spike 7 can run after the apply. Agents do
  not read observations until the st-b6bf and st-dd0d decision files are
  committed (`LEARNINGS.md`).

## Consequences

- Before the apply nothing changes in AWS: the bucket stays private, and the
  README says readers need credentials until the operator's apply.
- After the apply every object in the bucket is readable by anyone who knows
  its key, including the ledger, run manifests and verification reports.
  Nothing private may be written to the bucket.
- `catalogue.base_url` links resolve without credentials after the apply.
- The weekly `verify.yml` run executes `pytest -m live` from GitHub `main`
  with no AWS credentials. The anonymous test is marked `xfail(strict=True)`
  until the apply, so that run stays green while the bucket is private. After
  the apply the test passes, which fails the run as an unexpected pass until
  the marker is removed.
- `tests/test_live_private_outputs.py` is removed. Its credentialed test moves
  unchanged to `tests/test_live_credentialed_read.py`, because readers need
  credentials until the apply.

## Evidence

`tests/test_infra.py` asserts the access block settings, the two public
statements, the `s3:prefix` condition (and fails on copies of the policy whose
list statement has lost it), `depends_on` the access block and the CORS rule.
`tests/test_public_read_decision.py` checks this record and the status line
of 0011. `tests/test_live_anonymous_read.py` (live, not run by st-1a5f) checks
an anonymous GET of `stac/catalog.json` with its `Access-Control-Allow-Origin`
header, an anonymous listing under `observations/`, denied listings of the
bucket root and of `ledger/`, and an anonymous DuckDB read with one glob.
