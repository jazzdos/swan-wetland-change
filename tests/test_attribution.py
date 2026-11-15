"""The DEA attribution block is one constant source (term T1, CC BY 4.0 s3(a))."""

from __future__ import annotations

import json
from typing import Any, Final, Literal, get_args

import pytest

from wetland_change.attribution import (
    CC_BY_4_LEGALCODE_URI,
    CC_BY_4_URI,
    DEA_ATTRIBUTION_ADDED_KEY,
    DEA_ATTRIBUTION_KEY,
    DEA_WATERBODIES_CITATION,
    DEA_WATERBODIES_PAPER_CITATION,
    AttributionKind,
    dea_attribution,
    dea_attribution_footer,
)

KINDS: Final = get_args(AttributionKind)
COPYRIGHT: Final = "© Commonwealth of Australia (Geoscience Australia)"

POLYGONS: Final = "DEA Waterbodies v3.0 polygons"
TIMESERIES: Final = "DEA Waterbodies v3.0 per-lake time series"
WO: Final = "DEA Sentinel-2 Water Observations (ga_s2_wo_provisional_3)"
NBART: Final = "DEA Sentinel-2 ARD NBART (ga_s2am_ard_3, ga_s2bm_ard_3, ga_s2cm_ard_3)"

EXPECTED_NAMES: Final[dict[str, list[str]]] = {
    "observation": [POLYGONS, WO],
    "change": [POLYGONS],
    "verification": [WO, NBART, TIMESERIES, POLYGONS],
    "collection": [POLYGONS, TIMESERIES, WO, NBART],
}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            text
            for key, item in value.items()
            for text in _strings(key) + _strings(item)
        ]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def test_key_constants() -> None:
    assert DEA_ATTRIBUTION_KEY == "dea_attribution"
    assert DEA_ATTRIBUTION_ADDED_KEY == "dea_attribution_added_after_the_fact"


@pytest.mark.parametrize("kind", KINDS)
def test_block_carries_the_section_3a_fields(kind: AttributionKind) -> None:
    block = dea_attribution(kind)
    assert list(block) == [
        "notice",
        "creator",
        "copyright",
        "licence",
        "licence_uri",
        "licence_text_uri",
        "disclaimer",
        "modified",
        "datasets",
    ]
    assert block["copyright"] == COPYRIGHT
    assert block["licence_uri"] == CC_BY_4_URI
    assert block["licence_text_uri"] == CC_BY_4_LEGALCODE_URI
    assert "section 5" in block["disclaimer"]
    assert block["modified"] is True
    assert COPYRIGHT in block["notice"]
    assert "CC BY 4.0" in block["notice"]
    assert CC_BY_4_URI in block["notice"]
    assert block["datasets"]
    for dataset in block["datasets"]:
        assert dataset["name"]
        assert dataset["content"]
        assert dataset["modification"]
        assert isinstance(dataset["sources"], list)
        assert dataset["sources"]
        for source in dataset["sources"]:
            assert isinstance(source, str)
            assert source.startswith("https://")


@pytest.mark.parametrize("kind", KINDS)
def test_dataset_names_and_order_per_kind(kind: AttributionKind) -> None:
    names = [dataset["name"] for dataset in dea_attribution(kind)["datasets"]]
    assert names == EXPECTED_NAMES[kind]


@pytest.mark.parametrize("kind", KINDS)
def test_citation_is_on_waterbodies_entries_only(kind: AttributionKind) -> None:
    assert "https://dx.doi.org/10.26186/148920" in DEA_WATERBODIES_CITATION
    for dataset in dea_attribution(kind)["datasets"]:
        if dataset["name"] in (POLYGONS, TIMESERIES):
            assert dataset["citation"] == DEA_WATERBODIES_CITATION
        else:
            assert "citation" not in dataset


def test_paper_citation_text_follows_the_product_page() -> None:
    assert DEA_WATERBODIES_PAPER_CITATION.startswith(
        "Krause, C.E., Newey, V., Alger, M.J. and Lymburner, L., 2021."
    )
    assert "Australia\u2019s Open Waterbodies using Landsat" in (
        DEA_WATERBODIES_PAPER_CITATION
    )
    assert "Remote Sensing, 13, 1437." in DEA_WATERBODIES_PAPER_CITATION
    assert DEA_WATERBODIES_PAPER_CITATION.endswith("https://doi.org/10.3390/rs13081437")


@pytest.mark.parametrize("kind", KINDS)
def test_paper_citation_is_on_waterbodies_entries_only(kind: AttributionKind) -> None:
    for dataset in dea_attribution(kind)["datasets"]:
        if dataset["name"] in (POLYGONS, TIMESERIES):
            assert dataset["paper_citation"] == DEA_WATERBODIES_PAPER_CITATION
        else:
            assert "paper_citation" not in dataset


@pytest.mark.parametrize("kind", KINDS)
def test_paper_citation_follows_citation_in_key_order(kind: AttributionKind) -> None:
    for dataset in dea_attribution(kind)["datasets"]:
        if dataset["name"] in (POLYGONS, TIMESERIES):
            keys = list(dataset)
            assert keys[keys.index("citation") + 1] == "paper_citation"


@pytest.mark.parametrize("kind", KINDS)
def test_mutating_a_result_does_not_change_the_next_call(kind: AttributionKind) -> None:
    first = dea_attribution(kind)
    first["notice"] = "changed"
    first["datasets"].append({"name": "extra"})
    first["datasets"][0]["sources"].append("https://example.invalid/")
    first["datasets"][0]["name"] = "renamed"
    second = dea_attribution(kind)
    assert second["notice"] != "changed"
    assert [dataset["name"] for dataset in second["datasets"]] == EXPECTED_NAMES[kind]
    assert "https://example.invalid/" not in second["datasets"][0]["sources"]


@pytest.mark.parametrize("kind", ["observation", "change"])
def test_footer_is_one_stable_json_value(
    kind: Literal["observation", "change"],
) -> None:
    footer = dea_attribution_footer(kind)
    assert list(footer) == ["dea_attribution"]
    assert json.loads(footer[DEA_ATTRIBUTION_KEY]) == dea_attribution(kind)
    assert footer == dea_attribution_footer(kind)


def test_unknown_kind_raises_value_error() -> None:
    with pytest.raises(ValueError, match="other"):
        dea_attribution("other")  # type: ignore[arg-type]  # the test passes a bad kind on purpose


@pytest.mark.parametrize("kind", KINDS)
def test_no_string_in_a_block_contains_an_em_dash(kind: AttributionKind) -> None:
    for text in _strings(dea_attribution(kind)):
        assert "\u2014" not in text
