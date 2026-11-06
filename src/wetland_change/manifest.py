"""Run manifest: what one run saw, did and wrote."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from wetland_change.store import OutputStore

KIND_SCORE = "score"
KIND_REQUEUE = "requeue"


def new_run_id(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def config_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_path(run_id: str) -> str:
    return f"runs/{run_id}.json"


@dataclass
class RunManifest:
    run_id: str
    started_at: datetime
    finished_at: datetime | None
    # None on a recovered manifest: the ledger does not record which version
    # or config produced a row, and the recovering run's own are not the
    # crashed run's.
    package_version: str | None
    config_sha256: str | None
    endpoint: str
    collection: str
    watermark_before: datetime | None
    watermark_after: datetime | None
    discovered: int = 0
    processed: int = 0
    failed: int = 0
    # Rejections newly written to the ledger this run.
    rejected: int = 0
    # Items already processed, plus rejections unchanged since they were
    # logged (same updated and reason), which are skipped and not rewritten.
    skipped_seen: int = 0
    skipped_filter: int = 0
    observation_files: list[str] = field(default_factory=list)
    # Parts this run wrote. A later compaction may merge them into
    # ledger/compacted/, so these paths can stop existing.
    ledger_files: list[str] = field(default_factory=list)
    kind: str = "run"
    datetime_start: datetime | None = None
    datetime_end: datetime | None = None
    output_root_override: str | None = None
    change_rows: int = 0
    change_files: list[str] = field(default_factory=list)
    change_files_removed: list[str] = field(default_factory=list)
    exhausted: int = 0
    exhausted_items: list[str] = field(default_factory=list)
    requeued_items: list[str] = field(default_factory=list)
    # The later run that finished scoring for this run and wrote this manifest
    # from the ledger. On such a manifest skipped_seen, skipped_filter and both
    # watermarks are empty, because only the crashed process knew them.
    recovered_by: str | None = None
    # Runs this run finished.
    recovered_runs: list[str] = field(default_factory=list)
    # CRS operations run in (cfg.aoi.operation_epsg). None on a recovered
    # manifest because the crashed run's config is not known, the same reason
    # package_version and config_sha256 are None there.
    operation_epsg: int | None = None
    # Library versions, the sha256 of uv.lock and the git commit of the code
    # that made the run. None on a recovered manifest because only the crashed
    # process knew its environment, the same reason package_version and
    # config_sha256 are None there.
    runtime: dict[str, str] | None = None
    uv_lock_sha256: str | None = None
    git_commit: str | None = None

    def to_json(self) -> str:
        def _default(value: Any) -> str:
            if isinstance(value, datetime):
                return value.isoformat()
            raise TypeError(f"not serialisable: {type(value).__name__}")

        return json.dumps(asdict(self), indent=2, sort_keys=True, default=_default)


def write_manifest(manifest: RunManifest, store: OutputStore) -> str:
    return store.write_bytes(
        manifest_path(manifest.run_id), manifest.to_json().encode()
    )
