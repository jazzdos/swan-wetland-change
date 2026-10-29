from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd
import pytest
from numpy.testing import assert_allclose

from wetland_change.change import (
    BASELINE_COLUMNS,
    MIN_BASELINE_SAMPLES,
    SCORE_COLUMNS,
    ObservationFrameError,
    UnscoredReason,
    build_baseline,
    daily_aggregate,
    score_observations,
)
from wetland_change.outputs.geoparquet import OBSERVATION_COLUMNS

MIN_VALID = 0.8  # [water] min_valid_fraction in config/pipeline.toml
POLYGON = "ramsar-56"
JANUARY_WATER = np.array(
    [41.2, 47.9, 50.3, 44.1, 52.8, 39.5, 49.0, 45.6, 55.2, 43.3, 48.7, 46.1]
)
JANUARY_NDVI = np.array(
    [0.21, 0.18, 0.25, 0.19, 0.30, 0.22, 0.17, 0.24, 0.20, 0.27, 0.23, 0.16]
)


def _observation(
    when: str,
    *,
    polygon_id: str = POLYGON,
    water: float = 45.0,
    ndvi: float = 0.2,
    valid: float = 0.95,
    coverage: float = 1.0,
    n_pixels: int = 1000,
    tile: str = "50HLK",
) -> dict[str, object]:
    n_clear = round(valid * n_pixels)
    stamp = pd.Timestamp(when, tz="UTC")
    return {
        "polygon_id": polygon_id,
        "site": "Forrestdale & Thomsons Lakes",
        "aoi_layer": "ramsar",
        "item_id": f"S2A_T{tile}_{stamp:%Y%m%d}T022351_L2A",
        "product_uri": "S2A_MSIL2A_x.SAFE",
        "datetime": stamp,
        "tile": tile,
        "processing_baseline": "05.11",
        "scene_coverage": coverage,
        "n_pixels": n_pixels,
        "n_clear": n_clear,
        "valid_fraction": n_clear / n_pixels if n_pixels else 0.0,
        "cloud_fraction": 0.0,
        "water_ha_index": water,
        "water_ha_scl": water,
        "ndwi_median": 0.1,
        "mndwi_median": 0.2,
        "ndvi_median": ndvi,
        "dea_wo_agreement": None,
        "run_id": "run-test",
    }


def _frame(rows: Sequence[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame.from_records(list(rows), columns=list(OBSERVATION_COLUMNS))


def _january_history() -> list[dict[str, object]]:
    return [
        _observation(
            f"{2023 + index // 4}-01-{3 + 5 * (index % 4):02d}T02:26:00",
            water=float(water),
            ndvi=float(ndvi),
        )
        for index, (water, ndvi) in enumerate(
            zip(JANUARY_WATER, JANUARY_NDVI, strict=True)
        )
    ]


def _robust(values: np.ndarray) -> tuple[float, float]:
    median = float(np.median(values))
    return median, 1.4826 * float(np.median(np.abs(values - median)))


def _baseline_row(baseline: pd.DataFrame, metric: str, month: int = 1) -> pd.Series:
    match = baseline[
        (baseline["polygon_id"] == POLYGON)
        & (baseline["month"] == month)
        & (baseline["metric"] == metric)
    ]
    assert len(match) == 1
    return match.iloc[0]


def _scored(scores: pd.DataFrame, day: date, metric: str) -> pd.Series:
    match = scores[
        (scores["polygon_id"] == POLYGON)
        & (scores["acquisition_date"] == day)
        & (scores["metric"] == metric)
    ]
    assert len(match) == 1
    return match.iloc[0]


@pytest.mark.parametrize(
    ("metric", "values"),
    [("water_ha_index", JANUARY_WATER), ("ndvi_median", JANUARY_NDVI)],
    ids=["water", "ndvi"],
)
def test_build_baseline_matches_numpy_median_and_scaled_mad(
    metric: str, values: np.ndarray
) -> None:
    other_month = [_observation("2024-02-10T02:26:00", water=500.0, ndvi=0.9)]
    other_polygon = [
        _observation("2024-01-10T02:26:00", polygon_id="ramsar-52", water=900.0)
    ]
    baseline = build_baseline(
        _frame(_january_history() + other_month + other_polygon),
        min_valid_fraction=MIN_VALID,
    )
    assert tuple(baseline.columns) == BASELINE_COLUMNS
    row = _baseline_row(baseline, metric)
    median, mad = _robust(values)
    assert_allclose(row["baseline_median"], median, rtol=1e-9)
    assert_allclose(row["baseline_mad"], mad, rtol=1e-9)
    assert row["baseline_n"] == len(values)


def test_build_baseline_excludes_rows_at_or_below_min_valid_fraction() -> None:
    cloudy = [
        _observation("2025-01-04T02:26:00", water=5000.0, valid=0.8),
        _observation("2025-01-09T02:26:00", water=5000.0, valid=0.5),
    ]
    baseline = build_baseline(
        _frame(_january_history() + cloudy), min_valid_fraction=MIN_VALID
    )
    row = _baseline_row(baseline, "water_ha_index")
    median, mad = _robust(JANUARY_WATER)
    assert row["baseline_n"] == len(JANUARY_WATER)
    assert_allclose(row["baseline_median"], median, rtol=1e-9)
    assert_allclose(row["baseline_mad"], mad, rtol=1e-9)


@pytest.mark.parametrize(
    ("valid", "expected_flag", "expected_reason"),
    [
        (0.8, False, UnscoredReason.LOW_VALID_FRACTION.value),
        (0.5, False, UnscoredReason.LOW_VALID_FRACTION.value),
        (0.801, True, None),
    ],
    ids=["at-gate", "below-gate", "just-above-gate"],
)
def test_score_flags_only_rows_above_min_valid_fraction(
    valid: float, expected_flag: bool, expected_reason: str | None
) -> None:
    baseline = build_baseline(_frame(_january_history()), min_valid_fraction=MIN_VALID)
    new = _frame([_observation("2026-01-14T02:26:00", water=5000.0, valid=valid)])
    scores = score_observations(new, baseline, min_valid_fraction=MIN_VALID)
    row = _scored(scores, date(2026, 1, 14), "water_ha_index")
    assert bool(row["flagged"]) is expected_flag
    assert row["reason"] == expected_reason


def test_score_flags_four_robust_sd_low_and_not_two_robust_sd_high() -> None:
    baseline = build_baseline(_frame(_january_history()), min_valid_fraction=MIN_VALID)
    median, mad = _robust(JANUARY_WATER)
    ndvi_median, _ = _robust(JANUARY_NDVI)
    new = _frame(
        [
            _observation(
                "2026-01-14T02:26:00", water=median - 4 * mad, ndvi=ndvi_median
            ),
            _observation(
                "2026-01-19T02:26:00", water=median + 2 * mad, ndvi=ndvi_median
            ),
        ]
    )
    scores = score_observations(new, baseline, min_valid_fraction=MIN_VALID)
    low = _scored(scores, date(2026, 1, 14), "water_ha_index")
    high = _scored(scores, date(2026, 1, 19), "water_ha_index")
    assert low["z"] < -3
    assert low["z"] == pytest.approx(-4.0)
    assert bool(low["flagged"]) is True
    assert low["reason"] is None
    assert high["z"] == pytest.approx(2.0)
    assert bool(high["flagged"]) is False
    assert high["reason"] is None


def test_score_zero_mad_gives_unflagged_row_with_reason() -> None:
    flat = [
        _observation(f"2024-01-{day:02d}T02:26:00", water=50.0)
        for day in (3, 8, 13, 18, 23, 28)
    ]
    baseline = build_baseline(_frame(flat), min_valid_fraction=MIN_VALID)
    assert _baseline_row(baseline, "water_ha_index")["baseline_mad"] == 0.0
    new = _frame([_observation("2026-01-14T02:26:00", water=80.0)])
    scores = score_observations(new, baseline, min_valid_fraction=MIN_VALID)
    row = _scored(scores, date(2026, 1, 14), "water_ha_index")
    assert bool(row["flagged"]) is False
    assert row["reason"] == UnscoredReason.ZERO_MAD.value
    assert pd.isna(row["z"]) or np.isfinite(row["z"])


def test_score_too_few_samples_gives_unflagged_row_with_reason() -> None:
    sparse = _january_history()[: MIN_BASELINE_SAMPLES - 1]
    baseline = build_baseline(_frame(sparse), min_valid_fraction=MIN_VALID)
    new = _frame([_observation("2026-01-14T02:26:00", water=5000.0)])
    scores = score_observations(new, baseline, min_valid_fraction=MIN_VALID)
    row = _scored(scores, date(2026, 1, 14), "water_ha_index")
    assert row["baseline_n"] == MIN_BASELINE_SAMPLES - 1
    assert bool(row["flagged"]) is False
    assert row["reason"] == UnscoredReason.TOO_FEW_SAMPLES.value
    assert pd.isna(row["z"]) or np.isfinite(row["z"])


def test_score_without_any_baseline_gives_too_few_samples() -> None:
    empty = build_baseline(_frame([]), min_valid_fraction=MIN_VALID)
    new = _frame([_observation("2026-01-14T02:26:00", water=5000.0)])
    scores = score_observations(new, empty, min_valid_fraction=MIN_VALID)
    row = _scored(scores, date(2026, 1, 14), "water_ha_index")
    assert row["baseline_n"] == 0
    assert pd.isna(row["baseline_median"]) and pd.isna(row["baseline_mad"])
    assert bool(row["flagged"]) is False
    assert row["reason"] == UnscoredReason.TOO_FEW_SAMPLES.value
    assert pd.isna(row["z"])


def test_score_seam_rows_same_day_give_one_scored_row() -> None:
    baseline = build_baseline(_frame(_january_history()), min_valid_fraction=MIN_VALID)
    seam = _frame(
        [
            _observation(
                "2026-01-14T02:26:00",
                coverage=0.4,
                n_pixels=400,
                water=18.0,
                tile="50HLK",
            ),
            _observation(
                "2026-01-14T02:26:00",
                coverage=0.6,
                n_pixels=600,
                water=27.0,
                tile="50HMK",
            ),
        ]
    )
    scores = score_observations(seam, baseline, min_valid_fraction=MIN_VALID)
    water = scores[scores["metric"] == "water_ha_index"]
    assert len(water) == 1
    row = water.iloc[0]
    assert row["acquisition_date"] == date(2026, 1, 14)
    assert row["n_scenes"] == 2
    assert row["scene_coverage"] == pytest.approx(1.0)
    assert row["value"] == pytest.approx(45.0)
    assert len(scores) == 2


def test_daily_aggregate_combining_rule_for_disjoint_seam_pieces() -> None:
    seam = _frame(
        [
            _observation(
                "2026-01-14T02:26:00",
                coverage=0.4,
                n_pixels=400,
                valid=1.0,
                water=18.0,
                ndvi=0.1,
                tile="50HLK",
            ),
            _observation(
                "2026-01-14T02:26:00",
                coverage=0.6,
                n_pixels=600,
                valid=0.9,
                water=27.0,
                ndvi=0.3,
                tile="50HMK",
            ),
        ]
    )
    row = daily_aggregate(seam).iloc[0]
    assert row["n_clear"] == 400 + 540
    assert row["valid_fraction"] == pytest.approx(940 / 1000)
    assert row["water_ha_index"] == pytest.approx(45.0)
    assert row["ndvi_median"] == pytest.approx((400 * 0.1 + 540 * 0.3) / 940)
    assert row["item_id"] == "S2A_T50HMK_20260114T022351_L2A"
    assert (
        row["item_ids"]
        == "S2A_T50HLK_20260114T022351_L2A,S2A_T50HMK_20260114T022351_L2A"
    )


def test_daily_aggregate_divides_out_overlap_when_no_row_covers_polygon() -> None:
    overlap = _frame(
        [
            _observation(
                "2026-01-14T02:26:00",
                coverage=0.7,
                n_pixels=700,
                water=28.0,
                tile="50HLK",
            ),
            _observation(
                "2026-01-14T02:26:00",
                coverage=0.6,
                n_pixels=600,
                water=24.0,
                tile="50HMK",
            ),
        ]
    )
    row = daily_aggregate(overlap).iloc[0]
    assert row["scene_coverage"] == pytest.approx(1.0)
    assert row["water_ha_index"] == pytest.approx(52.0 / 1.3)


def _forrestdale_pair(*, partner: bool) -> pd.DataFrame:
    # All the water lies outside the overlap, so the partner tile sees none.
    rows = [
        _observation(
            "2026-01-14T02:26:00",
            coverage=1.0,
            n_pixels=1000,
            water=40.0,
            tile="50HLK",
        )
    ]
    if partner:
        rows.append(
            _observation(
                "2026-01-14T02:26:00",
                coverage=0.363,
                n_pixels=363,
                water=0.0,
                tile="50HMK",
            )
        )
    return _frame(rows)


def test_daily_aggregate_full_coverage_row_ignores_partial_partner() -> None:
    alone = daily_aggregate(_forrestdale_pair(partner=False)).iloc[0]
    paired = daily_aggregate(_forrestdale_pair(partner=True)).iloc[0]
    assert alone["water_ha_index"] == pytest.approx(40.0)
    assert paired["water_ha_index"] == pytest.approx(alone["water_ha_index"])
    assert paired["n_clear"] == alone["n_clear"]
    assert paired["valid_fraction"] == pytest.approx(alone["valid_fraction"])
    assert paired["item_id"] == alone["item_id"]
    assert paired["n_scenes"] == 2
    assert alone["n_scenes"] == 1


def test_daily_aggregate_picks_clearest_of_several_full_coverage_rows() -> None:
    rows = _frame(
        [
            _observation("2026-01-14T02:26:00", water=30.0, valid=0.5, tile="50HLK"),
            _observation("2026-01-14T02:26:00", water=44.0, valid=0.9, tile="50HMK"),
        ]
    )
    row = daily_aggregate(rows).iloc[0]
    assert row["water_ha_index"] == pytest.approx(44.0)
    assert row["tile"] == "50HMK"


def test_daily_aggregate_scores_same_with_and_without_partner_tile() -> None:
    baseline = build_baseline(_frame(_january_history()), min_valid_fraction=MIN_VALID)
    scores = []
    for partner in (False, True):
        scored = score_observations(
            _forrestdale_pair(partner=partner), baseline, min_valid_fraction=MIN_VALID
        )
        scores.append(scored[scored["metric"] == "water_ha_index"].iloc[0]["z"])
    assert scores[0] == pytest.approx(scores[1])


def test_daily_aggregate_lone_partial_row_falls_below_valid_gate() -> None:
    partial = _frame(
        [
            _observation(
                "2026-01-14T02:26:00",
                coverage=0.363,
                n_pixels=363,
                valid=1.0,
                tile="50HMK",
            )
        ]
    )
    row = daily_aggregate(partial).iloc[0]
    assert row["valid_fraction"] == pytest.approx(0.363)
    assert row["valid_fraction"] <= MIN_VALID


def test_daily_aggregate_keeps_single_full_row_values() -> None:
    single = _frame(
        [_observation("2026-01-14T02:26:00", water=47.3, ndvi=0.21, valid=0.93)]
    )
    row = daily_aggregate(single).iloc[0]
    assert row["water_ha_index"] == 47.3
    assert row["ndvi_median"] == pytest.approx(0.21, rel=1e-12)
    assert row["valid_fraction"] == 0.93
    assert row["month"] == 1


@pytest.mark.parametrize("metric", ["water_ha_index", "ndvi_median"])
def test_score_rows_carry_the_baseline_they_were_scored_against(metric: str) -> None:
    baseline = build_baseline(_frame(_january_history()), min_valid_fraction=MIN_VALID)
    new = _frame([_observation("2026-01-14T02:26:00", water=47.0, ndvi=0.2)])
    scores = score_observations(new, baseline, min_valid_fraction=MIN_VALID)
    assert tuple(scores.columns) == SCORE_COLUMNS
    scored = _scored(scores, date(2026, 1, 14), metric)
    expected = _baseline_row(baseline, metric)
    assert scored["baseline_median"] == expected["baseline_median"]
    assert scored["baseline_mad"] == expected["baseline_mad"]
    assert scored["baseline_n"] == expected["baseline_n"]


def test_daily_aggregate_rejects_frame_without_required_columns() -> None:
    with pytest.raises(ObservationFrameError, match="n_clear"):
        daily_aggregate(
            _frame([_observation("2026-01-14T02:26:00")]).drop(columns=["n_clear"])
        )
