"""Backfill analysis for story st-b983: coverage, change rows and hypotheses H1 to H4.

The hypotheses and their verdict rules are pre-registered in LEARNINGS.md
(section "Pre-registered hypotheses (st-b983, 2026-11-02)"). The verdict
functions here implement those rules and nothing else.

Run from the worktree root, because config/pipeline.toml holds relative AOI
paths. The script reads the output root and never writes to it; it writes only
to the paths given as arguments.

Subcommands:

    selftest   Run the verdict and comparison cases. No network, no files.
    reference  Search Earth Search for the CLI's polygon set over the range and
               write the reference id list and its count.
    analyse    Rescore the stored observations for ramsar-56 and ramsar-52,
               compare them with the stored change files, and write the changes
               CSV, the scores CSV and the evidence JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Final

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape

from wetland_change.aoi import AoiPolygon, load_waterbodies, union_bbox_4326
from wetland_change.catalogue.search import (
    Discovery,
    build_search_kwargs,
    discover,
    open_client,
)
from wetland_change.change import (
    METRICS,
    SCORE_COLUMNS,
    build_baseline,
    score_observations,
)
from wetland_change.cli import _load
from wetland_change.config import PipelineConfig, WaterbodiesVerifyConfig
from wetland_change.ledger import exhausted_keys, latest_entries, read_ledger
from wetland_change.outputs.changes import CHANGE_COLUMNS
from wetland_change.outputs.geoparquet import read_observations
from wetland_change.store import OutputStore
from wetland_change.verify.checks import Check
from wetland_change.verify.waterbodies import (
    CHECK_NAME,
    LAKES,
    SPEARMAN_CHECK_NAME,
    _unavailable,
    fetch_series,
    waterbody_checks,
)
from wetland_change.verify.waterbodies import (
    read_observations as read_lake_observations,
)

WATER: Final = "water_ha_index"
NDVI: Final = "ndvi_median"
FORRESTDALE: Final = "ramsar-56"
THOMSONS: Final = "ramsar-52"
POLYGONS: Final = (FORRESTDALE, THOMSONS)
FORRESTDALE_UID: Final = "qd63n1ww5_v3"
RHO_MIN: Final = 0.9
SERIES_UNAVAILABLE: Final = "series unavailable"
DEFAULT_START: Final = "2022-12-01"

SUPPORTED: Final = "supported"
NOT_SUPPORTED: Final = "not supported"
UNTESTABLE: Final = "untestable"

H1_WINDOW: Final = (date(2023, 12, 1), date(2024, 1, 31))
H2_WINDOW: Final = (date(2023, 2, 1), date(2023, 4, 30))
H3_WINDOW: Final = (date(2025, 6, 1), date(2025, 8, 31))


# --- verdicts ---------------------------------------------------------------

Window = tuple[date, date]


def _window_json(window: Window) -> list[str]:
    return [window[0].isoformat(), window[1].isoformat()]


def _rows_in_window(
    scores: pd.DataFrame, window: Window, metric: str = WATER
) -> pd.DataFrame:
    """Rows of one metric inside the window, with `acquisition_date` as a date."""
    columns = list(scores.columns)
    if scores.empty:
        return scores.loc[:, columns].copy()
    days = pd.to_datetime(scores["acquisition_date"]).dt.date
    keep = (scores["metric"] == metric) & (days >= window[0]) & (days <= window[1])
    rows = scores.loc[keep, columns].copy()
    rows["acquisition_date"] = days[keep]
    return rows.reset_index(drop=True)


def _scored_mask(rows: pd.DataFrame) -> pd.Series:
    return rows["reason"].isna() & rows["z"].notna()


def _low_mask(rows: pd.DataFrame) -> pd.Series:
    return rows["flagged"].astype(bool) & (rows["z"] < 0)


def _number(value: Any) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def _flag_records(rows: pd.DataFrame) -> list[dict[str, Any]]:
    flagged = rows[rows["flagged"].astype(bool)].sort_values("acquisition_date")
    return [
        {
            "date": row.acquisition_date.isoformat(),
            "value": _number(row.value),
            "z": _number(row.z),
            "baseline_median": _number(row.baseline_median),
            "baseline_mad": _number(row.baseline_mad),
            "baseline_n": int(row.baseline_n),
        }
        for row in flagged.itertuples(index=False)
    ]


def _min_z(rows: pd.DataFrame) -> dict[str, Any] | None:
    scored = rows[_scored_mask(rows)]
    if scored.empty:
        return None
    row = scored.loc[scored["z"].idxmin()]
    return {"date": row["acquisition_date"].isoformat(), "z": _number(row["z"])}


def _summary(rows: pd.DataFrame, window: Window) -> dict[str, Any]:
    reasons = Counter(str(reason) for reason in rows["reason"].dropna())
    return {
        "window": _window_json(window),
        "n_dates": int(rows["acquisition_date"].nunique()),
        "n_scored": int(_scored_mask(rows).sum()),
        "reasons": dict(sorted(reasons.items())),
        "flags": _flag_records(rows),
        "min_z": _min_z(rows),
    }


def verdict_h1(scores: pd.DataFrame) -> dict[str, Any]:
    """Forrestdale low water: supported on at least one low flag."""
    rows = _rows_in_window(scores, H1_WINDOW)
    result = _summary(rows, H1_WINDOW)
    if _low_mask(rows).any():
        result["verdict"] = SUPPORTED
    elif result["n_scored"] > 0:
        result["verdict"] = NOT_SUPPORTED
    else:
        result["verdict"] = UNTESTABLE
    return result


def verdict_h2(scores: pd.DataFrame) -> dict[str, Any]:
    """Forrestdale no anomaly: scored and no water flag of either sign."""
    rows = _rows_in_window(scores, H2_WINDOW)
    result = _summary(rows, H2_WINDOW)
    if rows["flagged"].astype(bool).any():
        result["verdict"] = NOT_SUPPORTED
    elif result["n_scored"] > 0:
        result["verdict"] = SUPPORTED
    else:
        result["verdict"] = UNTESTABLE
    return result


def _h3_polygon(rows: pd.DataFrame) -> dict[str, Any]:
    scored = rows[_scored_mask(rows)]
    delta = scored["value"] - scored["baseline_median"]
    median_delta = _number(delta.median()) if len(delta) else None
    low_flags = int(_low_mask(rows).sum())
    meets = median_delta is not None and median_delta >= 0 and low_flags == 0
    monthly: dict[str, Any] = {}
    months = rows.assign(
        month=[day.strftime("%Y-%m") for day in rows["acquisition_date"]]
    )
    for month, group in months.groupby("month", sort=True):
        in_month = group[_scored_mask(group)]
        month_delta = in_month["value"] - in_month["baseline_median"]
        monthly[str(month)] = {
            "n_dates": int(group["acquisition_date"].nunique()),
            "n_scored": int(len(in_month)),
            "median_delta": _number(month_delta.median()) if len(in_month) else None,
        }
    return {
        "n_scored": int(len(scored)),
        "median_delta": median_delta,
        "share_at_or_above_baseline": (
            _number((delta >= 0).mean()) if len(delta) else None
        ),
        "low_flags": low_flags,
        "meets_rule": meets,
        "monthly": monthly,
    }


def verdict_h3(scores_56: pd.DataFrame, scores_52: pd.DataFrame) -> dict[str, Any]:
    """Winter water at or above baseline in both polygons."""
    per_polygon: dict[str, dict[str, Any]] = {}
    reasons: Counter[str] = Counter()
    flags: list[dict[str, Any]] = []
    n_dates = 0
    min_z: dict[str, Any] | None = None
    for polygon, scores in ((FORRESTDALE, scores_56), (THOMSONS, scores_52)):
        rows = _rows_in_window(scores, H3_WINDOW)
        summary = _summary(rows, H3_WINDOW)
        per_polygon[polygon] = {
            "n_dates": summary["n_dates"],
            "reasons": summary["reasons"],
            "flags": summary["flags"],
            "min_z": summary["min_z"],
            **_h3_polygon(rows),
        }
        n_dates += summary["n_dates"]
        reasons.update(summary["reasons"])
        flags.extend({"polygon_id": polygon, **flag} for flag in summary["flags"])
        candidate = summary["min_z"]
        if candidate is not None and (min_z is None or candidate["z"] < min_z["z"]):
            min_z = {"polygon_id": polygon, **candidate}
    fails = [
        entry
        for entry in per_polygon.values()
        if entry["n_scored"] > 0 and not entry["meets_rule"]
    ]
    if fails:
        verdict = NOT_SUPPORTED
    elif all(entry["n_scored"] > 0 for entry in per_polygon.values()):
        verdict = SUPPORTED
    else:
        verdict = UNTESTABLE
    return {
        "verdict": verdict,
        "window": _window_json(H3_WINDOW),
        "n_dates": n_dates,
        "n_scored": sum(entry["n_scored"] for entry in per_polygon.values()),
        "reasons": dict(sorted(reasons.items())),
        "flags": flags,
        "min_z": min_z,
        "polygons": per_polygon,
    }


def verdict_h4(lakes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Every scored lake has rho of at least `RHO_MIN`; unscored lakes are ignored."""
    scored = [lake for lake in lakes if lake["scored"] and lake["rho"] is not None]
    failing = [lake["lake"] for lake in scored if lake["rho"] < RHO_MIN]
    if failing:
        verdict = NOT_SUPPORTED
    elif scored:
        verdict = SUPPORTED
    else:
        verdict = UNTESTABLE
    return {
        "verdict": verdict,
        "rho_min": RHO_MIN,
        "n_lakes": len(lakes),
        "n_scored": len(scored),
        "failing": failing,
        "rho": {str(lake["lake"]): lake["rho"] for lake in scored},
    }


# --- comparison and CSV -----------------------------------------------------


def _change_keys(frame: pd.DataFrame) -> set[tuple[Any, ...]]:
    return {
        (str(row.polygon_id), str(row.item_id), str(row.metric), round(float(row.z), 6))
        for row in frame.itertuples(index=False)
    }


def compare_changes(
    rescored_flagged: pd.DataFrame, change_rows: pd.DataFrame
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """Rows only in the rescore, then rows only in the stored change files."""
    expected = _change_keys(rescored_flagged)
    stored = _change_keys(change_rows)
    return sorted(expected - stored), sorted(stored - expected)


def _join_ids(value: Any) -> Any:
    if isinstance(value, list | tuple | np.ndarray):
        return ";".join(str(item) for item in value)
    return value


def frame_to_csv(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    """Sorted CSV text with `columns`; a header line alone when there are no rows."""
    out = frame.loc[:, list(columns)].copy()
    if "item_ids" in out.columns and len(out):
        out["item_ids"] = out["item_ids"].map(_join_ids)
    if len(out):
        out = out.sort_values(["polygon_id", "datetime", "metric"], kind="stable")
    return out.to_csv(index=False, lineterminator="\n")


# --- shared helpers ---------------------------------------------------------


def parse_day(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)


def range_bounds(start: str, end: str) -> tuple[datetime, datetime]:
    """Midnight UTC of start and the last microsecond of end, as the CLI does."""
    first = parse_day(start)
    last = parse_day(end).replace(hour=23, minute=59, second=59, microsecond=999999)
    if last < first:
        raise SystemExit("--end is before --start")
    return first, last


def clean(value: Any) -> Any:
    """Make a value strict-JSON safe: ISO dates, NaN as null, numpy as Python."""
    if isinstance(value, Mapping):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return [clean(item) for item in value.tolist()]
    if isinstance(value, datetime | date | pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(clean(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def git_head() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def search_range(
    cfg: PipelineConfig,
    polygons: list[AoiPolygon],
    start_dt: datetime,
    end_dt: datetime,
) -> Discovery:
    """A fresh Earth Search with the CLI's polygon set and no ledger."""
    return discover(
        open_client(cfg.stac.endpoint),
        cfg.stac,
        bbox=union_bbox_4326(polygons),
        polygons_4326=[polygon.geometry_4326 for polygon in polygons],
        created_from=None,
        seen=set(),
        datetime_range=(start_dt, end_dt),
    )


def search_unfiltered(
    cfg: PipelineConfig,
    polygons: list[AoiPolygon],
    start_dt: datetime,
    end_dt: datetime,
) -> list[dict[str, Any]]:
    """Every collection item over the polygons in the range, with no cloud filter.

    `build_search_kwargs` sends the cloud filter to the server, so `Discovery`
    never sees the items it excludes. This search drops the `query` filter and
    re-checks the acquisition window and footprint locally.
    """
    kwargs = build_search_kwargs(
        cfg.stac,
        bbox=union_bbox_4326(polygons),
        created_from=None,
        datetime_range=(start_dt, end_dt),
    )
    kwargs.pop("query")
    client = open_client(cfg.stac.endpoint)
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for item in client.search(**kwargs).items_as_dicts():
        item_id = str(item.get("id"))
        props: Mapping[str, Any] = item.get("properties", {})
        if item_id in seen:
            continue
        seen.add(item_id)
        acquired = datetime.fromisoformat(str(props["datetime"]).replace("Z", "+00:00"))
        if not start_dt <= acquired <= end_dt:
            continue
        footprint = shape(item["geometry"])
        if not any(footprint.intersects(p.geometry_4326) for p in polygons):
            continue
        cloud = props.get("eo:cloud_cover")
        items.append(
            {
                "item_id": item_id,
                "datetime": acquired.isoformat(),
                "cloud_cover": None if cloud is None else float(cloud),
            }
        )
    return sorted(items, key=lambda i: (i["datetime"], i["item_id"]))


def search_reference(
    cfg: PipelineConfig,
    polygons: list[AoiPolygon],
    start_dt: datetime,
    end_dt: datetime,
) -> tuple[dict[str, Any], list[str]]:
    """Reference counts and ids from a fresh search over the range."""
    found = search_range(cfg, polygons, start_dt, end_dt)
    ids = sorted(
        {scene.item_id for scene in found.scenes}
        | {item_id for item_id, _reason in found.rejected}
    )
    summary = {
        "reference_count": len(found.scenes) + len(found.rejected),
        # Results of the cloud-filtered search (the server applies the cloud
        # filter), not the full catalogue count.
        "raw_count": len(found.scenes) + len(found.rejected) + found.skipped_filter,
        "skipped_filter": found.skipped_filter,
        "rejected_count": len(found.rejected),
        "searched_at": datetime.now(UTC).isoformat(),
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }
    return summary, ids


def cmd_reference(args: argparse.Namespace) -> int:
    start_dt, end_dt = range_bounds(args.start, args.end)
    cfg, polygons = _load(Path(args.config))
    summary, ids = search_reference(cfg, polygons, start_dt, end_dt)
    write_json(Path(args.out), {**summary, "ids": ids})
    Path(args.count_out).write_text(f"{summary['reference_count']}\n", encoding="utf-8")
    return 0


# --- analyse ----------------------------------------------------------------


def rescore(
    observations: pd.DataFrame,
    *,
    min_valid_fraction: float,
    first: date,
    last: date,
) -> pd.DataFrame:
    """Replicate `score_changes` per date for the two polygons, over the range."""
    frame = pd.DataFrame(observations.drop(columns="geometry"))
    frame["acq_date"] = frame["datetime"].dt.tz_convert(UTC).dt.date
    parts: list[pd.DataFrame] = []
    for polygon in POLYGONS:
        rows = frame[frame["polygon_id"] == polygon]
        for day in sorted(rows["acq_date"].unique()):
            if not first <= day <= last:
                continue
            day_rows = rows[rows["acq_date"] == day]
            history = rows[
                (rows["acq_date"] < day) & (rows["datetime"].dt.month == day.month)
            ]
            baseline = build_baseline(history, min_valid_fraction=min_valid_fraction)
            parts.append(
                score_observations(
                    day_rows, baseline, min_valid_fraction=min_valid_fraction
                )
            )
    if not parts:
        return pd.DataFrame(columns=list(SCORE_COLUMNS))
    scores = pd.concat(parts, ignore_index=True)
    scores = scores[scores["metric"].isin(METRICS)]
    return scores.reset_index(drop=True)


def read_change_rows(store: OutputStore, *, first: date, last: date) -> pd.DataFrame:
    """Stored change rows of the two polygons inside the range, geometry dropped."""
    paths = [
        path
        for path in store.list_files("changes")
        if path.rsplit("/", 1)[-1].startswith("chg_") and path.endswith(".parquet")
    ]
    frames = [
        pd.DataFrame(
            gpd.read_parquet(BytesIO(store.read_bytes(path))).drop(columns="geometry")
        )
        for path in paths
    ]
    if not frames:
        return pd.DataFrame(columns=list(CHANGE_COLUMNS))
    rows = pd.concat(frames, ignore_index=True)
    days = rows["datetime"].dt.tz_convert(UTC).dt.date
    keep = rows["polygon_id"].isin(POLYGONS) & (days >= first) & (days <= last)
    return rows[keep].reset_index(drop=True)


def ledger_evidence(
    store: OutputStore, reference: Mapping[str, Any], ids: Sequence[str]
) -> dict[str, Any]:
    table = read_ledger(store)
    latest = latest_entries(table)
    latest_ids = set(latest["item_id"]) if len(latest) else set()
    reference_ids = set(ids)
    in_reference = latest_ids & reference_ids
    failed = latest[latest["status"] == "failed"] if len(latest) else latest
    return {
        "latest_items": len(latest_ids),
        "in_reference": len(in_reference),
        "coverage": len(in_reference) / reference["reference_count"]
        if reference["reference_count"]
        else None,
        "raw_coverage": len(in_reference) / reference["raw_count"]
        if reference["raw_count"]
        else None,
        "by_status": dict(Counter(latest["status"])) if len(latest) else {},
        "not_in_reference": sorted(latest_ids - reference_ids),
        "missing_from_ledger": sorted(reference_ids - latest_ids),
        "failed": [
            {"id": row.item_id, "error": row.error, "attempts": int(row.attempts)}
            for row in failed.sort_values("item_id").itertuples(index=False)
        ],
        "exhausted": len(exhausted_keys(table)),
    }


SECONDS_PATTERN: Final = re.compile(
    r"\bchunk=\S+ lane=\d+ pass=\d+ rc=\d+ secs=(\d+)\b"
)


def backfill_seconds(progress_log: Path) -> dict[str, Any]:
    """Wall seconds of the `backfill` calls, from the driver's progress.log.

    The driver logs `secs=` for each call. The run manifests cannot give this,
    because `backfill_once` stamps `started_at` and `finished_at` with the same
    `--now`. The sum is across lanes, so it is runner time, not elapsed time.
    """
    seconds = [
        int(match.group(1))
        for line in progress_log.read_text(encoding="utf-8").splitlines()
        if (match := SECONDS_PATTERN.search(line))
    ]
    return {"calls": len(seconds), "seconds_sum": sum(seconds)}


def runs_evidence(store: OutputStore, progress_log: Path | None) -> dict[str, Any]:
    manifests = []
    for path in store.list_files("runs"):
        if path.endswith(".json"):
            data = json.loads(store.read_bytes(path))
            if data.get("kind") == "backfill":
                manifests.append(data)
    processed = sum(int(item.get("processed", 0)) for item in manifests)
    starts = [manifest["started_at"] for manifest in manifests]
    evidence: dict[str, Any] = {
        "manifests": len(manifests),
        "processed_sum": processed,
        "failed_attempts_sum": sum(int(item.get("failed", 0)) for item in manifests),
        "rejected_sum": sum(int(item.get("rejected", 0)) for item in manifests),
        "first_started_at": min(starts, key=datetime.fromisoformat) if starts else None,
        "backfill_calls": None,
        "backfill_seconds_sum": None,
        "seconds_per_processed_scene": None,
    }
    if progress_log is not None:
        timing = backfill_seconds(progress_log)
        evidence["backfill_calls"] = timing["calls"]
        evidence["backfill_seconds_sum"] = timing["seconds_sum"]
        if processed:
            evidence["seconds_per_processed_scene"] = timing["seconds_sum"] / processed
    return evidence


def cached(loader: Callable[[str], pd.DataFrame]) -> Callable[[str], pd.DataFrame]:
    store: dict[str, pd.DataFrame] = {}

    def load(uid: str) -> pd.DataFrame:
        if uid not in store:
            store[uid] = loader(uid)
        return store[uid]

    return load


def dea_wet_fraction(
    series_loader: Callable[[str], pd.DataFrame], window: Window
) -> list[dict[str, Any]]:
    series = series_loader(FORRESTDALE_UID)
    days = series["date"].dt.tz_convert(UTC).dt.date
    keep = (days >= window[0]) & (days <= window[1])
    return [
        {"date": day.isoformat(), "wet_fraction": _number(fraction)}
        for day, fraction in zip(
            days[keep], series.loc[keep, "wet_fraction"], strict=True
        )
    ]


def retrospective(
    observations: pd.DataFrame, scores_56: pd.DataFrame, *, min_valid_fraction: float
) -> list[dict[str, Any]]:
    """Descriptive z of Forrestdale H2 dates against same-month rows of other years.

    Not a verdict and not ADR 0004: the baseline includes later dates.
    """
    frame = pd.DataFrame(observations.drop(columns="geometry"))
    rows = frame[frame["polygon_id"] == FORRESTDALE]
    other = rows[rows["datetime"].dt.tz_convert(UTC).dt.year != 2023]
    baseline = build_baseline(other, min_valid_fraction=min_valid_fraction)
    water = baseline[baseline["metric"] == WATER].set_index("month")
    out: list[dict[str, Any]] = []
    for row in _rows_in_window(scores_56, H2_WINDOW).itertuples(index=False):
        month = row.acquisition_date.month
        median = mad = z = None
        sample_count = 0
        if month in water.index:
            median = _number(water.loc[month, "baseline_median"])
            mad = _number(water.loc[month, "baseline_mad"])
            sample_count = int(water.loc[month, "baseline_n"])
            value = _number(row.value)
            if value is not None and median is not None and mad:
                z = (value - median) / mad
        out.append(
            {
                "date": row.acquisition_date.isoformat(),
                "value": _number(row.value),
                "median": median,
                "mad": mad,
                "n": sample_count,
                "z": z,
            }
        )
    return out


def lake_evidence(checks: Sequence[Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lakes: list[dict[str, Any]] = []
    per_pass: dict[str, dict[str, Any]] = {}
    for check in checks:
        uid = str(check.detail.get("uid"))
        lake = str(check.detail.get("lake", uid))
        if check.name == SPEARMAN_CHECK_NAME:
            lakes.append(
                {
                    "lake": lake,
                    "uid": uid,
                    "rho": check.measured,
                    "n_pairs": check.detail.get("n_pairs"),
                    "n_unpaired": check.detail.get("n_unpaired"),
                    "passed": check.passed,
                    "reason": check.detail.get("reason"),
                    "scored": check.measured is not None
                    and check.detail.get("reason") is None,
                }
            )
        elif check.name == CHECK_NAME:
            entry = per_pass.setdefault(
                lake, {"pass": 0, "fail": 0, "skip": 0, "_diffs": []}
            )
            if check.passed is None:
                entry["skip"] += 1
            else:
                entry["pass" if check.passed else "fail"] += 1
                entry["_diffs"].append(float(check.measured))
    for entry in per_pass.values():
        diffs = entry.pop("_diffs")
        entry["median_abs_diff_pp"] = float(np.median(diffs)) if diffs else None
    first = {"Forrestdale Lake": 0, "Thomsons Lake": 1}
    lakes.sort(key=lambda entry: (first.get(entry["lake"], 2), entry["lake"]))
    return lakes, per_pass


def unavailable_lakes(lakes: Sequence[Mapping[str, Any]]) -> list[str]:
    """Lakes whose DEA series could not be fetched.

    `verdict_h4` ignores an unscored lake, so one failed fetch could flip H4.
    A rerun is the remedy, not a verdict.
    """
    return [
        str(lake["lake"]) for lake in lakes if lake.get("reason") == SERIES_UNAVAILABLE
    ]


def cmd_analyse(args: argparse.Namespace) -> int:
    config = Path(args.config)
    start_dt, end_dt = range_bounds(args.start, args.end)
    first, last = start_dt.date(), end_dt.date()
    cfg, polygons = _load(config)
    store = OutputStore(args.output_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    observations = read_observations(store)
    min_valid = cfg.water.min_valid_fraction
    scores = rescore(observations, min_valid_fraction=min_valid, first=first, last=last)
    changes = read_change_rows(store, first=first, last=last)
    flagged = scores[scores["flagged"].astype(bool)]
    missing, extra = compare_changes(flagged, changes)
    matched = not missing and not extra
    if not matched and not args.skip_change_check:
        print(f"missing from change files ({len(missing)}): {missing}", file=sys.stderr)
        print(f"extra in change files ({len(extra)}): {extra}", file=sys.stderr)

    reference, ids = search_reference(cfg, polygons, start_dt, end_dt)
    series_loader = cached(fetch_series)
    lakes_aoi = load_waterbodies(
        cfg.aoi.waterbodies_path, operation_epsg=cfg.aoi.operation_epsg
    )
    checks = waterbody_checks(
        read_lake_observations(store),
        series_loader,
        lakes_aoi,
        cfg=cfg.verify.waterbodies,
        min_valid_fraction=min_valid,
        start=first,
        end=last,
    )
    lakes, per_pass = lake_evidence(checks)
    unavailable = unavailable_lakes(lakes)
    if unavailable:
        print(
            f"DEA series unavailable for {unavailable}; no evidence written, rerun",
            file=sys.stderr,
        )
        return 2

    scores_56 = scores[scores["polygon_id"] == FORRESTDALE]
    scores_52 = scores[scores["polygon_id"] == THOMSONS]
    h1 = verdict_h1(scores_56)
    h1["dea_wet_fraction"] = dea_wet_fraction(series_loader, H1_WINDOW)
    h2 = verdict_h2(scores_56)
    h2["retrospective"] = retrospective(
        observations, scores_56, min_valid_fraction=min_valid
    )
    h2["ndvi_flags"] = _flag_records(_rows_in_window(scores_56, H2_WINDOW, NDVI))
    forrestdale = [polygon for polygon in polygons if polygon.polygon_id == FORRESTDALE]
    if len(forrestdale) != 1:
        raise SystemExit(
            f"expected one {FORRESTDALE} polygon, found {len(forrestdale)}"
        )
    old = search_range(
        cfg,
        forrestdale,
        datetime(2022, 2, 1, tzinfo=UTC),
        datetime(2022, 4, 30, 23, 59, 59, 999999, tzinfo=UTC),
    )
    # Items that cover Forrestdale and pass the pipeline's cloud filter, as
    # the reference count does. The unfiltered list below is a separate search
    # without the server-side cloud filter, so it shows what the filter hides.
    h2["c1_items_feb_apr_2022"] = len(old.scenes) + len(old.rejected)
    unfiltered = search_unfiltered(
        cfg,
        forrestdale,
        datetime(2022, 2, 1, tzinfo=UTC),
        datetime(2022, 4, 30, 23, 59, 59, 999999, tzinfo=UTC),
    )
    h2["c1_items_feb_apr_2022_unfiltered"] = len(unfiltered)
    h2["c1_items_feb_apr_2022_excluded_by_cloud_filter"] = [
        item
        for item in unfiltered
        if item["cloud_cover"] is None
        or item["cloud_cover"] >= cfg.stac.cloud_cover_max
    ]
    h2["untestable_2022_half"] = h2["c1_items_feb_apr_2022"] == 0
    h3 = verdict_h3(scores_56, scores_52)
    h4 = verdict_h4(lakes)
    h4["lakes"] = lakes
    h4["per_pass"] = per_pass

    evidence = {
        "range": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
        "date": args.date,
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "git_head": git_head(),
        "reference": reference,
        "ledger": ledger_evidence(store, reference, ids),
        "runs": runs_evidence(
            store, Path(args.progress_log) if args.progress_log else None
        ),
        "change_rows": (
            {
                polygon: int((changes["polygon_id"] == polygon).sum())
                for polygon in POLYGONS
            }
        ),
        "self_check": {
            "ran": not args.skip_change_check,
            "matched": None if args.skip_change_check else matched,
        },
        "h1": h1,
        "h2": h2,
        "h3": h3,
        "h4": h4,
    }
    prefix = out_dir / f"{args.date}-backfill"
    Path(f"{prefix}-changes.csv").write_text(
        frame_to_csv(changes, CHANGE_COLUMNS), encoding="utf-8"
    )
    Path(f"{prefix}-scores.csv").write_text(
        frame_to_csv(scores, SCORE_COLUMNS), encoding="utf-8"
    )
    write_json(Path(f"{prefix}-evidence.json"), evidence)
    return 1 if not matched and not args.skip_change_check else 0


# --- selftest ---------------------------------------------------------------


def _row(
    day: date,
    *,
    z: float | None = 0.5,
    flagged: bool = False,
    reason: str | None = None,
    value: float = 10.0,
    baseline_median: float = 9.0,
    metric: str = WATER,
) -> dict[str, Any]:
    return {
        "acquisition_date": day,
        "metric": metric,
        "value": value,
        "baseline_median": baseline_median,
        "baseline_mad": 1.0,
        "baseline_n": 6,
        "z": np.nan if z is None else z,
        "flagged": flagged,
        "reason": reason,
    }


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _unscored(day: date) -> dict[str, Any]:
    return _row(day, z=None, reason="too_few_samples")


def _selftest_h1() -> None:
    day = date(2023, 12, 10)
    assert verdict_h1(_frame([_unscored(day)]))["verdict"] == UNTESTABLE
    assert verdict_h1(_frame([_row(day)]))["verdict"] == NOT_SUPPORTED
    high = _frame([_row(day), _row(date(2023, 12, 15), z=4.0, flagged=True)])
    assert verdict_h1(high)["verdict"] == NOT_SUPPORTED
    low = _frame([_row(day), _row(date(2023, 12, 15), z=-4.0, flagged=True)])
    result = verdict_h1(low)
    assert result["verdict"] == SUPPORTED
    assert result["n_scored"] == 2 and len(result["flags"]) == 1
    outside = _frame([_row(day), _row(date(2024, 2, 1), z=-4.0, flagged=True)])
    assert verdict_h1(outside)["verdict"] == NOT_SUPPORTED
    only_outside = _frame([_row(date(2024, 2, 1), z=-4.0, flagged=True)])
    assert verdict_h1(only_outside)["verdict"] == UNTESTABLE


def _selftest_h2() -> None:
    day = date(2023, 3, 10)
    assert verdict_h2(_frame([_unscored(day)]))["verdict"] == UNTESTABLE
    assert verdict_h2(_frame([_row(day)]))["verdict"] == SUPPORTED
    high = _frame([_row(day), _row(date(2023, 3, 17), z=4.0, flagged=True)])
    assert verdict_h2(high)["verdict"] == NOT_SUPPORTED
    low = _frame([_row(day), _row(date(2023, 3, 17), z=-4.0, flagged=True)])
    assert verdict_h2(low)["verdict"] == NOT_SUPPORTED
    ndvi = _frame(
        [
            _row(day),
            _row(day, z=5.0, flagged=True, metric=NDVI),
            _unscored(date(2023, 3, 12)),
        ]
    )
    result = verdict_h2(ndvi)
    assert result["verdict"] == SUPPORTED
    assert result["reasons"] == {"too_few_samples": 1}


def _h3_series(deltas: list[float], *, low_flag: bool = False) -> pd.DataFrame:
    rows = []
    for i, delta in enumerate(deltas):
        rows.append(
            _row(
                date(2025, 6, 1 + i),
                value=9.0 + delta,
                baseline_median=9.0,
                z=delta,
                flagged=low_flag and i == 0,
            )
        )
    return _frame(rows)


def _selftest_h3() -> None:
    meets = _h3_series([1.0, -0.5, 2.0])
    zero = _h3_series([-1.0, 0.0, 1.0])
    negative = _h3_series([-1.0, -0.5, 0.5])
    flagged = _h3_series([1.0, 2.0, 3.0])
    flagged.loc[0, ["z", "flagged"]] = [-4.0, True]
    none = _frame([_unscored(date(2025, 6, 5))])
    assert verdict_h3(meets, meets)["verdict"] == SUPPORTED
    result = verdict_h3(meets, zero)
    assert result["verdict"] == SUPPORTED
    assert result["polygons"][THOMSONS]["median_delta"] == 0.0
    assert result["polygons"][THOMSONS]["meets_rule"] is True
    assert verdict_h3(meets, negative)["verdict"] == NOT_SUPPORTED
    assert verdict_h3(flagged, meets)["verdict"] == NOT_SUPPORTED
    assert verdict_h3(none, meets)["verdict"] == UNTESTABLE
    assert verdict_h3(meets, none)["verdict"] == UNTESTABLE
    assert verdict_h3(none, negative)["verdict"] == NOT_SUPPORTED
    assert verdict_h3(none, none)["verdict"] == UNTESTABLE


def _lake(rho: float | None, scored: bool = True, name: str = "L") -> dict[str, Any]:
    return {"lake": name, "rho": rho, "scored": scored}


def _selftest_h4() -> None:
    assert verdict_h4([])["verdict"] == UNTESTABLE
    assert verdict_h4([_lake(None, False)])["verdict"] == UNTESTABLE
    assert verdict_h4([_lake(0.95), _lake(0.9)])["verdict"] == SUPPORTED
    assert verdict_h4([_lake(0.95), _lake(0.89)])["verdict"] == NOT_SUPPORTED
    assert verdict_h4([_lake(0.95), _lake(0.1, False)])["verdict"] == SUPPORTED


def _selftest_unavailable() -> None:
    """A failed DEA fetch must stop `analyse`, because H4 would ignore the lake."""
    cfg = WaterbodiesVerifyConfig()
    thomsons, forrestdale = "qd635epws_v3", "qd63n1ww5_v3"
    assert LAKES[thomsons] == "Thomsons Lake"
    down = _unavailable(thomsons, RuntimeError("timeout"), cfg)
    up = [
        Check(
            SPEARMAN_CHECK_NAME,
            True,
            0.95,
            cfg.spearman_min,
            "ref",
            {"uid": forrestdale, "lake": LAKES[forrestdale], "n_pairs": 20},
        )
    ]
    lakes, _ = lake_evidence([*down, *up])
    assert unavailable_lakes(lakes) == ["Thomsons Lake"]
    by_name = {lake["lake"]: lake for lake in lakes}
    assert not by_name["Thomsons Lake"]["scored"]
    assert by_name["Forrestdale Lake"]["scored"]
    assert verdict_h4(lakes)["verdict"] == SUPPORTED  # why the guard is needed
    assert unavailable_lakes(lake_evidence(up)[0]) == []
    low = [
        Check(
            SPEARMAN_CHECK_NAME,
            False,
            0.4,
            cfg.spearman_min,
            "ref",
            {"uid": thomsons, "lake": LAKES[thomsons], "n_pairs": 20},
        )
    ]
    assert unavailable_lakes(lake_evidence(low)[0]) == []  # a low rho is a verdict


def _selftest_progress_log() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "progress.log"
        stamp = "2026-11-03T01:00:00Z"
        lines = [
            f"{stamp} driver start pid=1 end_date=2026-11-02",
            f"{stamp} chunk=2022-12-01..2022-12-31 lane=0 pass=1 rc=0 secs=600",
            f"{stamp} chunk=2023-01-01..2023-03-31 lane=1 pass=1 rc=2 secs=125",
            f"{stamp} chunk=2023-01-01..2023-03-31 lane=1 pass=2 rc=0 secs=75",
            f"{stamp} chunk=2023-04-01..2023-06-30 lane=0 GAVE_UP rc=2",
        ]
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert backfill_seconds(log) == {"calls": 3, "seconds_sum": 800}


def _selftest_compare_and_csv() -> None:
    base = pd.DataFrame(
        {
            "polygon_id": ["ramsar-56", "ramsar-52"],
            "item_id": ["a", "b"],
            "metric": [WATER, NDVI],
            "z": [-3.5, 4.1234567],
        }
    )
    same = base.copy()
    same.loc[1, "z"] = 4.1234568  # equal after rounding to 6 places
    assert compare_changes(base, same) == ([], [])
    extra = pd.concat([same, base.iloc[[0]].assign(item_id="c")], ignore_index=True)
    missing, added = compare_changes(base, extra)
    assert missing == [] and added == [("ramsar-56", "c", WATER, -3.5)]
    missing, added = compare_changes(extra, base)
    assert missing == [("ramsar-56", "c", WATER, -3.5)] and added == []
    empty = pd.DataFrame(columns=list(CHANGE_COLUMNS))
    text = frame_to_csv(empty, CHANGE_COLUMNS)
    assert text == ",".join(CHANGE_COLUMNS) + "\n", repr(text)


def selftest() -> int:
    for case in (
        _selftest_h1,
        _selftest_h2,
        _selftest_h3,
        _selftest_h4,
        _selftest_unavailable,
        _selftest_progress_log,
        _selftest_compare_and_csv,
    ):
        case()
    print("selftest ok")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest", help="run the verdict cases; no network, no files")

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--start", default=DEFAULT_START, help="first UTC date")
        p.add_argument("--end", required=True, help="last UTC date, inclusive")
        p.add_argument("--config", default="config/pipeline.toml")

    ref = sub.add_parser("reference", help="search Earth Search for the id list")
    common(ref)
    ref.add_argument("--out", required=True, help="JSON file for the reference")
    ref.add_argument("--count-out", required=True, help="file for the integer count")

    ana = sub.add_parser("analyse", help="rescore, compare and write the evidence")
    common(ana)
    ana.add_argument("--output-root", required=True)
    ana.add_argument("--out-dir", required=True)
    ana.add_argument("--date", required=True, help="filename prefix")
    ana.add_argument("--skip-change-check", action="store_true")
    ana.add_argument(
        "--progress-log",
        help="the driver's progress.log; its secs= fields give the backfill time",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "selftest":
        return selftest()
    if args.command == "reference":
        return cmd_reference(args)
    return cmd_analyse(args)


if __name__ == "__main__":
    sys.exit(main())
