import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import rasterio

from wetland_change.manifest import (
    KIND_REQUEUE,
    RunManifest,
    config_sha256,
    manifest_path,
    new_run_id,
    write_manifest,
)
from wetland_change.runtime import capture_environment
from wetland_change.store import OutputStore

NOW = datetime(2026, 10, 29, 10, 5, 7, tzinfo=UTC)


def test_new_run_id_is_sortable_utc_stamp() -> None:
    assert new_run_id(NOW) == "20261029T100507Z"


def test_config_sha256(tmp_path: Path) -> None:
    path = tmp_path / "p.toml"
    path.write_text("a = 1\n")
    assert config_sha256(path) == config_sha256(path)
    assert len(config_sha256(path)) == 64


def test_write_manifest_round_trips(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    manifest = RunManifest(
        run_id="r1",
        started_at=NOW,
        finished_at=NOW,
        package_version="0.1.0",
        config_sha256="abc",
        endpoint="https://example",
        collection="sentinel-2-c1-l2a",
        watermark_before=None,
        watermark_after=NOW,
        discovered=2,
        processed=1,
        failed=1,
        rejected=0,
        skipped_seen=0,
        skipped_filter=3,
        observation_files=["observations/a.parquet"],
        ledger_files=["ledger/year=2026/ledger_r1.parquet"],
    )
    relpath = write_manifest(manifest, store)
    assert relpath == manifest_path("r1") == "runs/r1.json"
    payload = json.loads(store.read_bytes(relpath))
    assert payload["run_id"] == "r1"
    assert payload["watermark_before"] is None
    assert payload["watermark_after"] == "2026-10-29T10:05:07+00:00"
    assert payload["observation_files"] == ["observations/a.parquet"]


def test_exhausted_and_requeued_fields_default_and_round_trip(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    manifest = RunManifest(
        run_id="r2",
        started_at=NOW,
        finished_at=NOW,
        package_version="0.1.0",
        config_sha256="abc",
        endpoint="https://example",
        collection="sentinel-2-c1-l2a",
        watermark_before=None,
        watermark_after=None,
    )
    assert manifest.exhausted == 0
    assert manifest.exhausted_items == []
    assert manifest.requeued_items == []
    assert KIND_REQUEUE == "requeue"
    manifest.exhausted_items = ["a", "b"]
    manifest.exhausted = 2
    manifest.requeued_items = ["c"]
    payload = json.loads(store.read_bytes(write_manifest(manifest, store)))
    assert payload["exhausted"] == 2
    assert payload["exhausted_items"] == ["a", "b"]
    assert payload["requeued_items"] == ["c"]


def test_recovery_fields_default_to_null_and_empty_in_json() -> None:
    manifest = RunManifest(
        run_id="r3",
        started_at=NOW,
        finished_at=NOW,
        package_version="0.1.0",
        config_sha256="abc",
        endpoint="https://example",
        collection="sentinel-2-c1-l2a",
        watermark_before=None,
        watermark_after=None,
    )
    payload = json.loads(manifest.to_json())
    assert payload["recovered_by"] is None
    assert payload["recovered_runs"] == []


def _manifest(**extra: Any) -> RunManifest:
    return RunManifest(
        run_id="r2",
        started_at=NOW,
        finished_at=NOW,
        package_version="0.1.0",
        config_sha256="abc",
        endpoint="https://example",
        collection="sentinel-2-c1-l2a",
        watermark_before=None,
        watermark_after=None,
        discovered=0,
        processed=0,
        failed=0,
        rejected=0,
        skipped_seen=0,
        skipped_filter=0,
        observation_files=[],
        ledger_files=[],
        **extra,
    )


def test_operation_epsg_defaults_to_none() -> None:
    manifest = _manifest()
    assert manifest.operation_epsg is None
    assert json.loads(manifest.to_json())["operation_epsg"] is None


def test_operation_epsg_is_written_to_the_manifest(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_manifest(_manifest(operation_epsg=32750), store)
    assert json.loads(store.read_bytes(relpath))["operation_epsg"] == 32750


def test_environment_fields_default_to_null_in_the_manifest_json(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_manifest(_manifest(), store)
    payload = json.loads(store.read_bytes(relpath))
    assert payload["runtime"] is None
    assert payload["uv_lock_sha256"] is None
    assert payload["git_commit"] is None


def test_environment_fields_round_trip_through_the_manifest_json(
    tmp_path: Path,
) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_manifest(
        _manifest(runtime={"python": "3.12.0"}, uv_lock_sha256="abc", git_commit="def"),
        store,
    )
    payload = json.loads(store.read_bytes(relpath))
    assert payload["runtime"] == {"python": "3.12.0"}
    assert payload["uv_lock_sha256"] == "abc"
    assert payload["git_commit"] == "def"


def test_capture_environment_runtime_has_the_seven_versions() -> None:
    runtime = capture_environment().runtime
    assert set(runtime) == {
        "python",
        "gdal",
        "proj",
        "geopandas",
        "rasterio",
        "pyarrow",
        "numpy",
    }
    assert all(isinstance(v, str) and v for v in runtime.values())
    assert runtime["gdal"] == rasterio.__gdal_version__


def test_uv_lock_sha256_hashes_the_lock_file(tmp_path: Path) -> None:
    assert capture_environment(tmp_path).uv_lock_sha256 is None
    (tmp_path / "uv.lock").write_bytes(b"version = 1\n")
    assert (
        capture_environment(tmp_path).uv_lock_sha256
        == hashlib.sha256(b"version = 1\n").hexdigest()
    )


def test_git_commit_is_null_outside_a_checkout(tmp_path: Path) -> None:
    assert capture_environment(tmp_path).git_commit is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git binary not installed")
def test_git_commit_inside_a_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    git = [
        "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "commit.gpgsign=false",
    ]
    subprocess.run([*git, "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [*git, "commit", "--allow-empty", "-m", "x"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        [*git, "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert len(head) == 40
    assert capture_environment(tmp_path).git_commit == head
