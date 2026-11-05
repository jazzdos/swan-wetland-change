"""Matrix row: water extent, history, against DEA Waterbodies v3.

Per lake, the pipeline wet fraction over the DEA Waterbodies polygon is
compared with the wet fraction in the DEA Waterbodies v3 CSV time series for
a pass 1 to 3 days apart (`max_day_gap`, same day included), within
`tolerance_pp` percentage points. A per-lake Spearman correlation of the two
series over all scored pairs must reach `spearman_min` (hypothesis 4 uses the
same pairing).

CSV format (probed live 2026-10-30): one file per waterbody at
`{TIMESERIES_BASE}/{uid[:4]}/{uid}.csv` with header `date,pc_wet,px_wet`.
`date` is an ISO UTC timestamp such as 2026-10-10T02:05:30Z. `pc_wet` is a
PERCENT (90.41 means 0.9041 of the polygon), `px_wet` is the wet 25 m pixel
count. Rows for observations DEA could not use have blank `pc_wet` and
`px_wet`; they are dropped. The series starts in 1986 (Landsat), so it holds
rows from sensors other than Sentinel-2.

Units: the pipeline wet fraction is `water_ha_index` (hectares, calibrated
index class) divided by the polygon area in hectares (polygon geometry in
EPSG:32750 metres, area / 1e4). DEA wet fraction is dimensionless. The
per-pass difference is reported in percentage points.

Conventions: passes pair by UTC calendar date, nearest DEA row wins, a tie
goes to the earlier DEA date. A pipeline row with no DEA row in range makes no
per-pass check and is counted in the lake's `n_unpaired`. A paired row whose
`valid_fraction` is below `min_valid_fraction`, or whose `water_ha_index` is
not finite, is a skipped check and is left out of the correlation. A row whose
`scene_coverage` is below `FULL_COVERAGE` (a polygon on a tile seam, where
`water_ha_index` covers only the in-scene part but is divided by the whole
polygon area) is skipped the same way. When several rows of one polygon share
a datetime (the same datatake on two tiles) only the row with the highest
`scene_coverage` is kept, so a datatake is one pair. For each tile and UTC
calendar date only one row is kept (highest `scene_coverage`, then highest
`valid_fraction`, then earliest datetime), because rows of one tile on one
date pair with the same DEA row and are not independent pairs. Rows of
different tiles with different datetimes on one date are not merged.
`n_pairs` therefore counts one pair per tile and date. Spearman is the
Pearson correlation of average ranks, computed on hectares (ranks equal those
of the fraction because the area is constant).

Scope: the per-pass checks cover the rows passed as `observations` (one run).
The Spearman check scores the optional `history` frame instead, the stored
observations of the last `[verify.waterbodies] history_days` days, because one
daily run holds too few rows to reach `spearman_min_pairs`. The same tile and
date rules de-duplicate the history rows of each polygon. With `history` None
the Spearman check scores the same rows as the per-pass checks.

Nothing here knows about runs or ledgers, so the backfill can call it over
any date range.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from io import BytesIO, StringIO

import numpy as np
import pandas as pd
import requests

from wetland_change.aoi import AoiPolygon
from wetland_change.change import FULL_COVERAGE
from wetland_change.config import WaterbodiesVerifyConfig
from wetland_change.store import OutputStore
from wetland_change.verify.checks import Check

CHECK_NAME = "water_vs_dea_waterbodies"
SPEARMAN_CHECK_NAME = "water_spearman_vs_dea_waterbodies"
# Peel Inlet and Harvey Estuary have no DEA Waterbodies polygon.
LAKES: dict[str, str] = {
    "qd635epws_v3": "Thomsons Lake",
    "qd63n1ww5_v3": "Forrestdale Lake",
    "qd4m2n3rj_v3": "Lake Clifton",
    "qd4k2967m_v3": "Lake Preston",
}
TIMESERIES_BASE = (
    "https://data.dea.ga.gov.au/derivative/dea_waterbodies/3-0-0/timeseries"
)
WATERBODY_LAYER = "dea_waterbody"
OBSERVATION_COLUMNS: list[str] = [
    "polygon_id",
    "aoi_layer",
    "item_id",
    "datetime",
    "tile",
    "scene_coverage",
    "valid_fraction",
    "water_ha_index",
]

SeriesLoader = Callable[[str], pd.DataFrame]


def timeseries_url(uid: str) -> str:
    return f"{TIMESERIES_BASE}/{uid[:4]}/{uid}.csv"


def parse_timeseries(text: str) -> pd.DataFrame:
    """`date` (UTC) and `wet_fraction` (pc_wet / 100), blanks dropped, sorted."""
    raw = pd.read_csv(StringIO(text), usecols=["date", "pc_wet"])
    wet = pd.to_numeric(raw["pc_wet"], errors="coerce")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["date"], utc=True),
            "wet_fraction": wet / 100.0,
        }
    )
    frame = frame[np.isfinite(frame["wet_fraction"])]
    return frame.sort_values("date").reset_index(drop=True)


def fetch_series(uid: str, *, timeout: float = 60.0) -> pd.DataFrame:
    resp = requests.get(timeseries_url(uid), timeout=timeout)
    resp.raise_for_status()
    return parse_timeseries(resp.text)


def read_observations(
    store: OutputStore, paths: Iterable[str] | None = None
) -> pd.DataFrame:
    """Stored observation rows of the DEA waterbody polygons."""
    if paths is None:
        paths = [p for p in store.list_files("observations") if p.endswith(".parquet")]
    frames = [
        pd.read_parquet(BytesIO(store.read_bytes(p)), columns=OBSERVATION_COLUMNS)
        for p in paths
    ]
    if not frames:
        return pd.DataFrame({c: [] for c in OBSERVATION_COLUMNS})
    out = pd.concat(frames, ignore_index=True)
    return out[out["aoi_layer"] == WATERBODY_LAYER].reset_index(drop=True)


def spearman_check(
    uid: str,
    pipeline: Sequence[float] | np.ndarray,
    reference: Sequence[float] | np.ndarray,
    *,
    cfg: WaterbodiesVerifyConfig,
    n_unpaired: int = 0,
) -> Check:
    """Spearman correlation of the paired pipeline and DEA values for one lake."""
    pipe = np.asarray(pipeline, dtype=float)
    ref = np.asarray(reference, dtype=float)
    n_pairs = int(pipe.size)
    detail: dict[str, object] = {
        "uid": uid,
        "lake": LAKES.get(uid, uid),
        "n_pairs": n_pairs,
        "n_unpaired": n_unpaired,
    }
    reference_text = (
        f"Spearman rho of pipeline water hectares and DEA Waterbodies v3 CSV {uid} "
        "wet fraction over paired passes"
    )

    def skipped(reason: str) -> Check:
        detail["reason"] = reason
        return Check(
            SPEARMAN_CHECK_NAME, None, None, cfg.spearman_min, reference_text, detail
        )

    if n_pairs < cfg.spearman_min_pairs:
        return skipped(f"fewer than {cfg.spearman_min_pairs} paired passes")
    ranks_p = pd.Series(pipe).rank(method="average").to_numpy()
    ranks_r = pd.Series(ref).rank(method="average").to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        rho = float(np.corrcoef(ranks_p, ranks_r)[0, 1])
    if not math.isfinite(rho):
        return skipped("correlation undefined (constant values)")
    return Check(
        SPEARMAN_CHECK_NAME,
        rho >= cfg.spearman_min,
        rho,
        cfg.spearman_min,
        reference_text,
        detail,
    )


def _uid(polygon: AoiPolygon) -> str | None:
    pid = polygon.polygon_id
    if pid.startswith("dea-") and pid.removeprefix("dea-") in LAKES:
        return pid.removeprefix("dea-")
    return None


def _day_numbers(stamps: pd.Series) -> np.ndarray:
    """UTC calendar day count of each timestamp."""
    days = stamps.dt.tz_convert("UTC").dt.floor("D").dt.tz_localize(None)
    out: np.ndarray = days.to_numpy(dtype="datetime64[D]").astype(np.int64)
    return out


def _paired_passes(
    uid: str,
    polygon: AoiPolygon,
    rows: pd.DataFrame,
    dea: pd.DataFrame,
    *,
    cfg: WaterbodiesVerifyConfig,
    min_valid_fraction: float,
) -> tuple[list[Check], list[float], list[float], int]:
    """Per-pass checks, pipeline hectare pairs, DEA pairs and `n_unpaired`."""
    lake = LAKES[uid]
    area_ha = polygon.geometry.area / 1e4
    reference = (
        f"DEA Waterbodies v3 CSV {uid}, wet fraction over the DEA polygon, "
        f"pass within {cfg.max_day_gap} days"
    )
    dea = dea.sort_values("date").reset_index(drop=True)
    dea_days = _day_numbers(dea["date"]) if len(dea) else np.empty(0, dtype=np.int64)
    # Tile-seam rule: one datatake on two tiles shares a datetime, so keep the
    # tile that covers most of the polygon.
    rows = (
        rows.sort_values(["datetime", "scene_coverage"], ascending=[True, False])
        .drop_duplicates("datetime", keep="first")
        .reset_index(drop=True)
    )
    # Rows of one tile on one UTC date pair with the same DEA row, so they are
    # not independent pairs. Keep the best row, in chronological order.
    if len(rows):
        rows = rows.assign(_day=_day_numbers(rows["datetime"]))
        rows = (
            rows.sort_values(
                ["tile", "_day", "scene_coverage", "valid_fraction", "datetime"],
                ascending=[True, True, False, False, True],
                na_position="last",
            )
            .drop_duplicates(["tile", "_day"], keep="first")
            .sort_values("datetime")
            .drop(columns="_day")
            .reset_index(drop=True)
        )

    checks: list[Check] = []
    pipe_pairs: list[float] = []
    dea_pairs: list[float] = []
    n_unpaired = 0
    for row in rows.itertuples(index=False):
        stamp = pd.Timestamp(row.datetime)
        day = int(_day_numbers(pd.Series([stamp]))[0])
        if dea_days.size == 0:
            n_unpaired += 1
            continue
        # argmin takes the first minimum, which is the earlier DEA date on a tie.
        idx = int(np.argmin(np.abs(dea_days - day)))
        gap = abs(int(dea_days[idx]) - day)
        if gap > cfg.max_day_gap:
            n_unpaired += 1
            continue
        dea_row = dea.iloc[idx]
        dea_wet = float(dea_row["wet_fraction"])
        water_ha = float(row.water_ha_index)
        valid = float(row.valid_fraction)
        coverage = float(row.scene_coverage)
        detail: dict[str, object] = {
            "item": row.item_id,
            "polygon_id": row.polygon_id,
            "uid": uid,
            "lake": lake,
            "pipeline_date": stamp.isoformat(),
            "dea_date": pd.Timestamp(dea_row["date"]).isoformat(),
            "day_gap": gap,
            "dea_wet_fraction": dea_wet,
            "valid_fraction": valid,
            "scene_coverage": coverage,
            "area_ha": area_ha,
        }
        if not math.isfinite(coverage) or coverage < FULL_COVERAGE:
            detail["reason"] = (
                f"scene_coverage {coverage:.3f} below full coverage {FULL_COVERAGE}"
            )
            checks.append(
                Check(CHECK_NAME, None, None, cfg.tolerance_pp, reference, detail)
            )
            continue
        if not math.isfinite(valid) or valid < min_valid_fraction:
            detail["reason"] = (
                f"valid_fraction {valid:.3f} below minimum {min_valid_fraction}"
            )
            checks.append(
                Check(CHECK_NAME, None, None, cfg.tolerance_pp, reference, detail)
            )
            continue
        if not math.isfinite(water_ha):
            detail["reason"] = "water_ha_index is not finite"
            checks.append(
                Check(CHECK_NAME, None, None, cfg.tolerance_pp, reference, detail)
            )
            continue
        pipeline_wet = water_ha / area_ha
        detail["pipeline_wet_fraction"] = pipeline_wet
        measured = abs(pipeline_wet - dea_wet) * 100.0
        checks.append(
            Check(
                CHECK_NAME,
                measured <= cfg.tolerance_pp,
                measured,
                cfg.tolerance_pp,
                reference,
                detail,
            )
        )
        pipe_pairs.append(water_ha)
        dea_pairs.append(dea_wet)
    return checks, pipe_pairs, dea_pairs, n_unpaired


def _lake_checks(
    uid: str,
    polygon: AoiPolygon,
    rows: pd.DataFrame,
    dea: pd.DataFrame,
    *,
    cfg: WaterbodiesVerifyConfig,
    min_valid_fraction: float,
    history: pd.DataFrame | None = None,
) -> list[Check]:
    """Per-pass checks over `rows`, then the Spearman check.

    The Spearman check scores the stored `history` rows of this polygon, or the
    pairs of `rows` themselves when `history` is None.
    """
    checks, pipe_pairs, dea_pairs, n_unpaired = _paired_passes(
        uid, polygon, rows, dea, cfg=cfg, min_valid_fraction=min_valid_fraction
    )
    if history is None:
        rho = spearman_check(uid, pipe_pairs, dea_pairs, cfg=cfg, n_unpaired=n_unpaired)
    else:
        mine = history[history["polygon_id"] == polygon.polygon_id]
        _, h_pipe, h_dea, h_unpaired = _paired_passes(
            uid, polygon, mine, dea, cfg=cfg, min_valid_fraction=min_valid_fraction
        )
        rho = spearman_check(uid, h_pipe, h_dea, cfg=cfg, n_unpaired=h_unpaired)
        rho.detail["history_days"] = cfg.history_days
        rho.detail["n_run_pairs"] = len(pipe_pairs)
    checks.append(rho)
    return checks


def _unavailable(uid: str, exc: Exception, cfg: WaterbodiesVerifyConfig) -> list[Check]:
    lake = LAKES[uid]
    skipped = Check(
        CHECK_NAME,
        None,
        None,
        cfg.tolerance_pp,
        "check did not run",
        {"uid": uid, "lake": lake, "error": f"{type(exc).__name__}: {exc}"},
    )
    rho = Check(
        SPEARMAN_CHECK_NAME,
        None,
        None,
        cfg.spearman_min,
        "check did not run",
        {
            "uid": uid,
            "lake": lake,
            "n_pairs": 0,
            "n_unpaired": 0,
            "reason": "series unavailable",
        },
    )
    return [skipped, rho]


def waterbody_checks(
    observations: pd.DataFrame,
    series: Mapping[str, pd.DataFrame] | SeriesLoader,
    polygons: Sequence[AoiPolygon],
    *,
    cfg: WaterbodiesVerifyConfig,
    min_valid_fraction: float,
    start: date | None = None,
    end: date | None = None,
    history: pd.DataFrame | None = None,
) -> list[Check]:
    """Per-pass checks then one Spearman check, for each DEA lake polygon.

    Per-pass checks cover `observations` (narrowed by `start` and `end`). The
    Spearman check scores `history` when given, else `observations`.
    """
    lakes = sorted(
        ((p.polygon_id, uid, p) for p in polygons if (uid := _uid(p)) is not None),
        key=lambda t: t[0],
    )
    obs = observations
    if len(obs):
        days = obs["datetime"].dt.tz_convert("UTC").dt.date
        keep = pd.Series(True, index=obs.index)
        if start is not None:
            keep &= days >= start
        if end is not None:
            keep &= days <= end
        obs = obs[keep]

    checks: list[Check] = []
    for pid, uid, polygon in lakes:
        try:
            dea = series(uid) if callable(series) else series[uid]
        except Exception as exc:
            checks.extend(_unavailable(uid, exc, cfg))
            continue
        rows = obs[obs["polygon_id"] == pid] if len(obs) else obs
        checks.extend(
            _lake_checks(
                uid,
                polygon,
                rows,
                dea,
                cfg=cfg,
                min_valid_fraction=min_valid_fraction,
                history=history,
            )
        )
    return checks
