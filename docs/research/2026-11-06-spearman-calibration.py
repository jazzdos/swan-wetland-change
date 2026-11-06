"""Read-only: whole-history per-lake Spearman rho from the gate's own code path.

Calibrates `spearman_min` (ADR 0005 rule: lowest pooled value minus 0.02, rounded
down to two decimals) and reconciles the gate with the H4 numbers in LEARNINGS.md.

  uv run python docs/research/2026-11-06-spearman-calibration.py \
      [--data-root DIR] [--out CSV] [--report TXT]

Per lake it scores every stored observation up to the newest scene, exactly as
`verify_run` does: `_history_paths` intersected with the `observations` listing,
`read_observations`, then `waterbody_checks(..., history=...)`. It also computes:

- `range_*`: the same gate code on the history rows dated 2022-12-01 to 2026-11-02
  (the H4 range), to separate the effect of the range from the effect of the
  pairing rule.
- `legacy_*`: the pairing before commit 00e8fb0 (datetime-only de-duplication by
  highest `scene_coverage`, same filters and `max_day_gap` pairing) over the H4
  range, scored with the module's `spearman_check`.

Only read paths are called: `read_ledger`, `OutputStore.list_files`,
`read_observations` and `fetch_series` (an anonymous read of public DEA data).
It never calls `verify_run`, which writes a report. Output goes to `--out` and
`--report` only. The CSV holds no fetch time, so it is deterministic for a given
backfill and DEA series.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
from datetime import date
from pathlib import Path
from typing import Final, NamedTuple

import numpy as np
import pandas as pd

from wetland_change.aoi import load_waterbodies
from wetland_change.change import FULL_COVERAGE
from wetland_change.config import WaterbodiesVerifyConfig, load_config
from wetland_change.ledger import latest_entries, read_ledger
from wetland_change.store import OutputStore
from wetland_change.verify.run import _history_paths
from wetland_change.verify.waterbodies import (
    LAKES,
    SPEARMAN_CHECK_NAME,
    _day_numbers,
    _paired_passes,
    fetch_series,
    read_observations,
    spearman_check,
    waterbody_checks,
)

REPO: Final = Path(__file__).resolve().parents[2]
HERE: Final = Path(__file__).resolve().parent
DEFAULT_DATA: Final = Path("/Users/jarrodbaker/Documents/swan-wetland-change-data")
H4_START: Final = date(2022, 12, 1)
H4_END: Final = date(2026, 11, 2)
ADR_MARGIN: Final = 0.02
WINDOW_FILES: Final = (
    "2026-11-05-spearman-windows.py",
    "2026-11-05-spearman-windows.csv",
)
FIELDS: Final = (
    "uid",
    "lake",
    "rho",
    "n_pairs",
    "n_unpaired",
    "first_datetime",
    "last_datetime",
    "legacy_rho",
    "legacy_n_pairs",
    "legacy_n_unpaired",
    "range_rho",
    "range_n_pairs",
    "range_n_unpaired",
    "n_rows_history",
    "n_rows_datetime_dedupe",
    "n_rows_tile_date_dedupe",
    "n_dropped_by_tile_date_dedupe",
    "n_outside_range",
    "dea_series_rows",
    "dea_series_last_date",
    "files_read",
    "bytes_read",
)


class H4Reported(NamedTuple):
    """H4 line of LEARNINGS.md, "Backfill hypotheses (2026-11-03)", report fc9f4ba."""

    rho: float
    n_pairs: int


class LakeScore(NamedTuple):
    rho: float | None
    n_pairs: int
    n_unpaired: int


H4_REPORTED: Final = {
    "qd63n1ww5_v3": H4Reported(0.870, 93),
    "qd635epws_v3": H4Reported(0.897, 99),
    "qd4m2n3rj_v3": H4Reported(0.858, 98),
    "qd4k2967m_v3": H4Reported(0.861, 98),
}


def _in_range(frame: pd.DataFrame) -> pd.DataFrame:
    days = frame["datetime"].dt.tz_convert("UTC").dt.date
    return frame[(days >= H4_START) & (days <= H4_END)]


def _datetime_dedupe(rows: pd.DataFrame) -> pd.DataFrame:
    """Pre-00e8fb0 rule: one row per datetime, the highest `scene_coverage`."""
    return (
        rows.sort_values(["datetime", "scene_coverage"], ascending=[True, False])
        .drop_duplicates("datetime", keep="first")
        .reset_index(drop=True)
    )


def _legacy_score(
    uid: str,
    rows: pd.DataFrame,
    dea: pd.DataFrame,
    *,
    min_valid_fraction: float,
    cfg: WaterbodiesVerifyConfig,
) -> LakeScore:
    """Pre-00e8fb0 pairing of `rows` (already narrowed to the range) with DEA."""
    dea = dea.sort_values("date").reset_index(drop=True)
    dea_days = _day_numbers(dea["date"]) if len(dea) else np.empty(0, dtype=np.int64)
    pipeline: list[float] = []
    reference: list[float] = []
    n_unpaired = 0
    for row in _datetime_dedupe(rows).itertuples(index=False):
        day = int(_day_numbers(pd.Series([pd.Timestamp(row.datetime)]))[0])
        if dea_days.size == 0:
            n_unpaired += 1
            continue
        nearest = int(np.argmin(np.abs(dea_days - day)))
        if abs(int(dea_days[nearest]) - day) > cfg.max_day_gap:
            n_unpaired += 1
            continue
        coverage = float(row.scene_coverage)
        valid = float(row.valid_fraction)
        water_ha = float(row.water_ha_index)
        if not math.isfinite(coverage) or coverage < FULL_COVERAGE:
            continue
        if not math.isfinite(valid) or valid < min_valid_fraction:
            continue
        if not math.isfinite(water_ha):
            continue
        pipeline.append(water_ha)
        reference.append(float(dea.iloc[nearest]["wet_fraction"]))
    check = spearman_check(
        uid,
        pipeline,
        reference,
        cfg=cfg,
        n_unpaired=n_unpaired,
    )
    return LakeScore(check.measured, len(pipeline), n_unpaired)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(value: float | None) -> str:
    return "" if value is None else repr(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Whole-history Spearman calibration")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA)
    parser.add_argument(
        "--out", type=Path, default=HERE / "2026-11-06-spearman-calibration.csv"
    )
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    report_path = args.report or args.out.with_suffix(".txt")

    config = load_config(REPO / "config" / "pipeline.toml")
    waterbodies = config.verify.waterbodies
    min_valid = config.water.min_valid_fraction
    outputs = args.data_root / "outputs"
    store = OutputStore(str(outputs))
    ledger = read_ledger(store)
    polygons = load_waterbodies(
        args.data_root / "aoi" / "dea_waterbodies_v3_swan.geojson",
        operation_epsg=config.aoi.operation_epsg,
    )
    by_id = {polygon.polygon_id: polygon for polygon in polygons}

    latest = latest_entries(ledger)
    succeeded = latest[
        (latest["status"] == "succeeded") & latest["observation_path"].notna()
    ]
    newest = pd.to_datetime(succeeded["datetime"], utc=True).max().to_pydatetime()

    # Exactly as verify_run: ledger paths intersected with one listing.
    stored = set(store.list_files("observations"))
    paths = sorted(_history_paths(ledger, newest=newest) & stored)
    history = read_observations(store, paths)
    bytes_read = sum(os.stat(outputs / path).st_size for path in paths)

    series_cache: dict[str, pd.DataFrame] = {}

    def series(uid: str) -> pd.DataFrame:
        if uid not in series_cache:
            series_cache[uid] = fetch_series(uid)
        return series_cache[uid]

    def gate_scores(frame: pd.DataFrame) -> dict[str, LakeScore]:
        checks = waterbody_checks(
            frame.iloc[:0],
            series,
            polygons,
            cfg=waterbodies,
            min_valid_fraction=min_valid,
            history=frame,
        )
        return {
            str(check.detail["uid"]): LakeScore(
                check.measured,
                int(str(check.detail["n_pairs"])),
                int(str(check.detail["n_unpaired"])),
            )
            for check in checks
            if check.name == SPEARMAN_CHECK_NAME
        }

    gate = gate_scores(history)
    in_range = gate_scores(_in_range(history))

    table: list[dict[str, object]] = []
    for uid in sorted(LAKES, key=lambda key: LAKES[key]):
        polygon = by_id[f"dea-{uid}"]
        mine = history[history["polygon_id"] == polygon.polygon_id]
        dea = series(uid)
        checks, pipeline_pairs, _, _ = _paired_passes(
            uid, polygon, mine, dea, cfg=waterbodies, min_valid_fraction=min_valid
        )
        scored_dates = sorted(
            str(check.detail["pipeline_date"])
            for check in checks
            if check.passed is not None
        )
        score = gate[uid]
        assert len(pipeline_pairs) == score.n_pairs, uid
        rows_after_tile_date = len(checks) + score.n_unpaired
        rows_after_datetime = len(_datetime_dedupe(mine))
        legacy = _legacy_score(
            uid,
            _in_range(mine),
            dea,
            min_valid_fraction=min_valid,
            cfg=waterbodies,
        )
        range_score = in_range[uid]
        table.append(
            {
                "uid": uid,
                "lake": LAKES[uid],
                "rho": _text(score.rho),
                "n_pairs": score.n_pairs,
                "n_unpaired": score.n_unpaired,
                "first_datetime": scored_dates[0] if scored_dates else "",
                "last_datetime": scored_dates[-1] if scored_dates else "",
                "legacy_rho": _text(legacy.rho),
                "legacy_n_pairs": legacy.n_pairs,
                "legacy_n_unpaired": legacy.n_unpaired,
                "range_rho": _text(range_score.rho),
                "range_n_pairs": range_score.n_pairs,
                "range_n_unpaired": range_score.n_unpaired,
                "n_rows_history": len(mine),
                "n_rows_datetime_dedupe": rows_after_datetime,
                "n_rows_tile_date_dedupe": rows_after_tile_date,
                "n_dropped_by_tile_date_dedupe": rows_after_datetime
                - rows_after_tile_date,
                "n_outside_range": len(mine) - len(_in_range(mine)),
                "dea_series_rows": len(dea),
                "dea_series_last_date": pd.Timestamp(dea["date"].max())
                .date()
                .isoformat(),
                "files_read": "",
                "bytes_read": "",
            }
        )
    totals: dict[str, object] = dict.fromkeys(FIELDS, "")
    totals["uid"] = "TOTAL_FILES_READ"
    totals["lake"] = "all lakes, one read of the stored history"
    totals["files_read"] = len(paths)
    totals["bytes_read"] = bytes_read
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(table)
        writer.writerow(totals)

    lowest = min(float(str(row["rho"])) for row in table if row["rho"] != "")
    proposed = math.floor((lowest - ADR_MARGIN) * 100) / 100

    lines = [
        "Spearman calibration, 2026-11-06",
        "",
        f"Newest scene: {newest.isoformat()}. Files read: {len(paths)}. "
        f"Bytes read: {bytes_read}. Lake rows in the history: {len(history)}.",
        f"max_day_gap {waterbodies.max_day_gap}, "
        f"spearman_min_pairs {waterbodies.spearman_min_pairs}, "
        f"spearman_min in config {waterbodies.spearman_min}.",
        "",
        "Gate = waterbody_checks over the whole stored history. Range = the same "
        f"code over {H4_START} to {H4_END}. Legacy = pairing before 00e8fb0 over "
        "that range. H4 = LEARNINGS.md, report fc9f4ba.",
        "",
        f"{'lake':18}{'gate rho':>10}{'n':>5}{'range rho':>11}{'n':>5}"
        f"{'legacy rho':>12}{'n':>5}{'H4 rho':>9}{'n':>5}",
    ]
    reproduces = True
    for row in table:
        reported = H4_REPORTED[str(row["uid"])]
        legacy_rho = float(str(row["legacy_rho"]))
        reproduces = reproduces and (
            round(legacy_rho, 3) == reported.rho
            and row["legacy_n_pairs"] == reported.n_pairs
        )
        lines.append(
            f"{row['lake']!s:18}{float(str(row['rho'])):10.3f}"
            f"{row['n_pairs']!s:>5}{float(str(row['range_rho'])):11.3f}"
            f"{row['range_n_pairs']!s:>5}{legacy_rho:12.3f}"
            f"{row['legacy_n_pairs']!s:>5}{reported.rho:9.3f}{reported.n_pairs:5d}"
        )
    lines += [
        "",
        f"{'lake':18}{'rows':>6}{'dt dedupe':>10}{'tile+date':>10}{'dropped':>8}"
        f"{'outside':>8}{'DEA rows':>9}  DEA last date",
    ]
    for row in table:
        lines.append(
            f"{row['lake']!s:18}{row['n_rows_history']!s:>6}"
            f"{row['n_rows_datetime_dedupe']!s:>10}"
            f"{row['n_rows_tile_date_dedupe']!s:>10}"
            f"{row['n_dropped_by_tile_date_dedupe']!s:>8}"
            f"{row['n_outside_range']!s:>8}"
            f"{row['dea_series_rows']!s:>9}  {row['dea_series_last_date']}"
        )
    lines += [
        "",
        "rows: stored rows of the polygon. dt dedupe: after datetime-only "
        "de-duplication over the whole history. tile+date: after the gate's tile "
        "and date rule. dropped: dt dedupe minus tile+date. outside: stored rows "
        f"dated outside {H4_START} to {H4_END}.",
        "",
        "R1 (legacy reproduces the H4 rho to three decimals and the H4 pair counts "
        f"exactly): {'holds' if reproduces else 'does not hold'}.",
        "",
        "Legacy minus gate, per lake: "
        + "; ".join(
            f"{row['lake']} rho "
            f"{float(str(row['legacy_rho'])) - float(str(row['rho'])):+.4f}, "
            f"pairs {int(str(row['legacy_n_pairs'])) - int(str(row['n_pairs'])):+d}"
            for row in table
        )
        + ".",
        "Gate and range columns agree on every lake: "
        f"{'yes' if all(row['rho'] == row['range_rho'] for row in table) else 'no'}"
        f" (stored rows outside the H4 range: "
        f"{sum(int(str(row['n_outside_range'])) for row in table)}).",
        "Commits: fc9f4ba (H4 report) 2026-11-03 18:45:32 +0800; 00e8fb0 "
        "(tile and date de-duplication) 2026-11-03 18:49:11 +0800.",
        "",
        f"Lowest gate rho: {lowest!r}. Proposed spearman_min = "
        f"floor(({lowest!r} - {ADR_MARGIN}) * 100) / 100 = {proposed}.",
        "",
        "Windowed measurements (2026-11-05): "
        + " and ".join(WINDOW_FILES)
        + " measured rho over 365-day and 730-day windows at monthly run ends. "
        "They ran against commit 46e0e20, before history_days was removed, so the "
        "script does not run on the branch head. They are read only. sha256:",
    ]
    lines += [f"  {_sha256(HERE / name)}  {name}" for name in WINDOW_FILES]
    report = "\n".join(lines) + "\n"
    report_path.write_text(report)
    print(report)
    print(f"proposed spearman_min: {proposed}")


if __name__ == "__main__":
    main()
