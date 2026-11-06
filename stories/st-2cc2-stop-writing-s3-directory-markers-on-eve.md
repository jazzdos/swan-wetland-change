---
id: st-2cc2
title: Stop writing S3 directory markers on every write
type: bug
priority: P2
depends_on: [st-4fa1]
discovered_from: st-4fa1
touches: [src/wetland_change/store.py, tests/test_store.py]
exclusive: false
created: 2026-11-05
updated: 2026-11-06
---

## Description

OutputStore.write_bytes calls create_dir on the parent of every key (src/wetland_change/store.py:29), which review finding L6 confirmed puts directory marker objects again on each write. S3 has no directories, so these are extra requests and extra objects in a public bucket. The description of st-4fa1 names this but its acceptance criteria do not, so it is out of scope there. Evidence: docs/research/2026-11-04-milestone-2-review.md L6.

## Acceptance Criteria

- [ ] Writing to an S3 root sends no request that creates a key ending in a slash
- [ ] checked against a stub S3 server on 127.0.0.1
- [ ] Writing to a local root still creates missing parent directories

## Implementation Plan

# st-2cc2 plan: stop writing S3 directory markers on write

## Findings (verified in the worktree, pyarrow 26.0.0)

- The `create_dir` call is at `src/wetland_change/store.py:44` in `OutputStore.write_bytes`. Nothing else in `src` or `scripts` touches `create_dir` or `.fs`.
- Probed against the existing stub, an S3 `write_bytes("runs/a/r.json", ...)` with root `s3://stub-bucket/prefix` sends `PUT /stub-bucket/prefix/`, `PUT /stub-bucket/prefix/runs/` and `PUT /stub-bucket/prefix/runs/a/`, all with Content-Type `application/x-directory`. Those are the marker objects.
- With the `create_dir` call removed, the same write sends only the multipart sequence for `prefix/runs/a/r.json`: `POST ?uploads`, `PUT ?partNumber=1&uploadId=...`, `POST ?uploadId=...`. `open_output_stream` on S3 creates no marker, so no S3FileSystem option is needed.
- `check_directory_existence_before_creation` is not accepted as an S3 URI query parameter in 26.0.0 (`ArrowInvalid: Unexpected query parameter`), so it is not an option via `from_uri`. It would not help anyway because the markers come from `create_dir` itself.
- Delete behaviour (out of scope for the AC, report only): `fs.delete_file` on S3 sends `DELETE <key>` and then `PUT <parent>/` with `application/x-directory`, so pyarrow re-creates the immediate parent marker after every delete. No S3FileSystem option stops this. Fixing it would need either a different delete path (for example a boto3 client or `delete_files`, to be checked) or removing the marker afterwards. Do not change `delete` in this story; add a short comment on `OutputStore.delete` recording the behaviour and recommend a follow-up story.
- Pitfall: `tests/test_store.py::_recorded` replaces `store.fs` with a `_Recorder` wrapper after construction. An `isinstance(self.fs, LocalFileSystem)` check at write time would see the wrapper and skip `create_dir`, so local writes through the wrapper would fail. Decide once in `__init__`, before any wrapping.

## Steps

1. Test first, `tests/test_store.py` (stub extension)
   - In `_StubS3`, add `self.calls: list[tuple[str, str]] = []` holding `(method, key)` for every request. In `_StubS3Handler._handle`, compute `key = urlsplit(self.path).path.removeprefix("/stub-bucket")` (keep the leading `/` and any trailing `/`, do not strip) and append `(self.command, key)`. Leave the existing `requests` tuples and the existing content-type test untouched.
   - Note that the handler's local `key` used for HEAD logic strips slashes; use a different variable name for the recorded value.
2. New test `test_s3_write_creates_no_directory_marker_keys` (RED before the fix)
   - Reuse the env setup and store construction from `test_s3_write_sends_the_content_type_header` (consider a small helper `_s3_store(stub_s3, monkeypatch)` shared by both tests; keep the existing test behaviour identical).
   - Write `runs/a/r.json` and `z.json` (a nested key and a top-level key).
   - Assert no recorded call with method PUT or POST has a key ending in `/`. Prove: the AC "sends no request that creates a key ending in a slash".
   - Assert the expected object creations were recorded (a `POST` with key `/prefix/runs/a/r.json` and a `POST` with `/prefix/z.json`, from `uploads` multipart initiation, found via `stub_s3.requests` paths). Prove: the test is not vacuous and the writes still reach the stub.
   - Confirm it fails on current code listing `/prefix/`, `/prefix/runs/`, `/prefix/runs/a/`.
3. New test `test_local_write_creates_missing_parent_directories`
   - `OutputStore(str(tmp_path / "out"))`, write `a/b/c/d.txt`, assert `(tmp_path/"out"/"a"/"b"/"c"/"d.txt").read_bytes()` matches and the parent directories exist. Also write a second key into the same existing parent to show it is not an error. Prove: AC "local root still creates missing parent directories". Existing `_recorded` based tests also cover this through the wrapper (they write into `runs/` which does not exist yet).
4. Fix, `src/wetland_change/store.py`
   - In `__init__`, after `from_uri`, set `self._creates_parents = isinstance(self.fs, pafs.LocalFileSystem)` (annotate as `bool`).
   - In `write_bytes`, wrap the `create_dir` call in `if self._creates_parents:`.
   - Add a brief comment: object stores have no directories, so only the local filesystem needs parents created; on S3 `create_dir` PUTs `x-directory` marker keys.
   - Update the module docstring with one flat sentence stating the same. No em dashes.
   - Add a short comment/docstring line on `delete` noting that pyarrow's S3 `delete_file` re-creates the parent marker (not addressed here).
5. Run gates, one per line, judged by exit code
   - `uv run ruff check src tests scripts`
   - `uv run ruff format --check src tests scripts`
   - `uv run mypy src scripts`
   - `uv run pytest -q`
   - `GITHUB_ACTIONS=true uv run pytest -q`
   - No `-m live`, do not clear addopts, commit nothing.

## Out of scope
Delete-side marker re-creation, `infra/`, `stories/**`, `.agents/shousper-stories/local/**`, the data repo.

## Orchestrator amendments

- Commit nothing; the orchestrator commits the story branch after the review gate.
- Put notes in the summary rather than setting needsHumanInput unless actually blocked.
- Never edit stories/** or .agents/shousper-stories/local/**. Never call AWS and never run terraform. No live tests (-m live).
- Judge pytest by exit code and never clear addopts; use -o addopts="-m 'not live'" only for a count. Also run GITHUB_ACTIONS=true uv run pytest -q.
- Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data.
- The delete-side marker is filed as st-c667. The comment on OutputStore.delete should name st-c667 rather than recommend a follow-up.
- OutputStore.list_files uses FileSelector(allow_not_found=True) and keeps only FileType.File entries, so listing does not depend on marker objects. Do not change it. If README.md, docs/plans/2026-10-29-swan-wetland-change-design.md or infra docs say writes create directory markers, update them.
- Prose in docs and comments: flat and factual, no em dashes.

## Implementation Notes

- 2026-11-06T00:56:22.670Z: store.py: write_bytes calls create_dir only when the root is a pyarrow LocalFileSystem (self._creates_parents set in __init__). tests/test_store.py: stub records (method, key) per request; test_s3_write_creates_no_directory_marker_keys (red on old code with PUTs to /prefix/, /prefix/runs/, /prefix/runs/a/) and test_local_write_creates_missing_parent_directories. Delete still re-creates the parent marker; filed st-c667. Gates all exit 0; 750 passed, 9 deselected.

## Questions
