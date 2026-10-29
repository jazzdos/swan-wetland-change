"""Check results and the verification report."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wetland_change.store import OutputStore


@dataclass
class Check:
    name: str
    passed: bool | None
    measured: float | None
    threshold: float | None
    reference: str
    detail: dict[str, Any] = field(default_factory=dict)


def _finite(value: Any) -> Any:
    """Map non-finite floats to None so the report is strict JSON."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(v) for v in value]
    return value


def report_path(run_id: str) -> str:
    return f"verification/{run_id}.json"


def _markdown(run_id: str, checks: list[Check], generated_at: datetime) -> str:
    lines = [
        f"# Verification report {run_id}",
        "",
        f"Generated {generated_at.isoformat()}.",
        "",
        "| check | passed | measured | threshold | reference |",
        "|---|---|---|---|---|",
    ]
    for c in checks:
        status = "skipped" if c.passed is None else ("yes" if c.passed else "no")
        measured = (
            ""
            if c.measured is None or not math.isfinite(c.measured)
            else f"{c.measured:.4f}"
        )
        threshold = "" if c.threshold is None else f"{c.threshold}"
        lines.append(
            f"| {c.name} | {status} | {measured} | {threshold} | {c.reference} |"
        )
    return "\n".join(lines) + "\n"


def write_report(
    checks: list[Check],
    *,
    store: OutputStore,
    run_id: str,
    docs_dir: Path | None,
    generated_at: datetime | None = None,
) -> tuple[str, Path | None]:
    """JSON beside the outputs; Markdown under docs/research when given."""
    when = generated_at or datetime.now(UTC)
    scored = [c for c in checks if c.passed is not None]
    payload = {
        "run_id": run_id,
        "generated_at": when.isoformat(),
        "n_scored": len(scored),
        "n_skipped": len(checks) - len(scored),
        "all_passed": bool(scored) and all(c.passed for c in scored),
        "checks": [_finite(asdict(c)) for c in checks],
    }
    json_path = store.write_bytes(
        report_path(run_id),
        json.dumps(payload, indent=2, default=str, allow_nan=False).encode(),
    )
    md_path: Path | None = None
    if docs_dir is not None:
        docs_dir.mkdir(parents=True, exist_ok=True)
        md_path = docs_dir / f"verification-{run_id}.md"
        md_path.write_text(_markdown(run_id, checks, when))
    return json_path, md_path
