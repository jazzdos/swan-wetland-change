---
id: st-2bc1
title: Record runtime versions and lock hash with each run
type: task
priority: P2
depends_on: []
discovered_from: st-ff89
touches: [README.md, src/wetland_change/manifest.py, src/wetland_change/pipeline.py, src/wetland_change/runtime.py, src/wetland_change/verify/checks.py, tests/test_manifest.py, tests/test_pipeline.py, tests/test_verify.py]
exclusive: false
created: 2026-11-06
updated: 2026-11-06
---

## Description

The run manifest records package_version (a constant 0.1.0) and config_sha256 (src/wetland_change/manifest.py:38-39, src/wetland_change/pipeline.py:163-164). It records no Python, GDAL, PROJ, geopandas, rasterio or pyarrow version, no uv.lock hash and no git commit, and the verification report records none either. A result cannot be tied to the environment that produced it. Found by the st-ff89 reproducibility audit, which fixes nothing.

## Acceptance Criteria

- [ ] The run manifest JSON has a runtime object with the Python
- [ ] GDAL
- [ ] PROJ
- [ ] geopandas
- [ ] rasterio
- [ ] pyarrow and numpy versions.
- [ ] The run manifest JSON has the sha256 of uv.lock and the git commit when the code runs inside a git checkout
- [ ] and null otherwise.
- [ ] The verification JSON report and the Markdown report carry the same runtime object.
- [ ] A recovered manifest leaves the new fields empty
- [ ] like package_version and config_sha256.
- [ ] Tests in tests/test_manifest.py and tests/test_verify.py assert the fields.
- [ ] The four verification gates pass.

## Implementation Plan

## Verified against the worktree (/Users/jarrodbaker/Documents/swan-wetland-change/.worktrees/st-2bc1, HEAD db65374)

- `src/wetland_change/manifest.py` holds `RunManifest` (dataclass, `to_json` uses `asdict`, `sort_keys=True`). It has `package_version` and `config_sha256` (both `str | None`) and `operation_epsg` (default None).
- `RunManifest(...)` is built in four places in `src/wetland_change/pipeline.py`: `_new_manifest` (~l.159, daily run and backfill), the score manifest (~l.779), the requeue manifest (~l.828), and `_recovered_manifest` (~l.581, which passes `package_version=None, config_sha256=None`).
- The verification report is `write_report` in `src/wetland_change/verify/checks.py` (JSON payload dict plus `_markdown(run_id, checks, generated_at, matrix)`). It is called once from `src/wetland_change/verify/run.py:505` and from several tests with the signature `write_report(checks, store=, run_id=, docs_dir=, generated_at=)`. That signature must stay backward compatible.
- Versions available in the venv: `rasterio.__gdal_version__` (3.12.2), `pyproj.proj_version_str` (9.8.1, pyproj is a declared dependency), plus the `__version__` attributes of geopandas, rasterio, pyarrow and numpy. `rasterio.env.get_gdal_release_name` does not exist, so do not use it.
- There is no existing module for any of this. README.md line ~100 documents the recovered-manifest empty fields.

## Design

New module `src/wetland_change/runtime.py` with `capture_environment(root: Path | None = None) -> Environment`. `Environment` is a frozen dataclass with `runtime: dict[str, str]`, `uv_lock_sha256: str | None` and `git_commit: str | None`.

- `runtime` keys: `python` (`platform.python_version()`), `gdal`, `proj` (pyproj's PROJ, the one geopandas reprojects with), `geopandas`, `rasterio`, `pyarrow`, `numpy`.
- `root` defaults to `Path(__file__).resolve().parents[2]`, the repo root. `uv_lock_sha256` is the sha256 of `root/uv.lock` if the file exists, else None.
- `git_commit` is `git rev-parse HEAD` run with `cwd=root`, only when `(root/".git")` exists (a file or a directory, since worktrees use a file). On a missing git binary, a non-zero exit, a timeout or an OSError it returns None. The `.git` check stops a non-editable install inside some other repository from reporting that repository's commit.

Manifest: `RunManifest` gains `runtime: dict[str, str] | None = None`, `uv_lock_sha256: str | None = None` and `git_commit: str | None = None`. These are top-level JSON keys. The three live constructions in pipeline.py fill them from one `capture_environment()` call. `_recovered_manifest` leaves them at the None defaults and gets a comment and docstring edit, because only the crashed process knew its environment.

Verification: `write_report` gains an optional keyword `environment: Environment | None = None`, defaulting to `capture_environment()`. The JSON payload gains `runtime` (same dict as the manifest), `uv_lock_sha256` and `git_commit`. The Markdown gets a trailing `## Runtime` section listing each runtime key plus uv.lock sha256 and git commit (`none` when null).

## Steps

1. TDD, `src/wetland_change/runtime.py` plus tests in `tests/test_manifest.py`.
   - `test_capture_environment_runtime_has_the_seven_versions`: keys equal {python, gdal, proj, geopandas, rasterio, pyarrow, numpy}, every value a non-empty str, and gdal equals `rasterio.__gdal_version__`.
   - `test_uv_lock_sha256_hashes_the_lock_file`: tmp root with a `uv.lock` gives the sha256 of its bytes; without one it gives None.
   - `test_git_commit_is_null_outside_a_checkout`: tmp root with no `.git` gives None.
   - `test_git_commit_inside_a_checkout`: `git init` plus an empty commit via `git -c user.name=t -c user.email=t@t commit --allow-empty -m x` in tmp, then expect `rev-parse HEAD`.
2. TDD, manifest fields in `src/wetland_change/manifest.py` and `src/wetland_change/pipeline.py`, tests in `tests/test_manifest.py` and `tests/test_pipeline.py`.
   - Manifest defaults are None and serialise as JSON null.
   - A manifest built with `runtime={...}`, `uv_lock_sha256="abc"` and `git_commit="def"` round-trips through `write_manifest`.
   - A run written by the pipeline (daily, and the score and requeue kinds if the existing helpers make that cheap) has a `runtime` object with the seven keys, and `uv_lock_sha256` and `git_commit` equal to `capture_environment()` values (monkeypatch `wetland_change.pipeline.capture_environment` to a fixed `Environment` for determinism).
   - In `test_a_recovered_manifest_does_not_take_the_recovering_runs_config`, the recovered manifest has `runtime`, `uv_lock_sha256` and `git_commit` all None, and the recovering run's own manifest has a populated `runtime`.
3. TDD, verification report in `src/wetland_change/verify/checks.py`, tests in `tests/test_verify.py`.
   - `write_report` with an injected `Environment` puts `payload["runtime"]`, `payload["uv_lock_sha256"]` and `payload["git_commit"]` in the JSON, and the Markdown contains the `## Runtime` heading, the python and gdal values and the git commit.
   - With no `environment` argument, the JSON `runtime` equals `capture_environment().runtime`, which is the same object shape as the manifest's.
   - A null commit and null lock render as `none` in the Markdown.
4. Docs. Update README.md (~l.100) so the recovered-manifest sentence also lists `runtime`, `uv_lock_sha256` and `git_commit`, and add one line saying the manifest and verification report record the runtime versions, uv.lock sha256 and git commit. Do not edit docs/research files.
5. Run the four gates in order, one command per line: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`. All must pass. Do not run live tests.
## Orchestrator amendments

These override the text above where they differ.

1. Agents commit nothing; the orchestrator commits after the run. Uncommitted work at the end of a task is expected and is not a defect. Put notes in the summary rather than setting needsHumanInput unless actually blocked. Never edit stories/** or .agents/shousper-stories/local/**.
2. Never call AWS for the project's own bucket, never run terraform plan or apply, never run compaction against S3, and never run `-m live` tests. Write nothing under /Users/jarrodbaker/Documents/swan-wetland-change-data and never point verify_run there. Do not rewrite committed reports under docs/research.
3. Gates, one command each, judged by exit code: `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv run mypy src scripts`, `uv run pytest -q`, `GITHUB_ACTIONS=true uv run pytest -q`. Never clear addopts for a gate; for a count use `-o addopts="-m 'not live'"`.
4. Tests that create a git repository must not depend on the developer's git config: run git with `-c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false` and set `GIT_CONFIG_GLOBAL=/dev/null` and `GIT_CONFIG_NOSYSTEM=1` in the subprocess env (monkeypatch.setenv is fine), so a global signing or hook setting cannot fail the test. Skip that one test with a clear reason if the git binary is missing.
5. The runtime object in the manifest and in the verification JSON must be the same shape and come from the same function, `capture_environment().runtime`. Do not put timestamps or hostnames in it.
6. Docs are flat factual prose with no em dashes.

## Implementation Notes

- 2026-11-06T06:14:44.318Z: Added src/wetland_change/runtime.py (Environment, capture_environment). RunManifest gains runtime, uv_lock_sha256 and git_commit; daily, score and requeue manifests fill them from one capture_environment() call; _recovered_manifest leaves them None. verify write_report takes an optional environment and adds the same three fields to the JSON and a Runtime table to the Markdown. git_commit is read only when the package root has .git, so an install inside another repository reports null. The git test isolates global and system git config. 907 passed.

## Questions
