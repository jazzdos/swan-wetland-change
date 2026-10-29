from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from shapely.geometry import box

from tests.conftest import REQUIRED_ASSETS
from wetland_change.catalogue.item import parse_timestamp
from wetland_change.catalogue.search import (
    STAC_RETRY_STATUSES,
    Discovery,
    build_search_kwargs,
    discover,
    make_stac_retry,
)
from wetland_change.config import StacConfig

CFG = StacConfig(
    endpoint="https://earth-search.aws.element84.com/v1",
    collection="sentinel-2-c1-l2a",
    cloud_cover_max=20.0,
    required_assets=REQUIRED_ASSETS,
)
THOMSONS_4326 = box(115.8168, -32.1615, 115.8421, -32.1378)
BBOX = THOMSONS_4326.bounds


class FakeSearch:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    def items_as_dicts(self) -> Iterator[dict[str, Any]]:
        yield from self._items


class FakeClient:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> FakeSearch:
        self.calls.append(kwargs)
        if "ids" in kwargs:
            return FakeSearch([i for i in self.items if i["id"] in kwargs["ids"]])
        return FakeSearch([i for i in self.items if not i.get("_retry_only")])


def _variant(item: dict[str, Any], suffix: str, **props: Any) -> dict[str, Any]:
    out = copy.deepcopy(item)
    out["id"] = f"{item['id']}_{suffix}"
    out["properties"].update(props)
    return out


def test_build_search_kwargs_uses_query_and_sort() -> None:
    since = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    kwargs = build_search_kwargs(CFG, bbox=BBOX, created_from=since)
    assert kwargs["collections"] == ["sentinel-2-c1-l2a"]
    assert kwargs["bbox"] == list(BBOX)
    assert kwargs["query"] == {
        "eo:cloud_cover": {"lt": 20.0},
        "created": {"gte": "2026-10-28T00:00:00Z"},
    }
    assert kwargs["sortby"] == [{"field": "properties.created", "direction": "asc"}]
    assert "ids" not in kwargs


def test_build_search_kwargs_without_watermark_or_with_ids() -> None:
    kwargs = build_search_kwargs(CFG, bbox=BBOX, created_from=None, ids=["a", "b"])
    assert "created" not in kwargs["query"]
    assert kwargs["ids"] == ["a", "b"]


def test_make_stac_retry_policy() -> None:
    retry = make_stac_retry()
    assert retry.total == 5
    assert set(STAC_RETRY_STATUSES) <= set(retry.status_forcelist)
    assert retry.allowed_methods is None
    assert retry.raise_on_status is False


def test_discover_rechecks_and_dedupes(fixture_item: dict[str, Any]) -> None:
    good = fixture_item
    cloudy = _variant(good, "cloudy", **{"eo:cloud_cover": 55.0})
    far = _variant(good, "far")
    far["geometry"] = {
        "type": "Polygon",
        "coordinates": [[[150, -30], [151, -30], [151, -29], [150, -29], [150, -30]]],
    }
    seen_copy = _variant(good, "seen")
    wrong = _variant(good, "wrong")
    wrong["collection"] = "sentinel-2-l2a"
    client = FakeClient([good, cloudy, far, seen_copy, wrong, copy.deepcopy(good)])
    result = discover(
        client,
        CFG,
        bbox=BBOX,
        polygons_4326=[THOMSONS_4326],
        created_from=None,
        seen={(seen_copy["id"], parse_timestamp(seen_copy["properties"]["updated"]))},
    )
    assert isinstance(result, Discovery)
    assert [s.item_id for s in result.scenes] == [good["id"]]
    assert result.skipped_seen == 1
    assert result.skipped_filter == 2
    assert result.rejected == [(wrong["id"], result.rejected[0][1])]
    assert "collection" in result.rejected[0][1]


def test_discover_fetches_retry_ids_by_id(fixture_item: dict[str, Any]) -> None:
    retry_item = _variant(fixture_item, "retry")
    retry_item["_retry_only"] = True
    client = FakeClient([fixture_item, retry_item])
    result = discover(
        client,
        CFG,
        bbox=BBOX,
        polygons_4326=[THOMSONS_4326],
        created_from=datetime(2026, 10, 28, tzinfo=UTC),
        seen=set(),
        retry_ids=[retry_item["id"]],
    )
    assert len(client.calls) == 2
    assert client.calls[1]["ids"] == [retry_item["id"]]
    assert "created" not in client.calls[1]["query"]
    assert {s.item_id for s in result.scenes} == {fixture_item["id"], retry_item["id"]}


def test_discover_rejects_malformed_item_without_aborting(
    fixture_item: dict[str, Any],
) -> None:
    good = fixture_item
    bad = _variant(good, "malformed")
    del bad["properties"]["s2:processing_baseline"]
    client = FakeClient([bad, good])
    result = discover(
        client,
        CFG,
        bbox=BBOX,
        polygons_4326=[THOMSONS_4326],
        created_from=None,
        seen=set(),
    )
    assert [s.item_id for s in result.scenes] == [good["id"]]
    assert [item_id for item_id, _ in result.rejected] == [bad["id"]]
    assert "KeyError" in result.rejected[0][1]


RANGE_START = datetime(2026, 10, 26, tzinfo=UTC)
RANGE_END = datetime(2026, 10, 28, 23, 59, 59, 999999, tzinfo=UTC)
RANGE_STRING = "2026-10-26T00:00:00Z/2026-10-28T23:59:59.999999Z"


def test_build_search_kwargs_with_datetime_range() -> None:
    kwargs = build_search_kwargs(
        CFG,
        bbox=BBOX,
        created_from=None,
        datetime_range=(RANGE_START, RANGE_END),
    )
    assert kwargs["datetime"] == RANGE_STRING
    assert kwargs["query"] == {"eo:cloud_cover": {"lt": 20.0}}
    assert kwargs["sortby"] == [{"field": "properties.created", "direction": "asc"}]


def test_build_search_kwargs_range_converts_to_utc() -> None:
    start = datetime(2026, 10, 26, 8, tzinfo=timezone(timedelta(hours=8)))
    kwargs = build_search_kwargs(
        CFG, bbox=BBOX, created_from=None, datetime_range=(start, RANGE_END)
    )
    assert kwargs["datetime"].startswith("2026-10-26T00:00:00Z/")


def test_build_search_kwargs_rejects_bad_range() -> None:
    naive = datetime(2026, 10, 26)
    with pytest.raises(ValueError):
        build_search_kwargs(
            CFG, bbox=BBOX, created_from=None, datetime_range=(naive, RANGE_END)
        )
    with pytest.raises(ValueError):
        build_search_kwargs(
            CFG, bbox=BBOX, created_from=None, datetime_range=(RANGE_START, naive)
        )
    with pytest.raises(ValueError):
        build_search_kwargs(
            CFG,
            bbox=BBOX,
            created_from=None,
            datetime_range=(RANGE_END, RANGE_START),
        )


def test_build_search_kwargs_without_range_has_no_datetime() -> None:
    since = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    kwargs = build_search_kwargs(CFG, bbox=BBOX, created_from=since)
    assert "datetime" not in kwargs


def test_discover_rechecks_datetime_range(fixture_item: dict[str, Any]) -> None:
    good = fixture_item
    at_start = _variant(good, "at_start", datetime="2026-10-26T00:00:00Z")
    at_end = _variant(good, "at_end", datetime="2026-10-28T23:59:59.999999Z")
    before = _variant(good, "before", datetime="2026-10-25T23:59:59Z")
    after = _variant(good, "after", datetime="2026-10-29T00:00:00Z")
    baddate = _variant(good, "baddate", datetime="not-a-date")
    client = FakeClient([good, at_start, at_end, before, after, baddate])
    result = discover(
        client,
        CFG,
        bbox=BBOX,
        polygons_4326=[THOMSONS_4326],
        created_from=None,
        seen=set(),
        datetime_range=(RANGE_START, RANGE_END),
    )
    assert {s.item_id for s in result.scenes} == {
        good["id"],
        at_start["id"],
        at_end["id"],
    }
    assert result.skipped_filter == 2
    assert [item_id for item_id, _ in result.rejected] == [baddate["id"]]
    assert client.calls[0]["datetime"] == RANGE_STRING
    assert "created" not in client.calls[0]["query"]
