from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from wetland_change.aoi import AoiPolygon
from wetland_change.config import WaterbodiesVerifyConfig
from wetland_change.outputs.geoparquet import observation_path
from wetland_change.store import OutputStore
from wetland_change.verify.waterbodies import (
    CHECK_NAME,
    SPEARMAN_CHECK_NAME,
    parse_timeseries,
    read_observations,
    spearman_check,
    timeseries_url,
    waterbody_checks,
)

FIXTURE = (
    Path(__file__).parent / "fixtures" / "waterbodies" / "qd635epws_v3_excerpt.csv"
)
UID = "qd635epws_v3"
PID = f"dea-{UID}"
AREA_HA = 193.2
CFG = WaterbodiesVerifyConfig()


def _polygon(uid: str = UID) -> AoiPolygon:
    geom = box(0, 0, 1932, 1000)
    return AoiPolygon(
        polygon_id=f"dea-{uid}",
        site=uid,
        layer="dea_waterbody",
        geometry=geom,
        geometry_4326=geom,
    )


def _obs(*rows: tuple[str, float, float]) -> pd.DataFrame:
    """Rows of (datetime, valid_fraction, wet fraction of the polygon)."""
    return pd.DataFrame(
        {
            "polygon_id": [PID] * len(rows),
            "aoi_layer": ["dea_waterbody"] * len(rows),
            "item_id": [f"item-{i}" for i in range(len(rows))],
            "datetime": pd.to_datetime([r[0] for r in rows], utc=True),
            "scene_coverage": [1.0] * len(rows),
            "valid_fraction": [r[1] for r in rows],
            "water_ha_index": [r[2] * AREA_HA for r in rows],
        }
    )


def _series() -> pd.DataFrame:
    return parse_timeseries(FIXTURE.read_text())


def _run(obs: pd.DataFrame, **kwargs):  # type: ignore[no-untyped-def]
    return waterbody_checks(
        obs,
        {UID: _series()},
        [_polygon()],
        cfg=CFG,
        min_valid_fraction=0.8,
        **kwargs,
    )


def _passes(checks):  # type: ignore[no-untyped-def]
    return [c for c in checks if c.name == CHECK_NAME]


def _rho(checks):  # type: ignore[no-untyped-def]
    (c,) = [c for c in checks if c.name == SPEARMAN_CHECK_NAME]
    return c


def test_timeseries_url() -> None:
    assert timeseries_url(UID) == (
        "https://data.dea.ga.gov.au/derivative/dea_waterbodies/3-0-0/"
        "timeseries/qd63/qd635epws_v3.csv"
    )


def test_parse_timeseries_percent_to_fraction() -> None:
    df = parse_timeseries(FIXTURE.read_text())
    assert len(df) == 3
    assert list(df.columns) == ["date", "wet_fraction"]
    assert str(df["date"].dt.tz) == "UTC"
    assert df["date"].is_monotonic_increasing
    last = df.iloc[-1]
    assert last["date"] == pd.Timestamp("2026-10-10T02:05:30Z")
    assert last["wet_fraction"] == pytest.approx(0.9041)


def test_pass_within_tolerance_scored() -> None:
    checks = _run(_obs(("2026-10-12T02:26:00Z", 0.95, 0.85)))
    (c,) = _passes(checks)
    assert c.passed is True
    assert c.detail["day_gap"] == 2
    assert c.detail["dea_date"].startswith("2026-10-10")
    assert c.measured == pytest.approx(5.41)
    assert c.threshold == 10.0
    assert c.detail["area_ha"] == pytest.approx(AREA_HA)


def test_pass_outside_tolerance_fails() -> None:
    (c,) = _passes(_run(_obs(("2026-10-12T02:26:00Z", 0.95, 0.70))))
    assert c.passed is False
    assert c.measured == pytest.approx(20.41)


def test_unpaired_rows_yield_no_check() -> None:
    obs = _obs(("2026-10-14T02:26:00Z", 0.95, 0.9), ("2026-01-01T02:26:00Z", 0.95, 0.9))
    checks = _run(obs)
    assert _passes(checks) == []
    rho = _rho(checks)
    assert rho.detail["n_unpaired"] == 2
    assert rho.detail["n_pairs"] == 0
    assert rho.passed is None


def test_low_valid_fraction_skipped_and_not_counted() -> None:
    obs = _obs(("2026-10-12T02:26:00Z", 0.5, 0.85))
    checks = _run(obs)
    (c,) = _passes(checks)
    assert c.passed is None
    assert c.detail["reason"]
    assert _rho(checks).detail["n_pairs"] == 0


def test_partial_scene_coverage_skipped_and_not_counted() -> None:
    obs = _obs(("2026-10-12T02:26:00Z", 1.0, 0.31))
    obs["scene_coverage"] = 0.363
    checks = _run(obs)
    (c,) = _passes(checks)
    assert c.passed is None
    assert "scene_coverage" in c.detail["reason"]
    assert _rho(checks).detail["n_pairs"] == 0


def test_tile_seam_keeps_highest_coverage_row_per_datetime() -> None:
    # One datatake on two tiles: the 36 percent row would read as a 57 pp FAIL.
    obs = _obs(
        ("2026-10-12T02:26:00Z", 1.0, 0.31),
        ("2026-10-12T02:26:00Z", 1.0, 0.85),
    )
    obs["scene_coverage"] = [0.363, 1.0]
    checks = _run(obs)
    (c,) = _passes(checks)
    assert c.passed is True
    assert c.detail["scene_coverage"] == 1.0
    assert c.measured == pytest.approx(5.41)


def test_tile_seam_without_full_tile_is_one_skip() -> None:
    obs = _obs(
        ("2026-10-12T02:26:00Z", 1.0, 0.31),
        ("2026-10-12T02:26:00Z", 1.0, 0.54),
    )
    obs["scene_coverage"] = [0.363, 0.637]
    checks = _run(obs)
    (c,) = _passes(checks)
    assert c.passed is None
    assert c.detail["scene_coverage"] == 0.637
    assert _rho(checks).detail["n_pairs"] == 0


def test_start_end_filter() -> None:
    obs = _obs(
        ("2026-10-12T02:26:00Z", 0.95, 0.85),
        ("1986-08-17T02:26:00Z", 0.95, 0.75),
    )
    both = _passes(_run(obs))
    assert len(both) == 2
    only_new = _passes(_run(obs, start=date(2026, 1, 1)))
    assert len(only_new) == 1
    only_old = _passes(_run(obs, end=date(1986, 12, 31)))
    assert len(only_old) == 1
    assert only_old[0].detail["pipeline_date"].startswith("1986-08-17")
    assert _passes(_run(obs, start=date(2027, 1, 1))) == []


def test_tie_goes_to_earlier_dea_date() -> None:
    # 1986-08-20 is 4 days after 08-16 and 5 before 08-25: too far for both,
    # 1986-08-20 shifted: 08-19 is 3 from 08-16 and 6 from 08-25.
    (c,) = _passes(_run(_obs(("1986-08-19T02:00:00Z", 0.95, 0.76))))
    assert c.detail["dea_date"].startswith("1986-08-16")
    assert c.detail["day_gap"] == 3


def test_same_day_counts() -> None:
    (c,) = _passes(_run(_obs(("2026-10-10T02:26:00Z", 0.95, 0.9041))))
    assert c.detail["day_gap"] == 0
    assert c.passed is True


def test_spearman_monotonic_passes() -> None:
    ref = np.linspace(0.3, 0.9, 12)
    check = spearman_check(UID, ref * 100, ref, cfg=CFG)
    assert check.name == SPEARMAN_CHECK_NAME
    assert check.passed is True
    assert check.measured == pytest.approx(1.0)
    assert check.threshold == 0.9


def test_spearman_weak_fails() -> None:
    ref = np.arange(12, dtype=float)
    pipe = np.array([5, 1, 9, 3, 11, 0, 7, 2, 10, 4, 8, 6], dtype=float)
    check = spearman_check(UID, pipe, ref, cfg=CFG)
    assert check.passed is False
    assert check.measured is not None and check.measured < 0.9


def test_spearman_too_few_pairs_skipped() -> None:
    ref = np.linspace(0.3, 0.9, 9)
    check = spearman_check(UID, ref, ref, cfg=CFG)
    assert check.passed is None
    assert check.measured is None
    assert check.threshold == 0.9
    assert check.detail["reason"]
    assert check.detail["n_pairs"] == 9


def test_spearman_constant_skipped() -> None:
    check = spearman_check(UID, np.ones(12), np.linspace(0, 1, 12), cfg=CFG)
    assert check.passed is None
    assert "constant" in check.detail["reason"]


def test_end_to_end_single_spearman_check() -> None:
    dates = pd.date_range("1986-08-16T02:00:00Z", periods=12, freq="10D")
    series = pd.DataFrame({"date": dates, "wet_fraction": np.linspace(0.3, 0.8, 12)})
    obs = _obs(
        *[
            (d.isoformat(), 0.95, float(w) + 0.01)
            for d, w in zip(dates, series["wet_fraction"], strict=True)
        ]
    )
    checks = waterbody_checks(
        obs, {UID: series}, [_polygon()], cfg=CFG, min_valid_fraction=0.8
    )
    assert len(_passes(checks)) == 12
    rho = _rho(checks)
    assert rho.passed is True
    assert rho.detail["n_pairs"] == 12
    assert checks[-1] is rho


def test_loader_exception_skips() -> None:
    def boom(uid: str) -> pd.DataFrame:
        raise RuntimeError("network down")

    checks = waterbody_checks(
        _obs(("2026-10-12T02:26:00Z", 0.95, 0.85)),
        boom,
        [_polygon()],
        cfg=CFG,
        min_valid_fraction=0.8,
    )
    names = [c.name for c in checks]
    assert names == [CHECK_NAME, SPEARMAN_CHECK_NAME]
    assert all(c.passed is None for c in checks)
    assert checks[0].detail["error"] == "RuntimeError: network down"
    assert checks[0].detail["uid"] == UID
    assert checks[0].reference == "check did not run"
    assert checks[1].detail["reason"] == "series unavailable"


def test_loader_called_only_for_polygon_uids() -> None:
    calls: list[str] = []

    def loader(uid: str) -> pd.DataFrame:
        calls.append(uid)
        return _series()

    waterbody_checks(
        _obs(("2026-10-12T02:26:00Z", 0.95, 0.85)),
        loader,
        [_polygon(), _polygon("unknown_v3")],
        cfg=CFG,
        min_valid_fraction=0.8,
    )
    assert calls == [UID]


def test_read_observations_keeps_only_waterbodies(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    frame = pd.DataFrame(
        {
            "polygon_id": [PID, "ramsar-thomsons"],
            "site": ["a", "b"],
            "aoi_layer": ["dea_waterbody", "ramsar"],
            "item_id": ["i1", "i1"],
            "datetime": pd.to_datetime(["2026-10-12T02:26:00Z"] * 2, utc=True),
            "scene_coverage": [1.0, 1.0],
            "valid_fraction": [0.9, 0.9],
            "water_ha_index": [10.0, 20.0],
        }
    )
    path = observation_path(2026, "T50HMK", "i1")
    from io import BytesIO

    buf = BytesIO()
    frame.to_parquet(buf, index=False)
    store.write_bytes(path, buf.getvalue())
    out = read_observations(store)
    assert list(out["polygon_id"]) == [PID]
    assert list(out.columns) == [
        "polygon_id",
        "aoi_layer",
        "item_id",
        "datetime",
        "scene_coverage",
        "valid_fraction",
        "water_ha_index",
    ]
    assert read_observations(OutputStore(str(tmp_path / "empty"))).empty
