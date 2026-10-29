"""Seasonal baseline and robust z scoring of observation rows.

Pure functions over pandas frames that follow the observation schema
(`ObservationRow` in `wetland_change.stats`, as framed by
`wetland_change.outputs.geoparquet.rows_to_frame` or read back from the
stored GeoParquet). No I/O.

The baseline is per polygon and month of year: the median and the scaled
median absolute deviation (MAD times 1.4826, a robust standard deviation)
of `water_ha_index` and `ndvi_median`. A daily aggregate is scored with
z = (value - baseline_median) / baseline_mad and flagged when |z| is above
3 and its `valid_fraction` is above `[water] min_valid_fraction`. Seasonal
drying is not change because the baseline is monthly (design doc, Change
detection).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

import numpy as np
import pandas as pd

MAD_SCALE: Final = 1.4826
Z_THRESHOLD: Final = 3.0
MIN_BASELINE_SAMPLES: Final = 5
FULL_COVERAGE: Final = 0.99
METRICS: Final[tuple[str, ...]] = ("water_ha_index", "ndvi_median")

REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "polygon_id",
    "item_id",
    "datetime",
    "tile",
    "scene_coverage",
    "n_pixels",
    "n_clear",
    "water_ha_index",
    "ndvi_median",
)

DAILY_COLUMNS: Final[tuple[str, ...]] = (
    "polygon_id",
    "acquisition_date",
    "month",
    "datetime",
    "item_id",
    "item_ids",
    "tile",
    "n_scenes",
    "scene_coverage",
    "n_pixels",
    "n_clear",
    "valid_fraction",
    *METRICS,
)

BASELINE_COLUMNS: Final[tuple[str, ...]] = (
    "polygon_id",
    "month",
    "metric",
    "baseline_median",
    "baseline_mad",
    "baseline_n",
)

SCORE_COLUMNS: Final[tuple[str, ...]] = (
    "polygon_id",
    "acquisition_date",
    "month",
    "datetime",
    "item_id",
    "item_ids",
    "tile",
    "n_scenes",
    "scene_coverage",
    "n_clear",
    "valid_fraction",
    "metric",
    "value",
    "baseline_median",
    "baseline_mad",
    "baseline_n",
    "z",
    "flagged",
    "reason",
)


class UnscoredReason(StrEnum):
    """Why a scored row cannot be flagged; stored as its string value."""

    LOW_VALID_FRACTION = "low_valid_fraction"
    MISSING_VALUE = "missing_value"
    TOO_FEW_SAMPLES = "too_few_samples"
    ZERO_MAD = "zero_mad"


class ObservationFrameError(ValueError):
    """An observation frame lacks a column the scoring needs."""


def _require_columns(frame: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ObservationFrameError(f"observation frame is missing columns {missing}")


def daily_aggregate(observations: pd.DataFrame) -> pd.DataFrame:
    """Combine observation rows into one row per polygon and UTC date.

    A polygon on a tile seam has one observation row per scene, each with
    `scene_coverage` below 1, and those rows are not comparable to a
    full-coverage row. The rows of one polygon on one UTC calendar date
    (the AOI is imaged near 02:26 UTC, so this is also the local date) are
    combined as follows:

    When any row has `scene_coverage` of at least `FULL_COVERAGE`, that
    row alone supplies every measurement below: the full-coverage row with
    the most clear pixels, ties broken by `item_id`. Partner rows are
    ignored for the measurements because water is not spread evenly across
    the polygon (at Forrestdale the lake is 1.000 in 50HLK and 0.363 in
    50HMK, spike S1), so pooling a partial row would make the value depend
    on whether the partner tile was observed that day. They still count in
    `n_scenes` and `item_ids`. When no row covers the polygon, the rows
    are combined as follows:

    - `n_pixels`, `n_clear`: sums.
    - `scene_coverage`: min(1, sum of the row coverages).
    - `valid_fraction`: sum(n_clear) / sum(n_pixels) times `scene_coverage`,
      the share of the whole polygon seen clear. A lone partial row keeps
      its clear share times its coverage, so it falls below the valid gate.
    - `water_ha_index`: sum(water_ha_index) / max(1, sum(scene_coverage)).
      Disjoint pieces add up, and where partial tiles overlap (coverages
      summing above 1) the double-counted area is divided back out, which
      assumes the water density is the same in the overlap.
    - `ndvi_median`: mean of the row medians weighted by `n_clear`, over
      rows with clear pixels and a finite median; NaN when there are none.
    - `item_id`, `tile`, `datetime`: from the row with the most clear
      pixels, ties broken by `item_id`. `item_ids` lists every
      contributing item, sorted and comma-joined; `n_scenes` counts them.

    A date with a single full-coverage row keeps that row's values.

    Args:
        observations: Rows following the observation schema.

    Returns:
        One row per `polygon_id` and `acquisition_date`, columns
        `DAILY_COLUMNS`, sorted by those two keys.

    Raises:
        ObservationFrameError: A column in `REQUIRED_COLUMNS` is missing.
    """
    _require_columns(observations)
    if observations.empty:
        return pd.DataFrame(columns=list(DAILY_COLUMNS))
    frame = observations.loc[:, list(REQUIRED_COLUMNS)].copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    frame["acquisition_date"] = frame["datetime"].dt.date
    clear_counts = frame["n_clear"].astype("float64")
    ndvi_values = frame["ndvi_median"].astype("float64")
    has_ndvi = (clear_counts > 0) & np.isfinite(ndvi_values)
    frame["ndvi_weight"] = clear_counts.where(has_ndvi, 0.0)
    frame["ndvi_weighted"] = (ndvi_values * clear_counts).where(has_ndvi, 0.0)
    frame = frame.sort_values(
        ["polygon_id", "acquisition_date", "n_clear", "item_id"],
        ascending=[True, True, False, True],
        kind="mergesort",
    )
    keys = ["polygon_id", "acquisition_date"]
    all_rows = frame.groupby(keys, sort=True)
    is_full = frame["scene_coverage"] >= FULL_COVERAGE
    by_key = is_full.groupby([frame["polygon_id"], frame["acquisition_date"]])
    full_rank = by_key.cumsum()
    has_full = by_key.transform("any")
    used = frame[~has_full | (is_full & (full_rank == 1))]
    grouped = used.groupby(keys, sort=True)
    daily = grouped.agg(
        datetime=("datetime", "first"),
        item_id=("item_id", "first"),
        tile=("tile", "first"),
        n_pixels=("n_pixels", "sum"),
        n_clear=("n_clear", "sum"),
        coverage_sum=("scene_coverage", "sum"),
        water_sum=("water_ha_index", "sum"),
        ndvi_weight=("ndvi_weight", "sum"),
        ndvi_weighted=("ndvi_weighted", "sum"),
    )
    daily["n_scenes"] = all_rows["item_id"].size()
    daily["item_ids"] = all_rows["item_id"].agg(lambda ids: ",".join(sorted(ids)))
    daily = daily.reset_index()
    coverage_sum = daily["coverage_sum"].astype("float64")
    pixel_counts = daily["n_pixels"].astype("float64")
    daily["scene_coverage"] = coverage_sum.clip(upper=1.0)
    clear_share = (daily["n_clear"] / pixel_counts.where(pixel_counts > 0)).fillna(0.0)
    daily["valid_fraction"] = clear_share * daily["scene_coverage"]
    daily["water_ha_index"] = daily["water_sum"] / coverage_sum.clip(lower=1.0)
    ndvi_weight = daily["ndvi_weight"]
    daily["ndvi_median"] = daily["ndvi_weighted"] / ndvi_weight.where(ndvi_weight > 0)
    daily["month"] = pd.to_datetime(daily["acquisition_date"]).dt.month.astype("int64")
    return daily.loc[:, list(DAILY_COLUMNS)].reset_index(drop=True)


def _melt_metrics(daily: pd.DataFrame) -> pd.DataFrame:
    id_columns = [column for column in DAILY_COLUMNS if column not in METRICS]
    long = daily.melt(
        id_vars=id_columns,
        value_vars=list(METRICS),
        var_name="metric",
        value_name="value",
    )
    long["value"] = long["value"].astype("float64")
    return long


def build_baseline(history: pd.DataFrame, *, min_valid_fraction: float) -> pd.DataFrame:
    """Median and scaled MAD per polygon, month of year and metric.

    `history` is combined per polygon and date with `daily_aggregate`
    first. Aggregates with `valid_fraction` at or below
    `min_valid_fraction`, and non-finite values, are left out. No minimum
    sample count is applied here; `score_observations` applies it.

    Args:
        history: Observation rows the baseline is built from.
        min_valid_fraction: `[water] min_valid_fraction` from the config.

    Returns:
        Columns `BASELINE_COLUMNS`: `baseline_median` is the median,
        `baseline_mad` is MAD_SCALE times the median absolute deviation
        from it, and `baseline_n` is the number of values used.
    """
    daily = daily_aggregate(history)
    usable = daily[daily["valid_fraction"] > min_valid_fraction]
    long = _melt_metrics(usable)
    long = long[np.isfinite(long["value"])]
    records: list[dict[str, object]] = []
    for (polygon_id, month, metric), values in long.groupby(
        ["polygon_id", "month", "metric"], sort=True
    )["value"]:
        samples = values.to_numpy(dtype="float64")
        median = float(np.median(samples))
        mad = MAD_SCALE * float(np.median(np.abs(samples - median)))
        records.append(
            {
                "polygon_id": polygon_id,
                "month": int(month),
                "metric": metric,
                "baseline_median": median,
                "baseline_mad": mad,
                "baseline_n": int(samples.size),
            }
        )
    baseline = pd.DataFrame.from_records(records, columns=list(BASELINE_COLUMNS))
    return baseline.astype({"month": "int64", "baseline_n": "int64"})


def score_observations(
    observations: pd.DataFrame,
    baseline: pd.DataFrame,
    *,
    min_valid_fraction: float,
    min_samples: int = MIN_BASELINE_SAMPLES,
    z_threshold: float = Z_THRESHOLD,
) -> pd.DataFrame:
    """Score daily aggregates against the baseline, one row per metric.

    `z` is (value - baseline_median) / baseline_mad. `flagged` is True
    only when |z| is above `z_threshold` and `valid_fraction` is above
    `min_valid_fraction`. `reason` is None for a scored row; otherwise it
    is the first matching `UnscoredReason` in this order:
    `low_valid_fraction` (z is still reported when the baseline is
    usable), `missing_value`, `too_few_samples` (baseline_n below
    `min_samples`), `zero_mad`. The last three leave z null, never
    infinite.

    Args:
        observations: Observation rows to score.
        baseline: Output of `build_baseline`; the caller chooses its history.
        min_valid_fraction: `[water] min_valid_fraction` from the config.
        min_samples: Fewest baseline values that make a usable baseline.
        z_threshold: |z| must exceed this to flag.

    Returns:
        Columns `SCORE_COLUMNS`, one row per polygon, acquisition date and
        metric, each carrying the baseline median, MAD and sample count it
        was scored against (NaN, NaN and 0 when the polygon-month has no
        baseline).
    """
    long = _melt_metrics(daily_aggregate(observations))
    merged = long.merge(
        baseline.loc[:, list(BASELINE_COLUMNS)],
        on=["polygon_id", "month", "metric"],
        how="left",
        validate="many_to_one",
    )
    merged["baseline_n"] = merged["baseline_n"].fillna(0).astype("int64")
    values = merged["value"]
    medians = merged["baseline_median"].astype("float64")
    mads = merged["baseline_mad"].astype("float64")
    is_valid = merged["valid_fraction"] > min_valid_fraction
    has_value = pd.Series(np.isfinite(values.to_numpy()), index=merged.index)
    has_enough = merged["baseline_n"] >= min_samples
    has_spread = mads > 0
    is_scorable = has_value & has_enough & has_spread
    merged["z"] = (values - medians) / mads.where(is_scorable)
    merged["flagged"] = (
        is_valid & is_scorable & (merged["z"].abs() > z_threshold)
    ).astype(bool)
    reasons = pd.Series([None] * len(merged), index=merged.index, dtype=object)
    reasons[~has_spread] = UnscoredReason.ZERO_MAD.value
    reasons[~has_enough] = UnscoredReason.TOO_FEW_SAMPLES.value
    reasons[~has_value] = UnscoredReason.MISSING_VALUE.value
    reasons[~is_valid] = UnscoredReason.LOW_VALID_FRACTION.value
    merged["reason"] = reasons
    scored = merged.sort_values(
        ["polygon_id", "acquisition_date", "metric"], kind="mergesort"
    )
    return scored.loc[:, list(SCORE_COLUMNS)].reset_index(drop=True)
