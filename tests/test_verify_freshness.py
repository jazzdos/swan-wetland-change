from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pyarrow as pa
import pytest
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from tests.test_verify_copernicus import (
    AOI_SMALL,
    BBOX,
    CFG,
    COVERS_SMALL,
    FIXTURES,
    MISSES_SMALL,
    NOW,
    OUTSIDE,
    POLYGONS,
    RecordingClient,
    cdse_item,
    es_item,
    name,
)
from wetland_change.ledger import MAX_ATTEMPTS, LedgerEntry, entries_to_table
from wetland_change.verify.checks import Check
from wetland_change.verify.copernicus import CDSE_COLLECTION, CDSE_STAC
from wetland_change.verify.freshness import (
    CHECK_CDSE,
    CHECK_ES,
    CHECK_EXHAUSTED,
    CHECK_NEWEST,
    MAX_AGE,
    SWAN_TILES,
    WINDOW,
    count_checks,
    exhausted_items_check,
    freshness_checks,
    list_tile_counts,
    newest_item_check,
)

OLD = "2026-10-05T02:12:11"
OLD2 = "2026-10-12T02:12:11"
RECENT = "2026-10-29T02:12:11"
BEFORE_WINDOW = "2026-09-20T02:12:11"


class RaisingClient:
    def search(self, **kwargs: Any) -> Any:
        raise RuntimeError("catalogue down")


def when(sensed: str) -> datetime:
    return datetime.fromisoformat(sensed).replace(tzinfo=UTC)


def row(
    sensed: str,
    *,
    tile: str = "T50HLK",
    status: str = "succeeded",
    processed_at: datetime = NOW,
    run_id: str = "r1",
    item_id: str | None = None,
    product_uri: str | None = None,
) -> LedgerEntry:
    return LedgerEntry(
        item_id=item_id or f"ES_{sensed}_{tile}",
        collection="sentinel-2-c1-l2a",
        datetime=when(sensed),
        created=when(sensed),
        updated=when(sensed),
        tile=tile[1:],
        cloud_cover=5.0,
        product_uri=product_uri or name(sensed, tile) + ".SAFE",
        status=status,
        attempts=1,
        error=None,
        run_id=run_id,
        processed_at=processed_at,
        n_rows=1,
        observation_path=None,
        source_item=None,
    )


def table(*entries: LedgerEntry) -> pa.Table:
    return entries_to_table(list(entries))


def counts(
    ledger: pa.Table,
    es: list[dict[str, Any]],
    cdse: list[dict[str, Any]],
    *,
    polygons: list[BaseGeometry] | None = None,
    bbox: tuple[float, float, float, float] = BBOX,
) -> list[Check]:
    return count_checks(
        ledger,
        RecordingClient(es),
        RecordingClient(cdse),
        CFG,
        bbox=bbox,
        polygons_4326=POLYGONS if polygons is None else polygons,
        now=NOW,
    )


def pick(checks: list[Check], check_name: str, tile: str = "50HLK") -> Check:
    (found,) = [c for c in checks if c.name == check_name and c.detail["tile"] == tile]
    return found


def test_constants() -> None:
    assert WINDOW == timedelta(days=30)
    assert MAX_AGE == timedelta(days=7)
    assert SWAN_TILES == ("50HLJ", "50HLK", "50HMJ", "50HMK", "50JLL", "50JML")


def test_newest_item_8_days_old_fails() -> None:
    sensed = (NOW - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S")
    check = newest_item_check(table(row(sensed)), NOW)
    assert check.name == CHECK_NEWEST
    assert check.passed is False
    assert check.measured == pytest.approx(8.0)
    assert check.threshold == 7.0
    assert check.reference == "ledger newest processed item"


def test_newest_item_6_days_old_passes() -> None:
    sensed = (NOW - timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%S")
    check = newest_item_check(table(row(sensed)), NOW)
    assert check.passed is True
    assert check.measured == pytest.approx(6.0)


def test_newest_item_empty_ledger_fails() -> None:
    check = newest_item_check(table(), NOW)
    assert check.passed is False
    assert check.measured is None
    assert "reason" in check.detail


def test_newest_item_ignores_failed_rows() -> None:
    old = (NOW - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%S")
    new = (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    check = newest_item_check(table(row(old), row(new, status="failed")), NOW)
    assert check.passed is False
    assert check.measured == pytest.approx(9.0)


def test_newest_item_only_failed_rows_fails() -> None:
    check = newest_item_check(table(row(OLD, status="failed")), NOW)
    assert check.passed is False
    assert check.measured is None


def test_newest_item_uses_latest_row_per_item() -> None:
    recent = (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    first = row(recent, status="succeeded", processed_at=NOW - timedelta(hours=2))
    later = row(recent, status="failed", processed_at=NOW - timedelta(hours=1))
    check = newest_item_check(table(first, later), NOW)
    assert check.passed is False
    assert check.measured is None


def test_newest_item_taken_across_rows() -> None:
    ages = [10, 3, 20]
    entries = [
        row((NOW - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S")) for d in ages
    ]
    check = newest_item_check(table(*entries), NOW)
    assert check.passed is True
    assert check.measured == pytest.approx(3.0)


# ES counts


def test_es_agreement_passes() -> None:
    checks = counts(table(row(OLD), row(OLD2)), [es_item(OLD), es_item(OLD2)], [])
    check = pick(checks, CHECK_ES)
    assert check.passed is True
    assert check.measured == 0.0
    assert check.threshold == 0.0
    assert check.reference == f"{CFG.endpoint} {CFG.collection}"
    d = check.detail
    assert d["ledger_count"] == 2
    assert d["reference_count"] == 2
    assert d["missing_from_ledger"] == []
    assert d["missing_from_reference"] == []
    assert d["pending_latency"] == []
    assert d["latency_hours"] == 24
    assert d["window_start"] == (NOW - WINDOW).isoformat()
    assert d["window_end"] == NOW.isoformat()


def test_es_old_item_absent_from_ledger_fails_only_that_tile() -> None:
    checks = counts(
        table(row(OLD2, tile="T50HMK")),
        [es_item(OLD), es_item(OLD2, tile="T50HMK")],
        [],
    )
    check = pick(checks, CHECK_ES)
    assert check.passed is False
    assert check.measured == 1.0
    assert check.detail["missing_from_ledger"] == [name(OLD)]
    assert pick(checks, CHECK_ES, "50HMK").passed is True


def test_es_recent_item_absent_from_ledger_is_pending() -> None:
    check = pick(counts(table(), [es_item(RECENT)], []), CHECK_ES)
    assert check.passed is True
    assert check.measured == 0.0
    assert check.detail["pending_latency"] == [name(RECENT)]
    assert check.detail["missing_from_ledger"] == []
    assert check.detail["reference_count"] == 1


def test_es_ledger_only_old_item_fails() -> None:
    check = pick(counts(table(row(OLD)), [], []), CHECK_ES)
    assert check.passed is False
    assert check.measured == 1.0
    assert check.detail["missing_from_reference"] == [name(OLD)]
    assert check.detail["ledger_count"] == 1


def test_es_items_older_than_window_are_ignored() -> None:
    checks = counts(table(row(BEFORE_WINDOW)), [es_item(BEFORE_WINDOW)], [])
    check = pick(checks, CHECK_ES)
    assert check.passed is True
    assert check.detail["ledger_count"] == 0
    assert check.detail["reference_count"] == 0


def test_es_ledger_ignores_failed_and_rejected_rows() -> None:
    entries = [
        row(OLD, status="failed"),
        row(OLD2, status="rejected", tile="T50HLK"),
    ]
    check = pick(counts(table(*entries), [], []), CHECK_ES)
    assert check.passed is True
    assert check.detail["ledger_count"] == 0


def test_es_ledger_row_without_product_uri_is_a_mismatch_by_item_id() -> None:
    entry = LedgerEntry(**{**row(OLD).__dict__, "product_uri": None})
    check = pick(counts(table(entry), [], []), CHECK_ES)
    assert check.passed is False
    assert check.detail["missing_from_reference"] == [entry.item_id]


# CDSE counts


def test_cdse_agreement_passes_across_baselines() -> None:
    checks = counts(
        table(row(OLD)), [], [cdse_item(OLD, baseline="N0512", gen="20261005T090000")]
    )
    check = pick(checks, CHECK_CDSE)
    assert check.passed is True
    assert check.measured == 0.0
    assert check.threshold == 0.0
    assert check.reference == f"{CDSE_STAC} {CDSE_COLLECTION}"
    assert check.detail["ledger_count"] == 1
    assert check.detail["reference_count"] == 1


def test_cdse_duplicated_datatake_counts_once() -> None:
    cdse = [
        cdse_item(OLD, baseline="N0512", gen="20261005T090000"),
        cdse_item(OLD, baseline="N0511", gen="20261006T090000"),
    ]
    check = pick(counts(table(row(OLD)), [], cdse), CHECK_CDSE)
    assert check.passed is True
    assert check.detail["reference_count"] == 1


def test_cdse_old_item_absent_from_ledger_fails_only_that_tile() -> None:
    cdse = [cdse_item(OLD), cdse_item(OLD2, tile="T50HMK")]
    checks = counts(table(row(OLD2, tile="T50HMK")), [], cdse)
    check = pick(checks, CHECK_CDSE)
    assert check.passed is False
    assert check.measured == 1.0
    assert check.detail["missing_from_ledger"] == [name(OLD, baseline="N0512")]
    assert pick(checks, CHECK_CDSE, "50HMK").passed is True


def test_cdse_recent_item_absent_from_ledger_is_pending() -> None:
    cdse = [cdse_item(RECENT)]
    check = pick(counts(table(), [], cdse), CHECK_CDSE)
    assert check.passed is True
    assert check.detail["pending_latency"] == [cdse[0]["id"]]


def test_cdse_ledger_only_old_item_fails() -> None:
    check = pick(counts(table(row(OLD)), [], []), CHECK_CDSE)
    assert check.passed is False
    assert check.detail["missing_from_reference"] == [name(OLD)]


def test_cdse_items_older_than_window_are_ignored() -> None:
    checks = counts(table(row(BEFORE_WINDOW)), [], [cdse_item(BEFORE_WINDOW)])
    check = pick(checks, CHECK_CDSE)
    assert check.passed is True
    assert check.detail["ledger_count"] == 0
    assert check.detail["reference_count"] == 0


def test_cdse_unbuildable_ledger_key_is_a_mismatch_not_an_error() -> None:
    entry = row(OLD, product_uri="not-a-product-name.SAFE")
    check = pick(counts(table(entry), [], []), CHECK_CDSE)
    assert check.passed is False
    assert check.detail["missing_from_reference"] == [entry.item_id]


# Tile universe and failures


def test_all_swan_tiles_appear_and_pass_when_empty() -> None:
    checks = counts(table(), [], [])
    assert len(checks) == 2 * len(SWAN_TILES)
    for check_name in (CHECK_ES, CHECK_CDSE):
        named = [c for c in checks if c.name == check_name]
        assert [c.detail["tile"] for c in named] == list(SWAN_TILES)
        assert all(c.passed is True and c.measured == 0.0 for c in named)


def test_extra_tile_seen_on_any_side_is_added_in_order() -> None:
    checks = counts(table(), [es_item(OLD, tile="T50KPA")], [])
    tiles = [c.detail["tile"] for c in checks if c.name == CHECK_ES]
    assert tiles == sorted([*SWAN_TILES, "50KPA"])


def test_failing_es_search_skips_only_es_checks() -> None:
    checks = count_checks(
        table(row(OLD)),
        RaisingClient(),
        RecordingClient([cdse_item(OLD)]),
        CFG,
        bbox=BBOX,
        polygons_4326=POLYGONS,
        now=NOW,
    )
    es_checks = [c for c in checks if c.name == CHECK_ES]
    assert es_checks
    for c in es_checks:
        assert c.passed is None
        assert c.measured is None
        assert c.threshold is None
        assert c.reference == "check did not run"
        assert c.detail["error"] == "RuntimeError: catalogue down"
    cdse_checks = [c for c in checks if c.name == CHECK_CDSE]
    assert all(c.passed is not None for c in cdse_checks)
    assert pick(checks, CHECK_CDSE).passed is True


def test_failing_cdse_search_skips_only_cdse_checks() -> None:
    checks = count_checks(
        table(),
        RecordingClient([]),
        RaisingClient(),
        CFG,
        bbox=BBOX,
        polygons_4326=POLYGONS,
        now=NOW,
    )
    assert all(c.passed is None for c in checks if c.name == CHECK_CDSE)
    assert all(c.passed is True for c in checks if c.name == CHECK_ES)


def test_search_kwargs() -> None:
    es_client = RecordingClient([])
    cdse_client = RecordingClient([])
    count_checks(
        table(),
        es_client,
        cdse_client,
        CFG,
        bbox=BBOX,
        polygons_4326=POLYGONS,
        now=NOW,
    )
    window = "2026-09-29T10:00:00Z/2026-10-29T10:00:00Z"
    (es_kwargs,) = es_client.calls
    assert es_kwargs["collections"] == ["sentinel-2-c1-l2a"]
    assert es_kwargs["bbox"] == list(BBOX)
    assert es_kwargs["datetime"] == window
    assert es_kwargs["query"] == {"eo:cloud_cover": {"lt": 20.0}}
    (cdse_kwargs,) = cdse_client.calls
    assert cdse_kwargs["collections"] == ["sentinel-2-l2a"]
    assert cdse_kwargs["datetime"] == window
    assert "query" not in cdse_kwargs


def test_freshness_checks_concatenates_newest_exhausted_es_then_cdse() -> None:
    recent = (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    checks = freshness_checks(
        table(row(recent)),
        RecordingClient([es_item(recent)]),
        RecordingClient([cdse_item(recent)]),
        CFG,
        bbox=BBOX,
        polygons_4326=POLYGONS,
        now=NOW,
    )
    names = [c.name for c in checks]
    n = len(SWAN_TILES)
    assert names == [CHECK_NEWEST, CHECK_EXHAUSTED] + [CHECK_ES] * n + [CHECK_CDSE] * n
    assert all(c.passed is True for c in checks)


# exhausted_items_check


def failed_row(sensed: str, attempts: int, **kwargs: Any) -> LedgerEntry:
    return dataclasses.replace(
        row(sensed, status="failed", **kwargs), attempts=attempts, error="boom"
    )


def test_exhausted_check_fails_with_the_item_ids() -> None:
    ledger = table(
        failed_row(RECENT, MAX_ATTEMPTS, item_id="b"),
        failed_row(RECENT, MAX_ATTEMPTS, item_id="a"),
        failed_row(RECENT, MAX_ATTEMPTS - 1, item_id="retrying"),
        row(RECENT, item_id="ok"),
    )
    check = exhausted_items_check(ledger)
    assert check.name == CHECK_EXHAUSTED
    assert check.passed is False
    assert check.measured == 2.0
    assert check.threshold == 0.0
    assert check.detail == {"item_ids": ["a", "b"], "max_attempts": MAX_ATTEMPTS}
    assert "tile" not in check.detail


def test_exhausted_check_passes_without_exhausted_items() -> None:
    check = exhausted_items_check(
        table(row(RECENT), failed_row(RECENT, 1, item_id="retrying"))
    )
    assert check.passed is True
    assert check.measured == 0.0
    assert check.detail["item_ids"] == []


def test_exhausted_check_passes_on_empty_ledger() -> None:
    assert exhausted_items_check(table()).passed is True


def test_exhausted_check_ignores_items_superseded_by_success() -> None:
    ledger = table(
        failed_row(RECENT, MAX_ATTEMPTS, item_id="x", processed_at=NOW),
        row(
            RECENT,
            item_id="x",
            run_id="r2",
            processed_at=NOW + timedelta(hours=1),
        ),
    )
    assert exhausted_items_check(ledger).passed is True


# list_tile_counts

START = datetime(2026, 9, 1, tzinfo=UTC)


def test_list_tile_counts_es() -> None:
    items = [
        es_item(OLD),
        es_item(OLD2),
        es_item(OLD, tile="T50HMK"),
    ]
    result = list_tile_counts(
        RecordingClient(items),
        CFG,
        bbox=BBOX,
        polygons_4326=POLYGONS,
        start=START,
        end=NOW,
        cdse=False,
    )
    assert result == {"50HLK": 2, "50HMK": 1}


def test_list_tile_counts_cdse_dedups_datatakes() -> None:
    items = [
        cdse_item(OLD),
        cdse_item(OLD, baseline="N0511", gen="20261006T090000"),
        cdse_item(OLD2, tile="T50HMK"),
    ]
    result = list_tile_counts(
        RecordingClient(items),
        CFG,
        bbox=BBOX,
        polygons_4326=POLYGONS,
        start=START,
        end=NOW,
        cdse=True,
    )
    assert result == {"50HLK": 1, "50HMK": 1}


def test_list_tile_counts_applies_cloud_and_footprint_filters() -> None:
    es_items = [
        es_item(OLD),
        es_item(OLD2, cloud=50.0),
        es_item("2026-10-13T02:12:11", geometry=OUTSIDE),
    ]
    result = list_tile_counts(
        RecordingClient(es_items),
        CFG,
        bbox=BBOX,
        polygons_4326=POLYGONS,
        start=START,
        end=NOW,
        cdse=False,
    )
    assert result == {"50HLK": 1}


def test_list_tile_counts_applies_the_window_locally() -> None:
    items = [es_item(OLD), es_item("2026-08-01T02:12:11")]
    result = list_tile_counts(
        RecordingClient(items),
        CFG,
        bbox=BBOX,
        polygons_4326=POLYGONS,
        start=START,
        end=NOW,
        cdse=False,
    )
    assert result == {"50HLK": 1}


def test_list_tile_counts_search_kwargs() -> None:
    client = RecordingClient([])
    list_tile_counts(
        client,
        CFG,
        bbox=BBOX,
        polygons_4326=POLYGONS,
        start=START,
        end=NOW,
        cdse=False,
    )
    (kwargs,) = client.calls
    assert kwargs["datetime"] == "2026-09-01T00:00:00Z/2026-10-29T10:00:00Z"
    assert kwargs["query"] == {"eo:cloud_cover": {"lt": 20.0}}


def test_cdse_only_footprint_edge_is_reported_not_counted() -> None:
    es = [es_item(OLD, geometry=MISSES_SMALL)]
    cdse = [cdse_item(OLD, geometry=COVERS_SMALL)]
    check = pick(counts(table(), es, cdse, polygons=AOI_SMALL), CHECK_CDSE)
    assert check.passed is True
    assert check.measured == 0.0
    assert check.detail["footprint_edge"] == [cdse[0]["id"]]
    assert check.detail["missing_from_ledger"] == []
    assert check.detail["missing_from_reference"] == []


def test_cdse_only_footprint_edge_leaves_earth_search_check_unchanged() -> None:
    es = [es_item(OLD, geometry=MISSES_SMALL)]
    cdse = [cdse_item(OLD, geometry=COVERS_SMALL)]
    check = pick(counts(table(), es, cdse, polygons=AOI_SMALL), CHECK_ES)
    assert check.passed is True
    assert "footprint_edge" not in check.detail
    assert check.detail["ledger_count"] == 0
    assert check.detail["reference_count"] == 0


def test_earth_search_only_footprint_edge_is_reported_not_counted() -> None:
    es = [es_item(OLD, geometry=COVERS_SMALL)]
    cdse = [cdse_item(OLD, geometry=MISSES_SMALL)]
    checks = counts(table(row(OLD)), es, cdse, polygons=AOI_SMALL)
    check = pick(checks, CHECK_CDSE)
    assert check.passed is True
    assert check.measured == 0.0
    assert check.detail["footprint_edge"] == [cdse[0]["id"]]
    assert check.detail["ledger_count"] == 0
    assert check.detail["reference_count"] == 0
    es_check = pick(checks, CHECK_ES)
    assert es_check.passed is True
    assert es_check.detail["reference_count"] == 1


def test_datatake_listed_only_by_cdse_still_fails() -> None:
    cdse = [cdse_item(OLD, geometry=COVERS_SMALL)]
    check = pick(counts(table(), [], cdse, polygons=AOI_SMALL), CHECK_CDSE)
    assert check.passed is False
    assert check.measured == 1.0
    assert check.detail["missing_from_ledger"] == [cdse[0]["id"]]
    assert check.detail["footprint_edge"] == []


def test_failing_es_search_leaves_cdse_on_its_own_footprint() -> None:
    cdse = [
        cdse_item(OLD, geometry=COVERS_SMALL),
        cdse_item(OLD2, geometry=MISSES_SMALL),
    ]
    checks = count_checks(
        table(),
        RaisingClient(),  # type: ignore[arg-type]
        RecordingClient(cdse),
        CFG,
        bbox=BBOX,
        polygons_4326=AOI_SMALL,
        now=NOW,
    )
    check = pick(checks, CHECK_CDSE)
    assert check.passed is False
    assert check.detail["missing_from_ledger"] == [cdse[0]["id"]]
    assert check.detail["reference_count"] == 1
    assert check.detail["footprint_edge"] == []


def test_footprint_edge_stays_on_its_own_tile() -> None:
    es = [es_item(OLD, geometry=MISSES_SMALL)]
    cdse = [cdse_item(OLD, geometry=COVERS_SMALL)]
    checks = counts(table(), es, cdse, polygons=AOI_SMALL)
    assert pick(checks, CHECK_CDSE, "50HLK").detail["footprint_edge"] == [cdse[0]["id"]]
    assert pick(checks, CHECK_CDSE, "50HMK").detail["footprint_edge"] == []


def test_real_footprint_edge_50hmk_20261014() -> None:
    es_json = json.loads((FIXTURES / "es_item.json").read_text())
    cdse_json = json.loads((FIXTURES / "cdse_item.json").read_text())
    feature = json.loads((FIXTURES / "dea_qd4xhuft4_v3.geojson").read_text())[
        "features"
    ][0]
    polygon = shape(feature["geometry"])
    checks = counts(
        table(),
        [es_json],
        [cdse_json],
        polygons=[polygon],
        bbox=polygon.buffer(0.01).bounds,
    )
    cdse_check = pick(checks, CHECK_CDSE, "50HMK")
    assert cdse_check.passed is True
    assert cdse_check.measured == 0.0
    assert cdse_check.detail["footprint_edge"] == [
        "S2C_MSIL2A_20261014T020311_N0513_R017_T50HMK_20261014T062152"
    ]
    es_check = pick(checks, CHECK_ES, "50HMK")
    assert es_check.passed is True
    assert es_check.measured == 0.0
