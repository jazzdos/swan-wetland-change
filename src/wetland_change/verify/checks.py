"""Check results and the verification report."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wetland_change.attribution import DEA_ATTRIBUTION_KEY, dea_attribution
from wetland_change.runtime import Environment, capture_environment
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

    @property
    def advisory(self) -> bool:
        """A live row on a layer its limit was not calibrated on; it holds no verdict.

        See docs/decisions/0012-live-check-limits-apply-to-their-calibrated-layer.md.
        """
        return self.detail.get("advisory") is True

    @property
    def wet_area_only_failure(self) -> bool:
        """A live water check that passes agreement and fails only the wet area clause.

        Advisory under docs/decisions/0008-exit-code-for-live-water-check-failures.md:
        `passed` stays False, but the check does not block the run. An advisory
        row (ADR 0012) is never one.
        """
        return (
            not self.advisory
            and self.passed is False
            and self.detail.get("wet_area_passed") is False
            and self.measured is not None
            and self.threshold is not None
            and self.measured >= self.threshold
        )

    @property
    def blocking(self) -> bool:
        """Failed and not advisory; a blocking check makes `verify` exit 3."""
        return (
            self.passed is False
            and not self.advisory
            and not self.wet_area_only_failure
        )


def verdict_checks(checks: Iterable[Check]) -> list[Check]:
    """The rows that hold a verdict; advisory rows (ADR 0012) are left out."""
    return [c for c in checks if not c.advisory]


def check_note(check: Check) -> str:
    """The reader-facing note for the report and the CLI, empty for most checks.

    A wet-area-only failure names the polygon, scene and signed gap. The pooled
    wet area check states its gap and the number of checks pooled, passed or not,
    and the layer it was pooled over when it names one.
    """
    from wetland_change.verify.wo import POOLED_WET_AREA_CHECK  # wo imports Check

    if check.wet_area_only_failure:
        gap = check.detail.get("wet_area_diff_pp")
        limit = check.detail.get("wet_area_max_pp")
        who = " ".join(
            str(check.detail[k]) for k in ("polygon_id", "item") if k in check.detail
        )
        text = f"wet area gap {gap:+.2f} pp, limit {limit} pp"
        return f"{who}: {text}" if who else text
    if check.name == POOLED_WET_AREA_CHECK and check.measured is not None:
        text = (
            f"pooled wet area gap {check.measured:+.2f} pp over "
            f"{check.detail.get('n_checks')} checks, limit {check.threshold} pp"
        )
        layer = check.detail.get("layer")
        return f"{text}, {layer} layer only" if layer else text
    return ""


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
    advisory: list[dict[str, Any]],
    environment: Environment,
) -> str:
    from wetland_change.verify.layers import (
        LAYER_RULE,
        advisory_note,
    )  # layers imports Check

    lines = [
        f"# Verification report {run_id}",
        "",
        f"Generated {generated_at.isoformat()}.",
        "",
        "| check | passed | measured | threshold | reference | note |",
        "|---|---|---|---|---|---|",
    ]
    for c in verdict_checks(checks):
        if c.passed is None:
            status = "skipped"
        elif c.wet_area_only_failure:
            status = "warn"
        else:
            status = "yes" if c.passed else "no"
        measured = (
            ""
            if c.measured is None or not math.isfinite(c.measured)
            else f"{c.measured:.4f}"
        )
        threshold = "" if c.threshold is None else f"{c.threshold}"
        lines.append(
            f"| {c.name} | {status} | {measured} | {threshold} | {c.reference} "
            f"| {check_note(c)} |"
        )
    lines += [
        "",
        "## Matrix",
        "",
        "| row | status | pass | fail | warn | skipped | errored | note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in matrix:
        lines.append(
            f"| {r['row']} | {r['status']} | {r['n_pass']} | {r['n_fail']} "
            f"| {r['n_warn']} | {r['n_skipped']} | {r['n_errored']} | {r['note']} |"
        )
    if advisory:
        lines += [
            "",
            "## Advisory",
            "",
            "Live rows on layers other than ramsar are measured against the ramsar "
            f"limits and hold no verdict ({LAYER_RULE}).",
            "",
            "| check | layer | summary |",
            "|---|---|---|",
        ]
        for summary in advisory:
            lines.append(
                f"| {summary['check']} | {summary['layer']} "
                f"| {advisory_note(summary)} |"
            )
    lines += ["", "## Runtime", "", "| item | value |", "|---|---|"]
    for name, version in environment.runtime.items():
        lines.append(f"| {name} | {version} |")
    lines.append(f"| uv.lock sha256 | {environment.uv_lock_sha256 or 'none'} |")
    lines.append(f"| git commit | {environment.git_commit or 'none'} |")
    return "\n".join(lines) + "\n"


def write_report(
    checks: list[Check],
    *,
    store: OutputStore,
    run_id: str,
    docs_dir: Path | None,
    generated_at: datetime | None = None,
    environment: Environment | None = None,
) -> tuple[str, Path | None]:
    """JSON beside the outputs; Markdown under docs/research when given.

    `all_passed` is strict: any scored check with `passed` False clears it,
    including a wet-area-only failure, which `n_warned` counts. The exit code of
    `verify` is separate and ignores those advisory failures. Advisory rows
    (ADR 0012) are kept in `checks` but are left out of every count and of
    `all_passed`; `n_advisory` counts them and `advisory` holds one summary per
    live check and layer.

    The JSON carries `dea_attribution`, the CC BY 4.0 attribution for the
    Geoscience Australia DEA data its values derive from
    (src/wetland_change/attribution.py). The Markdown report does not.
    """
    from wetland_change.verify.layers import advisory_summaries  # layers imports Check
    from wetland_change.verify.matrix import matrix_status  # matrix imports Check

    when = generated_at or datetime.now(UTC)
    env = environment or capture_environment()
    verdict = verdict_checks(checks)
    scored = [c for c in verdict if c.passed is not None]
    n_errored = sum(c.errored for c in verdict)
    matrix = matrix_status(checks)
    summaries = advisory_summaries(checks)
    payload = {
        "run_id": run_id,
        "generated_at": when.isoformat(),
        "n_scored": len(scored),
        "n_skipped": len(verdict) - len(scored),
        "n_errored": n_errored,
        "n_warned": sum(c.wet_area_only_failure for c in verdict),
        "n_advisory": len(checks) - len(verdict),
        "all_passed": bool(scored) and all(c.passed for c in scored) and n_errored == 0,
        "matrix": matrix,
        "advisory": _finite(summaries),
        "runtime": env.runtime,
        "uv_lock_sha256": env.uv_lock_sha256,
        "git_commit": env.git_commit,
        "checks": [_finite(asdict(c)) for c in checks],
        DEA_ATTRIBUTION_KEY: dea_attribution("verification"),
    }
    json_path = store.write_bytes(
        report_path(run_id),
        json.dumps(payload, indent=2, default=str, allow_nan=False).encode(),
    )
    md_path: Path | None = None
    if docs_dir is not None:
        docs_dir.mkdir(parents=True, exist_ok=True)
        md_path = docs_dir / f"verification-{run_id}.md"
        md_path.write_text(
            _markdown(run_id, checks, when, matrix, _finite(summaries), env)
        )
    return json_path, md_path
