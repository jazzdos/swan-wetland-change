"""Is the DEA WO item there when the daily run first processes a scene-tile?

Implements the st-5f74 pre-registration in LEARNINGS.md. For every Earth Search
`sentinel-2-c1-l2a` item in the sample it finds the matching DEA
`ga_s2_wo_provisional_3` item (same UTC acquisition date and MGRS tile, the rule
of `find_wo_href` in `src/wetland_change/verify/wo.py`) and compares the DEA
index time (`properties.created`) with the first scheduled run (10:17:00 UTC)
at or after the Earth Search `created` time. Public anonymous STAC reads only,
no rasters.

  uv run python docs/research/2026-11-06-wo-availability.py \
      [--out CSV] [--report TXT]

Output paths default to files beside this script.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Final

import requests

HERE: Final = Path(__file__).resolve().parent
DEFAULT_OUT: Final = HERE / "2026-11-06-wo-availability.csv"
DEFAULT_REPORT: Final = HERE / "2026-11-06-wo-availability.txt"

EARTH_SEARCH_URL: Final = "https://earth-search.aws.element84.com/v1/search"
EARTH_SEARCH_COLLECTION: Final = "sentinel-2-c1-l2a"
DEA_URL: Final = "https://explorer.dea.ga.gov.au/stac/search"
DEA_COLLECTION: Final = "ga_s2_wo_provisional_3"
# Approximation of the AOI union bbox (the AOI GeoJSON is untracked).
BBOX: Final = (115.3, -33.2, 116.0, -31.6)
START: Final = date(2026, 8, 15)
END: Final = date(2026, 11, 3)
CLOUD_MAX: Final = 20.0
PAGE_LIMIT: Final = 100
REQUEST_TIMEOUT_SECONDS: Final = 90

CRON_TIME: Final = time(10, 17, 0, tzinfo=UTC)
RUN_DURATION_MARGIN: Final = timedelta(hours=2)
POPULATE_MIN_SHARE: Final = 0.5
H1_MIN_SHARE: Final = 0.90
WILSON_Z: Final = 1.96
LAG_DECIMALS: Final = 3

COLUMNS: Final = (
    "item_id",
    "tile",
    "acquired",
    "cloud_cover",
    "es_created",
    "wo_found",
    "wo_item_id",
    "wo_created",
    "wo_path_stamp",
    "t_proc",
    "lag_hours",
    "available_at_proc",
    "available_at_proc_plus2h",
)
LAG_QUANTILES: Final = (
    ("min", 0),
    ("p25", 25),
    ("median", 50),
    ("p75", 75),
    ("p90", 90),
    ("max", 100),
)
PATH_STAMP: Final = re.compile(r"\d{8}T\d{6}")

Row = dict[str, Any]
Post = Callable[[str, dict[str, Any]], dict[str, Any]]


def _parse_time(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_time(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def next_cron(created: datetime) -> datetime:
    """First 10:17:00 UTC at or after `created`."""
    same_day = datetime.combine(created.astimezone(UTC).date(), CRON_TIME)
    if same_day >= created:
        return same_day
    return same_day + timedelta(days=1)


def _path_stamp(item: Mapping[str, Any]) -> str:
    href = str(item.get("assets", {}).get("water", {}).get("href", ""))
    found = PATH_STAMP.search(href)
    return found.group(0) if found else ""


def _earliest_wo_by_key(
    dea_items: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Per (UTC date, region code), the item with the earliest `created`.

    Two items for one key are not expected. If DEA re-created one, the
    earliest index time is the first moment a WO item existed.
    """
    chosen: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in dea_items:
        properties = item["properties"]
        created = properties.get("created")
        if created is None:
            continue
        key = (
            _parse_time(properties["datetime"]).date().isoformat(),
            str(properties["odc:region_code"]),
        )
        current = chosen.get(key)
        if current is None or (_parse_time(created), item["id"]) < (
            _parse_time(current["properties"]["created"]),
            current["id"],
        ):
            chosen[key] = item
    return chosen


def build_rows(
    es_items: Iterable[Mapping[str, Any]],
    wo_items: Iterable[Mapping[str, Any]],
    *,
    start: date,
    end: date,
    cloud_max: float,
) -> list[Row]:
    """One row per Earth Search item in the sample, matched to a DEA WO item."""
    wo_by_key = _earliest_wo_by_key(wo_items)
    rows: list[Row] = []
    for item in es_items:
        properties = item["properties"]
        created = properties.get("created")
        cloud_cover = properties.get("eo:cloud_cover")
        if created is None or cloud_cover is None or cloud_cover > cloud_max:
            continue
        acquired = _parse_time(properties["datetime"]).date()
        if not start <= acquired <= end:
            continue
        tile = str(properties["grid:code"]).removeprefix("MGRS-")
        es_created = _parse_time(created)
        t_proc = next_cron(es_created)
        row: Row = {
            "item_id": str(item["id"]),
            "tile": tile,
            "acquired": acquired.isoformat(),
            "cloud_cover": float(cloud_cover),
            "es_created": _format_time(es_created),
            "wo_found": False,
            "wo_item_id": "",
            "wo_created": "",
            "wo_path_stamp": "",
            "t_proc": _format_time(t_proc),
            "lag_hours": None,
            "available_at_proc": False,
            "available_at_proc_plus2h": False,
        }
        match = wo_by_key.get((acquired.isoformat(), tile))
        if match is not None:
            wo_created = _parse_time(match["properties"]["created"])
            row.update(
                wo_found=True,
                wo_item_id=str(match["id"]),
                wo_created=_format_time(wo_created),
                wo_path_stamp=_path_stamp(match),
                lag_hours=round(
                    (wo_created - t_proc).total_seconds() / 3600, LAG_DECIMALS
                ),
                available_at_proc=wo_created <= t_proc,
                available_at_proc_plus2h=wo_created <= t_proc + RUN_DURATION_MARGIN,
            )
        rows.append(row)
    return sorted(rows, key=lambda row: (row["acquired"], row["item_id"]))


def wilson_interval(successes: int, total: int) -> tuple[float, float]:
    """Wilson 95 percent score interval for a share."""
    share = successes / total
    denominator = 1 + WILSON_Z**2 / total
    centre = share + WILSON_Z**2 / (2 * total)
    half_width = WILSON_Z * math.sqrt(
        share * (1 - share) / total + WILSON_Z**2 / (4 * total**2)
    )
    return (centre - half_width) / denominator, (centre + half_width) / denominator


def _nearest_rank(sorted_values: list[float], percent: int) -> float:
    rank = max(1, -(-percent * len(sorted_values) // 100))
    return sorted_values[rank - 1]


def summarise_rows(rows: list[Row]) -> dict[str, Any]:
    """Counts, shares, Wilson interval, lag quantiles and per-month counts."""
    if not rows:
        raise ValueError("no rows to summarise")
    total = len(rows)
    available = sum(1 for row in rows if row["available_at_proc"])
    available_plus2h = sum(1 for row in rows if row["available_at_proc_plus2h"])
    found = sum(1 for row in rows if row["wo_found"])
    wilson_low, wilson_high = wilson_interval(available, total)
    lags = sorted(row["lag_hours"] for row in rows if row["lag_hours"] is not None)
    lag_quantiles = {
        name: _nearest_rank(lags, percent) if lags else None
        for name, percent in LAG_QUANTILES
    }
    by_month: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "n_available": 0, "n_no_wo": 0}
    )
    for row in rows:
        counts = by_month[row["acquired"][:7]]
        counts["n"] += 1
        counts["n_available"] += int(row["available_at_proc"])
        counts["n_no_wo"] += int(not row["wo_found"])
    return {
        "n": total,
        "n_available": available,
        "share": available / total,
        "wilson_low": wilson_low,
        "wilson_high": wilson_high,
        "n_wo_found": found,
        "share_wo_found": found / total,
        "n_no_wo": total - found,
        "n_wo_later": found - available,
        "n_available_plus2h": available_plus2h,
        "share_plus2h": available_plus2h / total,
        "lag_hours": lag_quantiles,
        "by_month": dict(sorted(by_month.items())),
    }


def decide(summary: Mapping[str, Any]) -> str:
    """The pre-registered rule: populate when S is at least 0.50, else amend."""
    return "populate" if summary["share"] >= POPULATE_MIN_SHARE else "amend"


def _csv_value(column: str, value: Any) -> str:
    if column == "lag_hours":
        return "" if value is None else f"{value:.{LAG_DECIMALS}f}"
    return str(value)


def write_rows(rows: list[Row], path: Path) -> None:
    """Write the rows sorted by acquired date then item id."""
    ordered = sorted(rows, key=lambda row: (row["acquired"], row["item_id"]))
    with Path(path).open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(COLUMNS)
        for row in ordered:
            writer.writerow([_csv_value(column, row[column]) for column in COLUMNS])


def load_rows(path: Path) -> list[Row]:
    """Read a CSV written by `write_rows` back into what `build_rows` produced."""
    rows: list[Row] = []
    with Path(path).open(newline="") as handle:
        for raw in csv.DictReader(handle):
            row: Row = dict(raw)
            row["cloud_cover"] = float(raw["cloud_cover"])
            for column in (
                "wo_found",
                "available_at_proc",
                "available_at_proc_plus2h",
            ):
                row[column] = raw[column] == "True"
            row["lag_hours"] = float(raw["lag_hours"]) if raw["lag_hours"] else None
            rows.append(row)
    return rows


def fetch_all(post: Post, url: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    """Every feature of a STAC search, following `next` links.

    A next link with `merge: true` (DEA explorer sends `{"_o": N}`) holds only
    the changed keys and is merged into the previous body. Any other next link
    carries a full body (Earth Search). Features are de-duplicated by item id.
    """
    features: dict[str, dict[str, Any]] = {}
    current_url = url
    current_body = dict(body)
    while True:
        page = post(current_url, current_body)
        for feature in page.get("features", []):
            features.setdefault(str(feature["id"]), feature)
        next_link = next(
            (link for link in page.get("links", []) if link.get("rel") == "next"),
            None,
        )
        if next_link is None or not page.get("features"):
            return list(features.values())
        link_body = dict(next_link.get("body", {}))
        current_body = (
            {**current_body, **link_body} if next_link.get("merge") else link_body
        )
        current_url = str(next_link.get("href", current_url))


def _requests_post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    return payload


def _day_start(day: date) -> str:
    return f"{day.isoformat()}T00:00:00Z"


def _day_end(day: date) -> str:
    return f"{day.isoformat()}T23:59:59Z"


def search_bodies() -> tuple[dict[str, Any], dict[str, Any]]:
    """(Earth Search body, DEA body). DEA's window runs one day past the sample."""
    earth_search = {
        "collections": [EARTH_SEARCH_COLLECTION],
        "bbox": list(BBOX),
        "datetime": f"{_day_start(START)}/{_day_end(END)}",
        "limit": PAGE_LIMIT,
    }
    dea = {
        "collections": [DEA_COLLECTION],
        "bbox": list(BBOX),
        "datetime": f"{_day_start(START)}/{_day_end(END + timedelta(days=1))}",
        "limit": PAGE_LIMIT,
    }
    return earth_search, dea


def _fixed(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def render_report(
    rows: list[Row],
    summary: Mapping[str, Any],
    outcome: str,
    *,
    fetched: tuple[int, int],
    fetch_time: datetime,
) -> str:
    lag = summary["lag_hours"]
    lines = [
        "DEA WO availability at first processing (st-5f74)",
        "",
        "Parameters",
        f"  Earth Search: {EARTH_SEARCH_URL}, collection {EARTH_SEARCH_COLLECTION}",
        f"  DEA: {DEA_URL}, collection {DEA_COLLECTION}",
        f"  bbox: {list(BBOX)}",
        f"  acquired (UTC date): {START.isoformat()} to {END.isoformat()} inclusive",
        f"  DEA datetime window: {_day_start(START)}/"
        f"{_day_end(END + timedelta(days=1))}",
        f"  eo:cloud_cover <= {CLOUD_MAX}, properties.created not null",
        f"  scheduled run: {CRON_TIME.strftime('%H:%M:%S')} UTC daily",
        f"  fetched: {fetched[0]} Earth Search items, {fetched[1]} DEA items",
        f"  measured at: {_format_time(fetch_time)}",
        "",
        "Result",
        f"  N (scene-tiles): {summary['n']}",
        f"  tiles: {', '.join(sorted({row['tile'] for row in rows}))}",
        f"Share available at first processing: {summary['n_available']} of "
        f"{summary['n']}",
        f"  S: {_fixed(summary['share'], 4)}",
        f"  Wilson 95 percent interval: {_fixed(summary['wilson_low'], 4)} to "
        f"{_fixed(summary['wilson_high'], 4)}",
        f"  with a WO item at measurement time: {summary['n_wo_found']} of "
        f"{summary['n']} ({_fixed(summary['share_wo_found'], 4)})",
        f"  no WO item at all: {summary['n_no_wo']}",
        f"  WO item arrived after first processing: {summary['n_wo_later']}",
        f"  S2 (T_proc plus 2 hours): {summary['n_available_plus2h']} of "
        f"{summary['n']} ({_fixed(summary['share_plus2h'], 4)})",
        f"  H1 (S >= {H1_MIN_SHARE}): "
        + ("holds" if summary["share"] >= H1_MIN_SHARE else "does not hold"),
        "",
        "Lag, A_wo minus T_proc in hours (negative means WO was ready before the run)",
        "  nearest rank over scene-tiles with a WO item",
        "  " + ", ".join(f"{name} {_fixed(lag[name])}" for name, _ in LAG_QUANTILES),
        "",
        "By acquisition month",
        f"  {'month':<8}{'n':>5}{'available':>11}{'no_wo':>7}",
    ]
    for month, counts in summary["by_month"].items():
        lines.append(
            f"  {month:<8}{counts['n']:>5}{counts['n_available']:>11}"
            f"{counts['n_no_wo']:>7}"
        )
    lines += ["", f"Chosen outcome: {outcome}", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure DEA WO availability.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    earth_search_body, dea_body = search_bodies()
    earth_search_items = fetch_all(_requests_post, EARTH_SEARCH_URL, earth_search_body)
    dea_items = fetch_all(_requests_post, DEA_URL, dea_body)
    fetch_time = datetime.now(UTC)
    rows = build_rows(
        earth_search_items, dea_items, start=START, end=END, cloud_max=CLOUD_MAX
    )
    write_rows(rows, args.out)
    # Summarise the file, so the report matches what is committed.
    stored = load_rows(args.out)
    summary = summarise_rows(stored)
    report = render_report(
        stored,
        summary,
        decide(summary),
        fetched=(len(earth_search_items), len(dea_items)),
        fetch_time=fetch_time,
    )
    args.report.write_text(report)
    print(report)


if __name__ == "__main__":
    main()
