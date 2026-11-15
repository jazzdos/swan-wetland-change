"""The DBCA-010 attribution block is one constant source (CC BY-NC 4.0 s3(a)(1))."""

from __future__ import annotations

import json
from typing import Final, cast, get_args

import pytest

from wetland_change.attribution import dea_attribution
from wetland_change.dbca_attribution import (
    CC_BY_NC_4_LEGALCODE_URI,
    CC_BY_NC_4_SPDX,
    CC_BY_NC_4_URI,
    DBCA_ATTRIBUTION_ADDED_KEY,
    DBCA_ATTRIBUTION_KEY,
    DBCA_ATTRIBUTION_TEXT,
    DBCA_CREATOR,
    DBCA_DATASET_URI,
    DBCA_SERVICE_URI,
    DbcaKind,
    dbca_attribution,
    dbca_attribution_footer,
)

KINDS: Final = get_args(DbcaKind)

FIELD_ORDER: Final = [
    "notice",
    "creator",
    "copyright",
    "dataset",
    "dataset_uri",
    "sources",
    "licence",
    "licence_uri",
    "licence_text_uri",
    "licence_basis",
    "file_licence",
    "disclaimer",
    "modified",
    "content",
    "modification",
]

EXPECTED_TEXT: Final = (
    "Contains DBCA-010 Ramsar Sites data "
    "(https://catalogue.data.wa.gov.au/dataset/ramsar-sites) from the "
    "Department of Biodiversity, Conservation and Attractions (DBCA), Western "
    "Australia, licensed under CC BY-NC 4.0 "
    "(https://creativecommons.org/licenses/by-nc/4.0/). Modified: selected by "
    "site, reprojected to EPSG:4326 and used as zonal boundaries."
)


def test_constants_have_exact_values() -> None:
    assert DBCA_ATTRIBUTION_KEY == "dbca_attribution"
    assert DBCA_ATTRIBUTION_ADDED_KEY == "dbca_attribution_added_after_the_fact"
    assert CC_BY_NC_4_URI == "https://creativecommons.org/licenses/by-nc/4.0/"
    assert (
        CC_BY_NC_4_LEGALCODE_URI
        == "https://creativecommons.org/licenses/by-nc/4.0/legalcode.en"
    )
    assert CC_BY_NC_4_SPDX == "CC-BY-NC-4.0"


def test_kinds_are_the_three_published_file_kinds() -> None:
    assert set(KINDS) == {"observation", "change", "collection"}


@pytest.mark.parametrize("kind", KINDS)
def test_dbca_attribution_fields_are_in_the_fixed_order(kind: DbcaKind) -> None:
    assert list(dbca_attribution(kind)) == FIELD_ORDER


@pytest.mark.parametrize("kind", KINDS)
def test_dbca_attribution_carries_the_section_3a1_elements(kind: DbcaKind) -> None:
    block = dbca_attribution(kind)
    assert block["creator"] == DBCA_CREATOR
    assert (
        "Department of Biodiversity, Conservation and Attractions" in block["creator"]
    )
    assert "No copyright notice is supplied" in block["copyright"]
    assert block["licence_uri"] == "https://creativecommons.org/licenses/by-nc/4.0/"
    assert block["licence_text_uri"].endswith("legalcode.en")
    assert (
        block["dataset_uri"] == "https://catalogue.data.wa.gov.au/dataset/ramsar-sites"
    )
    assert block["sources"] == [DBCA_DATASET_URI, DBCA_SERVICE_URI]
    assert block["disclaimer"] == dea_attribution("observation")["disclaimer"]
    assert block["modified"] is True
    assert "EPSG:4326" in block["modification"]
    assert "EPSG:32750" in block["modification"]


@pytest.mark.parametrize("kind", KINDS)
def test_dbca_attribution_notice_is_the_exact_text(kind: DbcaKind) -> None:
    assert DBCA_ATTRIBUTION_TEXT == EXPECTED_TEXT
    assert dbca_attribution(kind)["notice"] == EXPECTED_TEXT


def test_dbca_attribution_content_names_what_each_kind_holds() -> None:
    observation = dbca_attribution("observation")["content"]
    assert "ram_ramsarname" in observation
    assert "polygon_id" in observation
    change = dbca_attribution("change")["content"]
    assert "polygon_id" in change
    assert "ram_ramsarname" not in change
    assert "assets" in dbca_attribution("collection")["content"]


@pytest.mark.parametrize("kind", KINDS)
def test_dbca_attribution_file_licence_states_non_commercial_use(
    kind: DbcaKind,
) -> None:
    text = dbca_attribution(kind)["file_licence"]
    assert "CC BY-NC 4.0" in text
    assert CC_BY_NC_4_URI in text
    assert "non-commercial" in text


def test_dbca_attribution_returns_a_fresh_block_each_call() -> None:
    first = dbca_attribution("observation")
    first["sources"].append("https://example.invalid/")
    first["notice"] = "changed"
    second = dbca_attribution("observation")
    assert second["sources"] == [DBCA_DATASET_URI, DBCA_SERVICE_URI]
    assert second["notice"] == EXPECTED_TEXT


@pytest.mark.parametrize("kind", KINDS)
def test_dbca_attribution_footer_is_one_stable_json_entry(kind: DbcaKind) -> None:
    footer = dbca_attribution_footer(kind)
    block = dbca_attribution(kind)
    assert list(footer) == [DBCA_ATTRIBUTION_KEY]
    assert json.loads(footer[DBCA_ATTRIBUTION_KEY]) == block
    assert footer[DBCA_ATTRIBUTION_KEY] == json.dumps(block, sort_keys=True)


def test_dbca_attribution_rejects_an_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown"):
        dbca_attribution(cast(DbcaKind, "verification"))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "forbidden", [chr(0x2014), "ShareAlike", "SA 4.0", "SA-4.0"], ids=repr
)
def test_dbca_attribution_has_no_em_dash_or_sharealike_wording(
    kind: DbcaKind, forbidden: str
) -> None:
    text = json.dumps(dbca_attribution(kind), ensure_ascii=False)
    assert forbidden not in text
