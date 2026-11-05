---
id: st-4fa1
title: Add bucket lifecycle and object content types
type: chore
epic: st-f849
priority: P3
depends_on: []
touches: [infra/README.md, infra/main.tf, src/wetland_change/stac/catalogue.py, src/wetland_change/store.py, tests/test_catalogue.py, tests/test_infra.py, tests/test_pipeline.py, tests/test_store.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-05
---

## Description

The bucket has no lifecycle rule to abort incomplete multipart uploads, every object is uploaded as application/octet-stream including the STAC JSON, and directory markers are PUT again on every write (src/wetland_change/store.py:29-31). Verdict CONFIRMED. Evidence: docs/research/2026-11-04-milestone-2-review.md L6.

## Acceptance Criteria

- [ ] infra adds a lifecycle rule that aborts incomplete multipart uploads after one day
- [ ] JSON and parquet objects are written with their media types

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-4fa1)

- `infra/main.tf` has the bucket, no lifecycle resource. `infra/versions.tf` pins aws provider ~> 5.0, so the separate `aws_s3_bucket_lifecycle_configuration` resource applies (the in-bucket `lifecycle_rule` is deprecated).
- `src/wetland_change/store.py:27-32` `OutputStore.write_bytes` calls `self.fs.open_output_stream(full)` with no metadata, so S3 stores `application/octet-stream`. pyarrow is 26.0.0; `open_output_stream(path, compression='detect', buffer_size=None, metadata=None)` supports `metadata={"Content-Type": ...}` on S3, and LocalFileSystem accepts and ignores it (checked: writes bytes unchanged).
- Every caller (ledger, manifest, geoparquet, changes, verify/checks, stac/catalogue) goes through `write_bytes`, so one change in store.py covers all of them. Written extensions are `.json` and `.parquet` only. `stac/catalogue.py` already defines `PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"` but imports `store`, so store.py must define its own mapping (no import from stac, to avoid a cycle).
- The directory-marker PUT (store.py:29 `create_dir`) is mentioned in the story description but is not in the acceptance criteria. Leave it alone; do not change `create_dir` behaviour.
- No terraform/AWS calls: tests are offline text checks (`tests/test_infra.py` style). Do not run terraform plan/apply/init/validate. `terraform fmt -check` on `infra/` is purely local and is allowed (terraform is at /opt/homebrew/bin/terraform).

## Steps

1. RED, infra: add to `tests/test_infra.py` a test `test_lifecycle_aborts_incomplete_multipart_uploads_after_one_day` that reads `infra/main.tf`, takes the block `resource "aws_s3_bucket_lifecycle_configuration" "outputs"`, and asserts: `bucket = aws_s3_bucket.outputs.id`; exactly one `rule` block; it has `status = "Enabled"`; an `abort_incomplete_multipart_upload` block with `days_after_initiation = 1`; and no `expiration`/`transition` blocks (the rule must not delete or move data). Proves the lifecycle rule exists, is enabled, targets the outputs bucket, aborts at 1 day, and cannot expire real objects. Run it; it fails (block not found).
2. GREEN, infra: in `infra/main.tf` after the CORS resource add `aws_s3_bucket_lifecycle_configuration.outputs` with a single rule `id = "abort-incomplete-multipart-uploads"`, `status = "Enabled"`, an empty `filter {}` (whole bucket), and `abort_incomplete_multipart_upload { days_after_initiation = 1 }`, with a short comment explaining killed writes leave billed parts. Run `terraform -chdir=infra fmt -check -recursive` (local only) and the new test.
3. Docs, infra: add one sentence to the "What the module creates" bucket bullet in `infra/README.md` stating that a lifecycle rule aborts incomplete multipart uploads after one day, and that the pipeline role needs no `s3:AbortMultipartUpload` because S3 applies the rule itself. Extend the lifecycle test (or add a small one) asserting the README mentions "multipart". Keep wording factual, no em dashes.
4. RED, content types: in `tests/test_store.py` add tests using a recording wrapper. Define a tiny helper class in the test that wraps `store.fs` (delegating `create_dir`, `open_output_stream`, etc. via `__getattr__`) and records the `metadata` argument passed to `open_output_stream`, then assign it as `store.fs`. Tests: (a) `test_write_bytes_sets_json_content_type`: `write_bytes("runs/r.json", b"{}")` records `{"Content-Type": "application/json"}`; (b) `test_write_bytes_sets_parquet_content_type`: `observations/x.parquet` records `{"Content-Type": "application/vnd.apache.parquet"}`; (c) uppercase/odd suffix check not required, but an unknown extension (`z.txt`) records no Content-Type (metadata None), so unknown types keep S3 default; (d) existing local round trip still passes (bytes unchanged on LocalFileSystem). Proves the media type is chosen from the key suffix and handed to the filesystem on every write. Run; (a) and (b) fail.
5. GREEN, content types: in `src/wetland_change/store.py` add a module constant `CONTENT_TYPES: Final[dict[str, str]] = {".json": "application/json", ".parquet": "application/vnd.apache.parquet"}` and a helper `_content_type(relpath) -> str | None` that looks up `PurePosixPath(relpath).suffix.lower()`. In `write_bytes`, pass `metadata={"Content-Type": ct}` to `open_output_stream` when `ct` is not None, else call without metadata (`metadata=None`). Do not change `create_dir`, return value, or other methods. Run test_store and the full suite.
6. Full verification, in order, one command per line, judge pytest by exit code, never clear addopts, no live tests: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts` (run `uv run ruff format` on the touched files if it complains), `uv run mypy src scripts`, `uv run pytest -q`. Do not commit; do not edit `stories/**`.
## Orchestrator amendments

- STAC Items are GeoJSON Features, and the catalogue's own item links declare `application/geo+json`, so `write_catalogue` stores Items with that type. `write_bytes` gains a keyword `content_type: str | None = None` that overrides the suffix lookup. Catalogs, Collections and the write index stay `application/json`. This extends the touched files to `src/wetland_change/stac/catalogue.py`, `tests/test_catalogue.py` and the test fakes that override `write_bytes`.
- `PARQUET_MEDIA_TYPE` in catalogue.py is derived from store.py's mapping so there is one source for the value.
- A recording wrapper proves only that the argument reaches the filesystem. A test against a stub S3 server on 127.0.0.1 proves the Content-Type header is on the request that creates the object. No AWS call and no new dependency.
- The directory marker PUT named in the description is not in the acceptance criteria and stays out of scope. It is filed as its own story.
- Never run terraform plan or apply, and never call AWS (epic st-f849).

## Implementation Notes

- 2026-11-05T15:12:43.934Z: Build-flow done, batch reviewed clean. Gates exit 0 before commit: ruff check, ruff format, mypy, pytest, pytest with GITHUB_ACTIONS=true, terraform fmt. Nothing is applied: the lifecycle rule takes effect only when Jarrod applies the module, and epic st-f849 forbids plan and apply here. Objects already in the bucket keep application/octet-stream until rewritten. Content-Type on the wire is checked against a local stub, not real S3. The stub test uses fake credentials because pyarrow rejects anonymous=true in an S3 URI. Directory markers filed as st-2cc2.

## Questions
