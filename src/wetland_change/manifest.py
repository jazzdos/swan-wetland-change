"""Run manifest: what one run saw, did and wrote."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from wetland_change.store import OutputStore


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
    package_version: str
    config_sha256: str
    endpoint: str
    collection: str
    watermark_before: datetime | None
    watermark_after: datetime | None
    discovered: int = 0
    processed: int = 0
    failed: int = 0
    rejected: int = 0
    skipped_seen: int = 0
    skipped_filter: int = 0
    observation_files: list[str] = field(default_factory=list)
    ledger_files: list[str] = field(default_factory=list)

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
