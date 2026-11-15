"""The Copernicus Sentinel data notice is one constant source (term T2)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Final, get_args

import numpy as np
import pandas as pd
import pytest

from wetland_change.sentinel_notice import (
    CDSE_L2A,
    COPERNICUS_NOTICE_ADDED_KEY,
    COPERNICUS_NOTICE_KEY,
    EARTH_SEARCH_C1,
    LEGAL_NOTICE_TITLE,
    LEGAL_NOTICE_URI,
    NOTICE_PREFIX,
    PLANETARY_COMPUTER_L2A,
    NoticeKind,
    copernicus_notice,
    copernicus_notice_footer,
    notice_text,
    utc_years,
)

KINDS: Final = get_args(NoticeKind)
PREFIX: Final = "Contains modified Copernicus Sentinel data"

SOURCES: Final = {
    "observation": [EARTH_SEARCH_C1],
    "change": [EARTH_SEARCH_C1],
    "ledger": [EARTH_SEARCH_C1],
    "verification": [EARTH_SEARCH_C1, PLANETARY_COMPUTER_L2A, CDSE_L2A],
    "collection": [EARTH_SEARCH_C1, PLANETARY_COMPUTER_L2A, CDSE_L2A],
}


def test_constants() -> None:
    assert COPERNICUS_NOTICE_KEY == "copernicus_notice"
    assert COPERNICUS_NOTICE_ADDED_KEY == "copernicus_notice_added_after_the_fact"
    assert NOTICE_PREFIX == PREFIX
    assert LEGAL_NOTICE_TITLE == (
        "Legal notice on the use of Copernicus Sentinel Data and Service Information"
    )
    assert LEGAL_NOTICE_URI == (
        "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice"
    )
    assert EARTH_SEARCH_C1 == (
        "https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a"
    )
    assert PLANETARY_COMPUTER_L2A == (
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a"
    )
    assert (
        CDSE_L2A == "https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a"
    )


def test_kinds() -> None:
    assert set(KINDS) == set(SOURCES)


@pytest.mark.parametrize(
    ("years", "expected"),
    [
        ([2026], f"{PREFIX} 2026"),
        ([2026, 2025, 2026], f"{PREFIX} 2025-2026"),
        ([2024, 2020, 2021, 2022], f"{PREFIX} 2020-2022, 2024"),
        ([2019, 2021], f"{PREFIX} 2019, 2021"),
    ],
)
def test_notice_text(years: list[int], expected: str) -> None:
    assert notice_text(years) == expected


def test_notice_text_empty_raises() -> None:
    with pytest.raises(ValueError, match="no acquisition year"):
        notice_text([])


def test_utc_years() -> None:
    stamps = [
        datetime(2026, 1, 1, 6, 0, tzinfo=timezone(timedelta(hours=8))),
        None,
        pd.NaT,
        pd.Timestamp("2026-10-27T02:26:46Z"),
        datetime(2024, 5, 1),
        np.datetime64("2024-12-31T23:00"),
    ]
    assert utc_years(stamps) == (2024, 2025, 2026)


def test_utc_years_empty_and_null_only() -> None:
    assert utc_years([]) == ()
    assert utc_years([None, pd.NaT]) == ()


@pytest.mark.parametrize("kind", KINDS)
def test_block_fields(kind: NoticeKind) -> None:
    block = copernicus_notice(kind, [2026, 2025])
    assert set(block) == {
        "notice",
        "years",
        "years_from",
        "modified",
        "sources",
        "legal_notice",
        "legal_notice_uri",
    }
    assert block["notice"] == f"{PREFIX} 2025-2026"
    assert block["years"] == [2025, 2026]
    assert block["modified"] is True
    assert block["sources"] == SOURCES[kind]
    assert block["legal_notice"] == LEGAL_NOTICE_TITLE
    assert block["legal_notice_uri"] == (
        "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice"
    )
    assert isinstance(block["years_from"], str)
    assert block["years_from"]


def test_years_from_distinct_per_kind() -> None:
    sentences = {copernicus_notice(k, [2026])["years_from"] for k in KINDS}
    assert len(sentences) == len(KINDS)


def test_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="kind"):
        copernicus_notice("nope", [2026])  # type: ignore[arg-type]


def test_empty_years_raises() -> None:
    with pytest.raises(ValueError, match="no acquisition year"):
        copernicus_notice("observation", [])


def test_blocks_are_independent() -> None:
    first = copernicus_notice("verification", [2026])
    first["years"].append(1999)
    first["sources"].append("x")
    first["notice"] = "changed"
    second = copernicus_notice("verification", [2026])
    assert second["years"] == [2026]
    assert second["sources"] == SOURCES["verification"]
    assert second["notice"] == f"{PREFIX} 2026"


@pytest.mark.parametrize("kind", KINDS)
def test_footer(kind: NoticeKind) -> None:
    assert copernicus_notice_footer(kind, []) == {}
    footer = copernicus_notice_footer(kind, [2026, 2024])
    assert list(footer) == [COPERNICUS_NOTICE_KEY]
    block = copernicus_notice(kind, [2024, 2026])
    assert footer[COPERNICUS_NOTICE_KEY] == json.dumps(block, sort_keys=True)
    assert json.loads(footer[COPERNICUS_NOTICE_KEY]) == block
