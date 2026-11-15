"""The one source of the Copernicus Sentinel data notice.

Term T2 of docs/research/2026-11-14-public-release-licences.md: when modified
Sentinel data is distributed, recipients are informed with "Contains modified
Copernicus Sentinel data [Year]", per the legal notice at
https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice.
Every published file holds values computed from, or metadata reformatted from,
Earth Search sentinel-2-c1-l2a items, so every file uses the modified form.

The legal notice and Delegated Regulation (EU) No 1159/2013 do not define
[Year]. Filling it with the UTC years of the Sentinel-2 acquisitions the
file's content comes from is this project's reading and the common
convention, not an official rule. Each kind states its rule in `years_from`.
A file with no such acquisition carries no notice, and the literal
placeholder [Year] is never written.

`copernicus_notice` builds the block for each kind of published file, and
`copernicus_notice_footer` wraps it as one Parquet footer entry. Values depend
only on the years, so rewriting a file gives the same bytes.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Collection, Iterable
from itertools import groupby
from typing import Any, Final, Literal

import pandas as pd

NoticeKind = Literal["observation", "change", "verification", "collection", "ledger"]

COPERNICUS_NOTICE_KEY: Final = "copernicus_notice"
COPERNICUS_NOTICE_ADDED_KEY: Final = "copernicus_notice_added_after_the_fact"

NOTICE_PREFIX: Final = "Contains modified Copernicus Sentinel data"
LEGAL_NOTICE_TITLE: Final = (
    "Legal notice on the use of Copernicus Sentinel Data and Service Information"
)
LEGAL_NOTICE_URI: Final = (
    "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice"
)

EARTH_SEARCH_C1: Final = (
    "https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a"
)
PLANETARY_COMPUTER_L2A: Final = (
    "https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a"
)
CDSE_L2A: Final = "https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a"

_EARTH_SEARCH_ONLY: Final = (EARTH_SEARCH_C1,)
_THREE_CATALOGUES: Final = (EARTH_SEARCH_C1, PLANETARY_COMPUTER_L2A, CDSE_L2A)

_SOURCES: Final[dict[str, tuple[str, ...]]] = {
    "observation": _EARTH_SEARCH_ONLY,
    "change": _EARTH_SEARCH_ONLY,
    "ledger": _EARTH_SEARCH_ONLY,
    "verification": _THREE_CATALOGUES,
    "collection": _THREE_CATALOGUES,
}

_YEARS_FROM: Final[dict[str, str]] = {
    "observation": "UTC year of the acquisition time (datetime) of the file's rows",
    "change": (
        "UTC years of the acquisition time of the file's rows and of the "
        "observation rows its baselines are built from: same polygon and "
        "calendar month, strictly earlier UTC dates"
    ),
    "ledger": (
        "UTC years of the datetime column of the file's rows; rows without one "
        "(rejected items) add none"
    ),
    "collection": "UTC years of the acquisition time of the collection's items",
    "verification": (
        "UTC years of the acquisition time of the run's succeeded scenes and of "
        "every stored scene acquired up to the newest of them, the history the "
        "waterbody checks read"
    ),
}


def utc_years(stamps: Iterable[object]) -> tuple[int, ...]:
    """Distinct UTC years of the non-null stamps, ascending; naive reads as UTC."""
    years: set[int] = set()
    for stamp in stamps:
        if pd.isna(stamp):
            continue
        moment = pd.Timestamp(stamp)
        if moment.tzinfo is None:
            moment = moment.tz_localize("UTC")
        else:
            moment = moment.tz_convert("UTC")
        years.add(int(moment.year))
    return tuple(sorted(years))


def _distinct(years: Collection[int]) -> list[int]:
    if not years:
        raise ValueError("no acquisition year")
    return sorted({int(year) for year in years})


def notice_text(years: Collection[int]) -> str:
    """The notice with consecutive years written as first-last runs."""
    ordered = _distinct(years)
    runs: list[str] = []
    # Years minus their index are constant within a consecutive run.
    for _, group in groupby(enumerate(ordered), key=lambda pair: pair[1] - pair[0]):
        run = [year for _, year in group]
        runs.append(str(run[0]) if len(run) == 1 else f"{run[0]}-{run[-1]}")
    return f"{NOTICE_PREFIX} {', '.join(runs)}"


def copernicus_notice(kind: NoticeKind, years: Collection[int]) -> dict[str, Any]:
    """A new notice block for one kind of published file."""
    if kind not in _SOURCES:
        raise ValueError(f"unknown notice kind {kind!r}")
    ordered = _distinct(years)
    return {
        "notice": notice_text(ordered),
        "years": ordered,
        "years_from": _YEARS_FROM[kind],
        "modified": True,
        "sources": list(copy.deepcopy(_SOURCES[kind])),
        "legal_notice": LEGAL_NOTICE_TITLE,
        "legal_notice_uri": LEGAL_NOTICE_URI,
    }


def copernicus_notice_footer(
    kind: NoticeKind, years: Collection[int]
) -> dict[str, str]:
    """One Parquet footer entry, or nothing when there is no acquisition year."""
    if not years:
        return {}
    return {
        COPERNICUS_NOTICE_KEY: json.dumps(
            copernicus_notice(kind, years), sort_keys=True
        )
    }
