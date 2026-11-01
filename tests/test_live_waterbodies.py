"""Live contract test against the DEA Waterbodies v3 CSV time series.

Run with: uv run pytest -q -m live tests/test_live_waterbodies.py
"""

from __future__ import annotations

import pandas as pd
import pytest

from wetland_change.verify.waterbodies import fetch_series

pytestmark = pytest.mark.live

THOMSONS_UID = "qd635epws_v3"


def test_thomsons_series_downloads_and_parses() -> None:
    series = fetch_series(THOMSONS_UID)
    assert not series.empty
    assert {"date", "wet_fraction"} <= set(series.columns)
    assert series["wet_fraction"].between(0, 1).all()
    assert str(series["date"].dt.tz) == "UTC"
    assert series["date"].is_monotonic_increasing
    row = series[series["date"].dt.date == pd.Timestamp("2022-12-17").date()]
    assert len(row) >= 1
    # Value from docs/research/2026-10-30-waterbodies-tolerance.csv.
    assert float(row["wet_fraction"].iloc[0]) == pytest.approx(0.9008, abs=1e-4)
