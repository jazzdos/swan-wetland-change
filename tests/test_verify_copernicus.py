from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from shapely.geometry import box, mapping
from shapely.geometry.base import BaseGeometry

from tests.test_pipeline import FakeSearch
from wetland_change.config import StacConfig
from wetland_change.verify.checks import Check
from wetland_change.verify.copernicus import (
    CDSE_COLLECTION,
    CDSE_STAC,
    CHECK_NAME,
    datatake_key,
    discovery_checks,
    run_window,
)

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
START = datetime(2026, 9, 1, tzinfo=UTC)
BBOX = (115.8, -32.2, 115.9, -32.1)
POLYGONS: list[BaseGeometry] = [box(*BBOX)]
INSIDE = mapping(box(115.82, -32.18, 115.85, -32.15))
OUTSIDE = mapping(box(120.0, -20.0, 120.1, -19.9))
CFG = StacConfig(
    endpoint="https://example.invalid",
    collection="sentinel-2-c1-l2a",
    cloud_cover_max=20.0,
)


class RecordingClient:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> FakeSearch:
        self.calls.append(kwargs)
        return FakeSearch(self.items)


def name(
    sensed: str, tile: str = "T50HLK", baseline: str = "N0513", gen: str = "x"
) -> str:
    stamp = sensed.replace("-", "").replace(":", "")
    generated = gen if gen != "x" else stamp[:9] + "071801"
    return f"S2C_MSIL2A_{stamp}_{baseline}_R060_{tile}_{generated}"


def es_item(
    sensed: str,
    *,
    tile: str = "T50HLK",
    baseline: str = "N0513",
    cloud: float | None = 5.0,
    geometry: dict[str, Any] = INSIDE,
) -> dict[str, Any]:
    product = name(sensed, tile, baseline)
    props: dict[str, Any] = {
        "datetime": sensed + "Z",
        "grid:code": f"MGRS-{tile[1:]}",
        "s2:product_uri": product + ".SAFE",
    }
    if cloud is not None:
        props["eo:cloud_cover"] = cloud
    return {"id": f"ES_{sensed}_{tile}", "geometry": geometry, "properties": props}


def cdse_item(
    sensed: str,
    *,
    tile: str = "T50HLK",
    baseline: str = "N0512",
    gen: str = "x",
    cloud: float | None = 5.0,
    geometry: dict[str, Any] = INSIDE,
    grid: bool = True,
) -> dict[str, Any]:
    props: dict[str, Any] = {"datetime": sensed + "Z"}
    if grid:
        props["grid:code"] = f"MGRS-{tile[1:]}"
    if cloud is not None:
        props["eo:cloud_cover"] = cloud
    return {
        "id": name(sensed, tile, baseline, gen),
        "geometry": geometry,
        "properties": props,
    }


def run(es: list[dict[str, Any]], cdse: list[dict[str, Any]]) -> list[Check]:
    return discovery_checks(
        RecordingClient(es),
        RecordingClient(cdse),
        CFG,
        bbox=BBOX,
        polygons_4326=POLYGONS,
        start=START,
        end=NOW,
        now=NOW,
    )


OLD = "2026-10-05T02:12:11"
OLD2 = "2026-09-20T02:12:11"
RECENT = "2026-10-29T02:12:11"


def test_matching_listings_pass_with_month_counts() -> None:
    es = [es_item(OLD), es_item(OLD2)]
    cdse = [cdse_item(OLD), cdse_item(OLD2)]
    (check,) = run(es, cdse)
    assert check.name == CHECK_NAME
    assert check.passed is True
    assert check.measured == 0.0
    assert check.threshold == 0.0
    assert check.reference == f"{CDSE_STAC} {CDSE_COLLECTION}"
    d = check.detail
    assert d["tile"] == "50HLK"
    assert d["months"] == {
        "2026-09": {"earth_search": 1, "cdse": 1},
        "2026-10": {"earth_search": 1, "cdse": 1},
    }
    assert d["missing_from_earth_search"] == []
    assert d["missing_from_cdse"] == []
    assert d["pending_latency"] == []
    assert d["latency_hours"] == 24
    assert d["window_start"] == START.isoformat()
    assert d["window_end"] == NOW.isoformat()


def test_old_cdse_only_product_fails() -> None:
    cdse = [cdse_item(OLD)]
    (check,) = run([es_item(OLD2)], [*cdse, cdse_item(OLD2)])
    assert check.passed is False
    assert check.measured == 1.0
    assert check.detail["missing_from_earth_search"] == [cdse[0]["id"]]
    assert check.detail["missing_from_cdse"] == []
    assert check.detail["months"]["2026-10"] == {"earth_search": 0, "cdse": 1}


def test_recent_cdse_only_product_is_pending_latency() -> None:
    cdse = [cdse_item(RECENT)]
    (check,) = run([], cdse)
    assert check.passed is True
    assert check.measured == 0.0
    assert check.detail["pending_latency"] == [cdse[0]["id"]]
    assert check.detail["missing_from_earth_search"] == []


def test_baseline_and_generation_differences_match_and_duplicates_count_once() -> None:
    es = [es_item(OLD, baseline="N0513")]
    cdse = [
        cdse_item(OLD, baseline="N0512", gen="20261005T090000"),
        cdse_item(OLD, baseline="N0511", gen="20261006T090000"),
    ]
    (check,) = run(es, cdse)
    assert check.passed is True
    assert check.detail["months"]["2026-10"] == {"earth_search": 1, "cdse": 1}


def test_old_earth_search_only_product_fails() -> None:
    es = [es_item(OLD)]
    (check,) = run(es, [cdse_item(OLD2)])
    assert check.passed is False
    assert check.measured == 2.0
    assert check.detail["missing_from_cdse"] == [name(OLD)]
    assert check.detail["missing_from_earth_search"] == [name(OLD2, baseline="N0512")]


def test_recent_earth_search_only_product_is_pending() -> None:
    (check,) = run([es_item(RECENT)], [])
    assert check.passed is True
    assert check.detail["pending_latency"] == [name(RECENT)]


def test_over_cloud_and_outside_polygon_items_are_ignored_on_both_sides() -> None:
    es = [
        es_item(OLD),
        es_item(OLD2, cloud=60.0),
        es_item("2026-09-25T02:12:11", geometry=OUTSIDE),
        es_item("2026-09-26T02:12:11", cloud=None),
    ]
    cdse = [
        cdse_item(OLD),
        cdse_item(OLD2, cloud=20.0),
        cdse_item("2026-09-27T02:12:11", geometry=OUTSIDE),
        cdse_item("2026-09-28T02:12:11", cloud=None),
    ]
    (check,) = run(es, cdse)
    assert check.passed is True
    assert check.measured == 0.0
    assert check.detail["months"] == {"2026-10": {"earth_search": 1, "cdse": 1}}


def test_two_tiles_give_two_checks_in_tile_order() -> None:
    es = [es_item(OLD, tile="T50HMK"), es_item(OLD, tile="T50HLK")]
    cdse = [cdse_item(OLD, tile="T50HLK"), cdse_item(OLD, tile="T50HMK")]
    checks = run(es, cdse)
    assert [c.detail["tile"] for c in checks] == ["50HLK", "50HMK"]
    assert all(c.name == CHECK_NAME and c.passed for c in checks)


def test_cdse_tile_falls_back_to_id_token() -> None:
    (check,) = run([es_item(OLD)], [cdse_item(OLD, grid=False)])
    assert check.passed is True
    assert check.detail["tile"] == "50HLK"


def test_empty_listings_give_one_skipped_check() -> None:
    (check,) = run([], [])
    assert check.name == CHECK_NAME
    assert check.passed is None
    assert check.measured is None
    assert check.threshold is None
    assert check.reference == f"{CDSE_STAC} {CDSE_COLLECTION}"
    assert check.detail == {
        "reason": "no items listed by either catalogue in the run window"
    }


def test_search_kwargs() -> None:
    es_client = RecordingClient([])
    cdse_client = RecordingClient([])
    discovery_checks(
        es_client,
        cdse_client,
        CFG,
        bbox=BBOX,
        polygons_4326=POLYGONS,
        start=START,
        end=NOW,
        now=NOW,
    )
    window = "2026-09-01T00:00:00Z/2026-10-29T10:00:00Z"
    (es_kwargs,) = es_client.calls
    assert es_kwargs["collections"] == ["sentinel-2-c1-l2a"]
    assert es_kwargs["bbox"] == list(BBOX)
    assert es_kwargs["datetime"] == window
    assert es_kwargs["query"] == {"eo:cloud_cover": {"lt": 20.0}}
    (cdse_kwargs,) = cdse_client.calls
    assert cdse_kwargs["collections"] == ["sentinel-2-l2a"]
    assert cdse_kwargs["bbox"] == list(BBOX)
    assert cdse_kwargs["datetime"] == window


def test_datatake_key_drops_baseline_and_generation_time() -> None:
    a = "S2C_MSIL2A_20261027T021211_N0513_R060_T50HLK_20261027T071801"
    b = "S2C_MSIL2A_20261027T021211_N0512_R060_T50HLK_20261028T101500.SAFE"
    assert datatake_key(a) == "S2C_MSIL2A_20261027T021211_R060_T50HLK"
    assert datatake_key(b) == datatake_key(a)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "S2C_MSIL2A_20261027T021211_R060_T50HLK",
        "S2C_MSIL2A_20261027T021211_N0513_R060_T50HLK_20261027T071801_extra",
        "S2C_MSIL2A_20261027T021211_X0513_R060_T50HLK_20261027T071801",
    ],
)
def test_datatake_key_rejects_malformed_names(bad: str) -> None:
    with pytest.raises(ValueError):
        datatake_key(bad)


def test_run_window() -> None:
    scenes = [
        datetime(2026, 10, 5, 13, 30, tzinfo=UTC),
        datetime(2026, 9, 20, 23, 59, tzinfo=UTC),
    ]
    start, end = run_window(scenes, NOW)
    assert start == datetime(2026, 9, 20, tzinfo=UTC)
    assert end == NOW
