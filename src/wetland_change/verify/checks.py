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

    @property
    def errored(self) -> bool:
        """Skipped because its source raised; a reason-only skip is not errored."""
        return self.passed is None and "error" in self.detail


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


def _markdown(
    run_id: str,
    checks: list[Check],
    generated_at: datetime,
    matrix: list[dict[str, Any]],
) -> str:
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
    lines += [
        "",
        "## Matrix",
        "",
        "| row | status | pass | fail | skipped | errored | note |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in matrix:
        lines.append(
            f"| {r['row']} | {r['status']} | {r['n_pass']} | {r['n_fail']} "
            f"| {r['n_skipped']} | {r['n_errored']} | {r['note']} |"
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
    from wetland_change.verify.matrix import matrix_status  # matrix imports Check

    when = generated_at or datetime.now(UTC)
    scored = [c for c in checks if c.passed is not None]
    n_errored = sum(c.errored for c in checks)
    matrix = matrix_status(checks)
    payload = {
        "run_id": run_id,
        "generated_at": when.isoformat(),
        "n_scored": len(scored),
        "n_skipped": len(checks) - len(scored),
        "n_errored": n_errored,
        "all_passed": bool(scored) and all(c.passed for c in scored) and n_errored == 0,
        "matrix": matrix,
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
        md_path.write_text(_markdown(run_id, checks, when, matrix))
    return json_path, md_path
