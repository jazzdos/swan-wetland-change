# 0011 Private output bucket

Status: accepted, 2026-11-06, on Jarrod's direction; superseded by 0016
(`docs/decisions/0016-public-read-output-bucket.md`) on 2026-11-15.
Supersedes: the design's public-read bucket and stac-browser on GitHub Pages
(`docs/plans/2026-10-29-swan-wetland-change-design.md`), and the anonymous
listing of `observations/` added by st-58e9.

## Context

The design (`docs/plans/2026-10-29-swan-wetland-change-design.md`) put outputs
and the STAC catalogue in a public-read S3 bucket with CORS, so that
stac-browser on GitHub Pages and anonymous DuckDB could read them.
`infra/main.tf` implemented that: anonymous `s3:GetObject` on every object,
anonymous `s3:ListBucket` under `observations/` (st-58e9), CORS GET and HEAD
from any origin, and a public access block with `block_public_policy` and
`restrict_public_buckets` set to false.

Nothing has been applied and no bucket exists. On 2026-11-06 Jarrod directed
that everything stays private until he has reviewed it, and that he will
consider public access later. The GitHub repository was made private the same
day under the same direction. That change is outside this decision.

Two design spikes depend on the public bucket. Spike 6 (a hand-written
catalogue on a public bucket with CORS, opened in stac-browser) no longer
applies while the bucket is private. Spike 7 (DuckDB reads the observations
from S3 with one glob) now means a credentialed reader.

## Decision-making

Jarrod directed this decision. The orchestrator recorded it.

## Decision

The module creates a private bucket. All four public access block settings are
true. The `public_read` policy document and the bucket policy are removed, and
the CORS configuration is removed. No principal `*` appears in the module.

The pipeline role is unchanged: OIDC trust on main, `s3:ListBucket` on the
bucket, and Get, Put and Delete on objects. The lifecycle rule and the outputs
`role_arn` and `bucket_url` are unchanged.

Readers use AWS credentials: DuckDB through a `credential_chain` secret
(README 'Querying with DuckDB'), and the STAC catalogue through signed requests
or a local copy. Reader IAM is granted outside this module.
`src/wetland_change/raster/env.py` concerns anonymous reads of third-party
Earth Search COGs and is unaffected.

## Effect on the design

- Success criterion 2 (the catalogue opens in stac-browser and validates) and
  criterion 3 (DuckDB reads the observations from S3 with one query) now apply
  to credentialed readers.
- The catalogue still validates offline. stac-browser on GitHub Pages cannot
  read a private bucket and is not used.
- Spikes 6 and 7 must be run with credentials, subject to the Context above.
- The ledger-compaction comment 'public and unversioned' becomes
  'unversioned'.

## Supersedes

- The design's public-read bucket and CORS for stac-browser on GitHub Pages.
- st-58e9's anonymous `s3:ListBucket` on `observations/` and the README's
  anonymous DuckDB secret (PROVIDER config).

## Reopening public access

In order:

1. Jarrod reviews the outputs and approves public access in a new ADR that
   supersedes this one.
2. Check licences in `data/SOURCES.md`. Every dataset must have
   `redistribute_public` true (Ramsar DBCA-010 is CC BY-SA 4.0, DEA Waterbodies
   is CC BY 4.0), and the attribution and ShareAlike terms must be met in the
   published files.
3. Infra: set `block_public_policy` and `restrict_public_buckets` to false
   (keep `block_public_acls` and `ignore_public_acls` true). Add a bucket
   policy granting anonymous `s3:GetObject` on objects and, if anonymous
   globbing is wanted, `s3:ListBucket` with an `s3:prefix` condition limited to
   `observations/`. Add `depends_on` the access block. Add a CORS rule for GET
   and HEAD if a browser viewer such as stac-browser is wanted.
4. Tests: replace the private-configuration assertions in
   `tests/test_infra.py` and the `credential_chain` README test in
   `tests/test_readme.py`, and restore an anonymous live test in place of
   `tests/test_live_private_outputs.py`.
5. Docs: update `README.md`, `infra/README.md` and the `infra/variables.tf`
   description.
6. Apply is run by the operator, never by an agent, and the plan is reviewed
   first.
7. Cost: anonymous requests are billed to the bucket owner.

## Consequences

- No resource has been created, so no data or URL changes.
- The repository is private, so GitHub Pages hosting of stac-browser is not
  available anyway.
- Reviewers without AWS credentials cannot read the bucket.
- `catalogue.base_url` still needs the `bucket_url` output after apply, but
  those https links need signed access.

## Evidence

`tests/test_infra.py` asserts the private configuration and fails if a public
grant, a public-policy allowance or a CORS rule is reintroduced.
`tests/test_live_private_outputs.py` (live, not run in the default suite)
checks that an anonymous GET of an existing object, an anonymous listing and an
anonymous DuckDB read are all denied, and that a credentialed DuckDB reader can
glob `observations/`. The existing object comes from the credentialed glob when
credentials are available, otherwise `stac/write-index.json`; a missing key is
not used because S3 answers 403 for it whether or not GetObject is public.
