"""Tests for the DEA WO availability script (st-5f74).

The script is a dated research file, so it is loaded by path. Nothing here
touches the network: `fetch_all` is driven by a fake `post` callable.
"""

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "research"
    / "2026-11-06-wo-availability.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("wo_availability", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


availability = _load()

START = date(2026, 8, 15)
END = date(2026, 11, 3)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def _earth_search_item(
    item_id: str,
    acquired: str,
    created: str | None,
    *,
    tile: str = "MGRS-50HLK",
    cloud: float = 5.0,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "properties": {
            "datetime": acquired,
            "created": created,
            "eo:cloud_cover": cloud,
            "grid:code": tile,
        },
    }


def _dea_item(
    item_id: str, acquired: str, created: str, region: str = "50HLK"
) -> dict[str, Any]:
    stamp = acquired.replace("-", "")[:8] + "T071416"
    return {
        "id": item_id,
        "properties": {
            "datetime": acquired,
            "created": created,
            "odc:region_code": region,
        },
        "assets": {
            "water": {
                "href": (
                    "s3://dea-public-data/derivative/ga_s2_wo_provisional_3/"
                    f"3-0-0/{region[:2]}/{region[2:]}/2026/{stamp}/x_water.tif"
                )
            }
        },
    }


def _build(
    earth_search: list[dict[str, Any]], dea: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = availability.build_rows(
        earth_search, dea, start=START, end=END, cloud_max=20.0
    )
    return result


@pytest.mark.parametrize(
    ("created", "expected"),
    [
        ("2026-09-01T10:17:00", "2026-09-01T10:17:00"),
        ("2026-09-01T10:17:01", "2026-09-02T10:17:00"),
        ("2026-09-01T10:16:59", "2026-09-01T10:17:00"),
        ("2026-09-01T00:00:00", "2026-09-01T10:17:00"),
        ("2026-09-01T23:59:59", "2026-09-02T10:17:00"),
    ],
)
def test_next_cron_returns_first_scheduled_instant_at_or_after_created(
    created: str, expected: str
) -> None:
    assert availability.next_cron(_utc(created)) == _utc(expected)


def test_next_cron_moves_on_for_a_microsecond_past_the_instant() -> None:
    created = datetime(2026, 9, 1, 10, 17, 0, 1, tzinfo=UTC)
    assert availability.next_cron(created) == _utc("2026-09-02T10:17:00")


def test_build_rows_matches_by_date_and_tile_and_computes_lag() -> None:
    earth_search = [
        _earth_search_item("S2A_1", "2026-10-01T02:30:00Z", "2026-10-01T07:00:00Z")
    ]
    dea = [_dea_item("wo1", "2026-10-01T02:30:00Z", "2026-10-01T08:00:00Z")]
    (row,) = _build(earth_search, dea)
    assert row["item_id"] == "S2A_1"
    assert row["tile"] == "50HLK"
    assert row["acquired"] == "2026-10-01"
    assert row["cloud_cover"] == 5.0
    assert row["wo_found"] is True
    assert row["wo_item_id"] == "wo1"
    assert row["wo_path_stamp"] == "20261001T071416"
    assert row["t_proc"] == "2026-10-01T10:17:00Z"
    assert row["lag_hours"] == pytest.approx(-2.283, abs=1e-9)
    assert row["available_at_proc"] is True
    assert row["available_at_proc_plus2h"] is True


def test_build_rows_wo_after_proc_is_available_only_with_the_two_hour_margin() -> None:
    earth_search = [
        _earth_search_item("a", "2026-10-01T02:30:00Z", "2026-10-01T07:00:00Z")
    ]
    dea = [_dea_item("wo1", "2026-10-01T02:30:00Z", "2026-10-01T11:17:00Z")]
    (row,) = _build(earth_search, dea)
    assert row["lag_hours"] == 1.0
    assert row["available_at_proc"] is False
    assert row["available_at_proc_plus2h"] is True


def test_build_rows_wo_created_exactly_at_proc_is_available() -> None:
    earth_search = [
        _earth_search_item("a", "2026-10-01T02:30:00Z", "2026-10-01T07:00:00Z")
    ]
    dea = [_dea_item("wo1", "2026-10-01T02:30:00Z", "2026-10-01T10:17:00Z")]
    (row,) = _build(earth_search, dea)
    assert row["lag_hours"] == 0.0
    assert row["available_at_proc"] is True


def test_build_rows_without_wo_item_leaves_wo_fields_empty() -> None:
    earth_search = [
        _earth_search_item("a", "2026-10-01T02:30:00Z", "2026-10-01T07:00:00Z")
    ]
    (row,) = _build(earth_search, [])
    assert row["wo_found"] is False
    assert row["wo_item_id"] == ""
    assert row["wo_created"] == ""
    assert row["wo_path_stamp"] == ""
    assert row["lag_hours"] is None
    assert row["available_at_proc"] is False
    assert row["available_at_proc_plus2h"] is False


def test_build_rows_does_not_match_another_tile_or_another_day() -> None:
    earth_search = [
        _earth_search_item("a", "2026-10-01T02:30:00Z", "2026-10-01T07:00:00Z")
    ]
    dea = [
        _dea_item(
            "other_tile", "2026-10-01T02:30:00Z", "2026-10-01T08:00:00Z", "50HLJ"
        ),
        _dea_item("other_day", "2026-10-06T02:30:00Z", "2026-10-06T08:00:00Z"),
    ]
    (row,) = _build(earth_search, dea)
    assert row["wo_found"] is False


def test_build_rows_takes_the_earliest_created_of_two_matching_wo_items() -> None:
    earth_search = [
        _earth_search_item("a", "2026-10-01T02:30:00Z", "2026-10-01T07:00:00Z")
    ]
    dea = [
        _dea_item("late", "2026-10-01T02:30:00Z", "2026-10-02T08:00:00Z"),
        _dea_item("early", "2026-10-01T02:30:00Z", "2026-10-01T08:00:00Z"),
    ]
    (row,) = _build(earth_search, dea)
    assert row["wo_item_id"] == "early"


def test_build_rows_applies_window_cloud_limit_and_drops_null_created() -> None:
    earth_search = [
        _earth_search_item("first_day", "2026-08-15T02:30:00Z", "2026-08-15T07:00:00Z"),
        _earth_search_item("before", "2026-08-14T23:59:59Z", "2026-08-15T07:00:00Z"),
        _earth_search_item("last_day", "2026-11-03T23:59:00Z", "2026-11-04T07:00:00Z"),
        _earth_search_item("after", "2026-11-04T00:00:00Z", "2026-11-04T07:00:00Z"),
        _earth_search_item(
            "cloud_edge", "2026-10-01T02:30:00Z", "2026-10-01T07:00:00Z", cloud=20.0
        ),
        _earth_search_item(
            "cloudy", "2026-10-02T02:30:00Z", "2026-10-02T07:00:00Z", cloud=20.1
        ),
        _earth_search_item("no_created", "2026-10-03T02:30:00Z", None),
    ]
    identifiers = {row["item_id"] for row in _build(earth_search, [])}
    assert identifiers == {"first_day", "last_day", "cloud_edge"}


def test_build_rows_uses_the_utc_acquisition_date() -> None:
    earth_search = [
        _earth_search_item("a", "2026-10-01T23:59:59+00:00", "2026-10-02T07:00:00Z")
    ]
    dea = [_dea_item("w", "2026-10-01T23:59:00Z", "2026-10-02T08:00:00Z")]
    (row,) = _build(earth_search, dea)
    assert row["acquired"] == "2026-10-01"
    assert row["wo_found"] is True


def test_build_rows_sorts_by_acquired_then_item_id() -> None:
    earth_search = [
        _earth_search_item("b", "2026-10-02T02:30:00Z", "2026-10-02T07:00:00Z"),
        _earth_search_item("z", "2026-10-01T02:30:00Z", "2026-10-01T07:00:00Z"),
        _earth_search_item("a", "2026-10-02T02:30:00Z", "2026-10-02T07:00:00Z"),
    ]
    assert [row["item_id"] for row in _build(earth_search, [])] == ["z", "a", "b"]


def _rows_for_summary() -> list[dict[str, Any]]:
    # Matched lags in hours are -3, -2, -1, 0.5 and 1.5, plus one scene-tile
    # with no WO item.
    earth_search: list[dict[str, Any]] = []
    dea: list[dict[str, Any]] = []
    offsets = [-3.0, -2.0, -1.0, 0.5, 1.5]
    for index, offset in enumerate(offsets):
        day = f"2026-10-{index + 1:02d}"
        earth_search.append(
            _earth_search_item(f"i{index}", f"{day}T02:30:00Z", f"{day}T07:00:00Z")
        )
        total_minutes = 10 * 60 + 17 + int(offset * 60)
        clock = f"{total_minutes // 60:02d}:{total_minutes % 60:02d}:00"
        dea.append(_dea_item(f"w{index}", f"{day}T02:30:00Z", f"{day}T{clock}Z"))
    earth_search.append(
        _earth_search_item("none", "2026-09-10T02:30:00Z", "2026-09-10T07:00:00Z")
    )
    return _build(earth_search, dea)


def test_summarise_rows_counts_and_shares() -> None:
    summary = availability.summarise_rows(_rows_for_summary())
    assert summary["n"] == 6
    assert summary["n_available"] == 3
    assert summary["share"] == pytest.approx(0.5)
    assert summary["n_no_wo"] == 1
    assert summary["n_wo_later"] == 2
    assert summary["n_wo_found"] == 5
    assert summary["share_wo_found"] == pytest.approx(5 / 6)
    assert summary["n_available_plus2h"] == 5
    assert summary["share_plus2h"] == pytest.approx(5 / 6)
    assert 0.0 < summary["wilson_low"] < 0.5 < summary["wilson_high"] < 1.0


def test_summarise_rows_lag_quantiles_use_nearest_rank() -> None:
    lags = availability.summarise_rows(_rows_for_summary())["lag_hours"]
    # Sorted lags are -3, -2, -1, 0.5, 1.5 and the rank is ceil(p * n).
    assert lags == {
        "min": -3.0,
        "p25": -2.0,
        "median": -1.0,
        "p75": 0.5,
        "p90": 1.5,
        "max": 1.5,
    }


def test_summarise_rows_counts_by_acquisition_month() -> None:
    by_month = availability.summarise_rows(_rows_for_summary())["by_month"]
    assert by_month == {
        "2026-09": {"n": 1, "n_available": 0, "n_no_wo": 1},
        "2026-10": {"n": 5, "n_available": 3, "n_no_wo": 0},
    }


def test_summarise_rows_rejects_an_empty_sample() -> None:
    with pytest.raises(ValueError, match="no rows"):
        availability.summarise_rows([])


def test_wilson_interval_for_all_available() -> None:
    low, high = availability.wilson_interval(49, 49)
    assert low == pytest.approx(0.9273, abs=1e-4)
    assert high == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("share", "expected"),
    [(0.5, "populate"), (0.49, "amend"), (0.9, "populate"), (0.0, "amend")],
)
def test_decide_populates_from_half_upwards(share: float, expected: str) -> None:
    assert availability.decide({"share": share}) == expected


def test_csv_round_trip_gives_identical_rows_and_summary(tmp_path: Path) -> None:
    rows = _rows_for_summary()
    path = tmp_path / "rows.csv"
    availability.write_rows(rows, path)
    assert availability.load_rows(path) == rows
    assert availability.summarise_rows(
        availability.load_rows(path)
    ) == availability.summarise_rows(rows)


def test_write_rows_fixes_header_order_sorting_and_lag_decimals(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rows.csv"
    availability.write_rows(_rows_for_summary(), path)
    lines = path.read_text().splitlines()
    assert lines[0] == (
        "item_id,tile,acquired,cloud_cover,es_created,wo_found,wo_item_id,"
        "wo_created,wo_path_stamp,t_proc,lag_hours,available_at_proc,"
        "available_at_proc_plus2h"
    )
    assert lines[1].split(",")[2] == "2026-09-10"
    assert ",-3.000," in lines[2]


class FakePost:
    """Returns canned pages in order and records every (url, body) it saw."""

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = list(pages)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((url, dict(body)))
        return self.pages.pop(0)


def test_fetch_all_merges_the_link_body_when_merge_is_true() -> None:
    post = FakePost(
        [
            {
                "features": [{"id": "a"}],
                "links": [
                    {"rel": "self"},
                    {"rel": "next", "body": {"_o": 1}, "merge": True},
                ],
            },
            {
                "features": [{"id": "b"}],
                "links": [{"rel": "next", "body": {"_o": 2}, "merge": True}],
            },
            {"features": [{"id": "c"}], "links": []},
        ]
    )
    body = {"collections": ["c"], "limit": 1}
    features = availability.fetch_all(post, "https://x/search", body)
    assert [feature["id"] for feature in features] == ["a", "b", "c"]
    assert [call[1] for call in post.calls] == [
        {"collections": ["c"], "limit": 1},
        {"collections": ["c"], "limit": 1, "_o": 1},
        {"collections": ["c"], "limit": 1, "_o": 2},
    ]
    assert body == {"collections": ["c"], "limit": 1}


def test_fetch_all_uses_the_full_link_body_without_merge() -> None:
    post = FakePost(
        [
            {
                "features": [{"id": "a"}],
                "links": [
                    {"rel": "next", "body": {"collections": ["c"], "token": "t"}}
                ],
            },
            {"features": [{"id": "b"}], "links": []},
        ]
    )
    features = availability.fetch_all(post, "https://x/search", {"collections": ["c"]})
    assert [feature["id"] for feature in features] == ["a", "b"]
    assert post.calls[1][1] == {"collections": ["c"], "token": "t"}


def test_fetch_all_deduplicates_by_item_id() -> None:
    post = FakePost(
        [
            {
                "features": [{"id": "a"}, {"id": "b"}],
                "links": [{"rel": "next", "body": {"_o": 2}, "merge": True}],
            },
            {"features": [{"id": "b"}, {"id": "c"}], "links": []},
        ]
    )
    features = availability.fetch_all(post, "https://x/search", {})
    assert [feature["id"] for feature in features] == ["a", "b", "c"]


def test_fetch_all_stops_when_there_is_no_next_link() -> None:
    post = FakePost([{"features": [{"id": "a"}]}])
    assert availability.fetch_all(post, "https://x/search", {}) == [{"id": "a"}]
    assert len(post.calls) == 1
