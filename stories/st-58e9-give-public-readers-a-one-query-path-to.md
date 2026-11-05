---
id: st-58e9
title: Give public readers a one-query path to the observations
type: bug
epic: st-f849
priority: P2
depends_on: []
touches: [infra/main.tf, README.md, tests/test_infra.py, tests/test_geoparquet.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

A DuckDB glob over the bucket has to list it, but the public policy grants only s3:GetObject (infra/main.tf:29) and tests/test_infra.py forbids s3:ListBucket, so success criterion 3 cannot be met anonymously. The S3 variant of the query in README.md needs credentials for the same reason. The GDAL cross-reader test also skips everywhere because the pyogrio wheel has no Parquet driver. Verdict PLAUSIBLE: not tested against S3. Evidence: docs/research/2026-11-04-milestone-2-review.md L2.

## Acceptance Criteria

- [ ] A documented DuckDB query reads every observation file from the public bucket without credentials
- [ ] The GeoParquet cross-reader check runs in CI with a reader that is installed

## Implementation Plan

## Implementation Notes

## Questions
