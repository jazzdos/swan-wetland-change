---
id: st-c667
title: Stop S3 deletes from re-creating directory markers
type: bug
priority: P2
depends_on: []
discovered_from: st-2cc2
touches: [LEARNINGS.md, pyproject.toml, src/wetland_change/store.py, tests/test_store.py, uv.lock]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

OutputStore.delete (src/wetland_change/store.py) calls pyarrow's S3FileSystem.delete_file. The st-2cc2 planner probed pyarrow 26.0.0 against the stub S3 server in tests/test_store.py: delete_file sends DELETE <key> and then PUT <parent>/ with Content-Type application/x-directory, so every delete re-creates the parent directory marker that st-2cc2 removes from writes. Callers are ledger compaction (src/wetland_change/ledger.py:291,295) and pipeline.py:320. No S3FileSystem option stops it. Out of scope in st-2cc2, whose criteria cover writes only. Candidate fixes: delete through fs.delete_files if it skips the parent marker (to be checked against the stub), or a direct S3 DeleteObject call; the fix must not call AWS in tests.

## Acceptance Criteria

- [ ] Deleting a key from an S3 root sends no request that creates a key ending in a slash
- [ ] checked against the stub S3 server on 127.0.0.1
- [ ] OutputStore.delete still returns whether the key existed
- [ ] and deleting from a local root still works

## Implementation Plan

## Verified findings (worktree .worktrees/st-c667, main at f501dac, pyarrow 26.0.0)

- `OutputStore.delete` (src/wetland_change/store.py:69) calls `self.fs.delete_file`. Probed against a key-aware copy of the stub: `delete_file` sends HEAD key, DELETE key, then `PUT /prefix/a/` (the parent marker). Confirmed.
- The story's first candidate does not exist: `pyarrow.fs.S3FileSystem` has no `delete_files` in 26.0.0 (methods: copy_file, create_dir, delete_dir, delete_dir_contents, delete_file, move, ...). No option stops the marker PUT.
- Second candidate works: a botocore S3 client `delete_object` against the stub sends exactly `DELETE /prefix/a/c.json` and nothing else (probed, path-style addressing, endpoint_url at 127.0.0.1).
- botocore is not a dependency today (only pyarrow, requests, urllib3, no boto3/s3fs/fsspec). `uv pip install --dry-run botocore` resolves (botocore 1.43.x, jmespath, python-dateutil). So the fix adds `botocore` as a runtime dependency. This is the only viable no-marker route; hand-rolled SigV4 was rejected as riskier than botocore's credential chain (CI uses configure-aws-credentials env vars).
- The existing stub in tests/test_store.py returns 404 for HEAD on any non-empty key and an empty listing, so `OutputStore.exists` is False for every key there. The delete tests need the stub to know seeded keys.
- Callers (ledger.py:291,295, pipeline.py:372) only use the bool return; behaviour unchanged.

## Steps

1. Add the dependency. In the worktree run `uv add botocore` (adds `botocore>=1.4x` to pyproject.toml `dependencies` and updates uv.lock). If mypy then reports missing stubs for botocore, add a `[[tool.mypy.overrides]] module = ["botocore.*"] ignore_missing_imports = true` entry next to any existing mypy config in pyproject.toml (or add `types-botocore` to the dev group; prefer the override if it is simpler). Do not add boto3.

2. Tests first (tests/test_store.py), then watch them fail:
   - Make `_StubS3` key-aware: add `self.keys: set[str] = set()` in `__init__` (keys without leading slash, e.g. `"prefix/runs/a/r.json"`). In `_StubS3Handler._handle`, after recording `requests`/`calls` and computing `key`: for HEAD, reply 200 if `not key or key in self.server.keys`, else 404 (same as today for unseeded keys, so existing tests are unaffected); for DELETE, `self.server.keys.discard(key)` and reply 204. Leave GET/PUT/POST as is.
   - `test_s3_delete_sends_no_request_that_creates_a_slash_key`: `stub_s3.keys.add("prefix/runs/a/r.json")`; store = `_s3_store(...)`; `assert store.delete("runs/a/r.json") is True`; assert `("DELETE", "/prefix/runs/a/r.json") in stub_s3.calls`; assert `[c for c in stub_s3.calls if c[0] in ("PUT", "POST")] == []`; assert no call at all has a key ending in `/` with a non-GET/HEAD method; assert the key was removed from `stub_s3.keys`. Proves the acceptance criterion against the 127.0.0.1 stub and that the old pyarrow path (PUT /prefix/runs/a/) is gone.
   - `test_s3_delete_returns_false_and_sends_no_delete_when_key_is_absent`: unseeded key; `store.delete("nope.json") is False`; no DELETE in `stub_s3.calls`. Proves the existed-bool contract.
   - `test_s3_delete_works_for_a_key_at_the_root_prefix_level`: seed `prefix/z.json`, delete `z.json`, returns True, DELETE `/prefix/z.json`, no PUT/POST. Proves bucket/key splitting with `_full`.
   - `test_local_delete_returns_whether_the_key_existed` (tmp_path): write `a/b.txt`, `delete("a/b.txt") is True`, file gone, second `delete` is False, and a missing key never raises. Proves the local branch still uses the filesystem.
   - `test_local_store_builds_no_s3_client`: `OutputStore(str(tmp_path/"out"))` then `delete` of a missing key works and `store._s3 is None` (see step 3 attribute name; adjust to the real name chosen).
   Run `uv run pytest tests/test_store.py -q` and confirm the new S3 tests fail for the right reason (PUT /prefix/... recorded, or HEAD/exists mismatch) before step 3.

3. Implement in src/wetland_change/store.py:
   - Imports: `from urllib.parse import parse_qs, urlsplit`, `import botocore.session`, `from botocore.config import Config`.
   - In `__init__`, keep the existing logic and add `self._is_s3 = isinstance(self.fs, pafs.S3FileSystem)` and `self._s3: Any = None` (typed lazily). Parse the URI query once: `query = {k: v[0] for k, v in parse_qs(urlsplit(root).query).items()}` and keep `endpoint_override`, `scheme` (default `https`), `region` as private attributes.
   - Add `_s3_client()` that lazily builds and caches `botocore.session.get_session().create_client("s3", region_name=region or self.fs.region or None, endpoint_url=f"{scheme}://{endpoint_override}" if endpoint_override else None, config=Config(s3={"addressing_style": "path"}) if endpoint_override else None)`. Always pass an explicit `endpoint_url` when the URI has `endpoint_override`, so tests never reach AWS; credentials come from botocore's default chain (env vars in CI and in the tests' monkeypatched env).
   - Rewrite `delete`: `if not self.exists(relpath): return False`; if S3, `bucket, key = self._full(relpath).split("/", 1)` then `self._s3_client().delete_object(Bucket=bucket, Key=key)`; else `self.fs.delete_file(self._full(relpath))`; return True. Replace the st-c667 comment with a short note that pyarrow's `S3FileSystem.delete_file` PUTs the parent directory marker, so S3 deletes go through DeleteObject.
   - Update the module docstring: deletes on S3 use a botocore DeleteObject so no directory marker is created; local deletes use the filesystem.

4. Docs: in LEARNINGS.md add one short dated entry (observed 2026-11: pyarrow 26.0.0 S3 `delete_file` PUTs the parent marker, `delete_files` does not exist, botocore DeleteObject sends one DELETE) if LEARNINGS.md has a findings section; otherwise skip. No data/SOURCES.md row (not a dataset). Do not run anything against the project's bucket, terraform, or compaction against S3.

5. Verify, one command each: `uv run ruff check src tests scripts`; `uv run ruff format --check src tests scripts` (run `uv run ruff format` on the touched files if it fails); `uv run mypy src scripts`; `uv run pytest -q`; `GITHUB_ACTIONS=true uv run pytest -q`. Confirm `git status` shows only pyproject.toml, uv.lock, src/wetland_change/store.py, tests/test_store.py (and LEARNINGS.md if edited).## Orchestrator amendments

These override the text above where they differ.

1. Commit nothing; the orchestrator commits. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**. Never call AWS for the project's own bucket, never run terraform plan or apply, never run compaction against S3. Judge pytest gates by exit code and never clear addopts for them; for a count use -o addopts="-m 'not live'". Docs are flat factual prose with no em dashes.
2. Tests must never reach anything but 127.0.0.1. Wherever a test builds an S3 OutputStore, monkeypatch AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_REGION to dummy values, set AWS_EC2_METADATA_DISABLED=true, delete AWS_PROFILE and AWS_SESSION_TOKEN, and point AWS_CONFIG_FILE and AWS_SHARED_CREDENTIALS_FILE at missing paths under tmp_path, so botocore never reads the developer's ~/.aws files or the instance metadata endpoint. Extend the existing `_s3_store` helper rather than repeating this per test.
3. The botocore client must use an explicit endpoint_url whenever the root URI carries endpoint_override; add one assertion in a test that the client's endpoint is the stub's 127.0.0.1 address.
4. botocore is a runtime dependency added with `uv add botocore`, so uv.lock changes in the same commit; confirm `uv lock --check` exits 0. Do not add boto3, s3fs or fsspec.

## Implementation Notes

- 2026-11-06T04:41:48.036Z: OutputStore.delete uses a botocore DeleteObject on S3 roots (pyarrow 26.0.0 has no delete_files and delete_file PUTs the parent marker). Tests against the 127.0.0.1 stub assert one DELETE and no PUT or POST; the bool return and local deletes are unchanged. New runtime dependency botocore; uv.lock moved python-dateutil from 3.0.0 to 2.9.0.post0 under botocore's constraint. 847 passed.

## Questions
