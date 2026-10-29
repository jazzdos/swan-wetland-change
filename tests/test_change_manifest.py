import json
from datetime import UTC, datetime
from pathlib import Path

from wetland_change.manifest import (
    KIND_SCORE,
    RunManifest,
    manifest_path,
    write_manifest,
)
from wetland_change.store import OutputStore

NOW = datetime(2026, 10, 30, 10, 5, 7, tzinfo=UTC)
CHANGE_FILE = "changes/year=2026/tile=50HLK/chg_x.parquet"


def _manifest(**extra: object) -> RunManifest:
    return RunManifest(
        run_id="r1",
        started_at=NOW,
        finished_at=NOW,
        package_version="0.1.0",
        config_sha256="abc",
        endpoint="https://example",
        collection="sentinel-2-c1-l2a",
        watermark_before=None,
        watermark_after=None,
        **extra,  # type: ignore[arg-type]
    )


def test_change_fields_default_to_empty() -> None:
    manifest = _manifest()
    assert manifest.change_rows == 0
    assert manifest.change_files == []
    assert manifest.change_files_removed == []
    payload = json.loads(manifest.to_json())
    assert payload["change_rows"] == 0
    assert payload["change_files"] == []
    assert payload["change_files_removed"] == []


def test_kind_score_constant() -> None:
    assert KIND_SCORE == "score"


def test_change_fields_round_trip(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    manifest = _manifest(
        kind=KIND_SCORE,
        change_rows=3,
        change_files=[CHANGE_FILE],
        change_files_removed=["changes/year=2026/tile=T50HNH/chg_old.parquet"],
    )
    relpath = write_manifest(manifest, store)
    assert relpath == manifest_path("r1") == "runs/r1.json"
    payload = json.loads(store.read_bytes(relpath))
    assert payload["kind"] == "score"
    assert payload["change_rows"] == 3
    assert payload["change_files"] == [CHANGE_FILE]
    assert payload["change_files_removed"] == [
        "changes/year=2026/tile=T50HNH/chg_old.parquet"
    ]


def test_adr_0004_records_strictly_before_rule() -> None:
    root = Path(__file__).parent.parent
    matches = list((root / "docs" / "decisions").glob("0004-*.md"))
    assert len(matches) == 1
    assert "strictly before" in matches[0].read_text()
