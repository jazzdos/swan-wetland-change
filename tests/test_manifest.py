import json
from datetime import UTC, datetime
from pathlib import Path

from wetland_change.manifest import (
    RunManifest,
    config_sha256,
    manifest_path,
    new_run_id,
    write_manifest,
)
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
