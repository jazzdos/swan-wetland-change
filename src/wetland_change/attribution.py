"""The one source of the Digital Earth Australia (DEA) attribution.

Term T1 of docs/research/2026-11-14-public-release-licences.md found that
published files carrying Geoscience Australia DEA data (CC BY 4.0) have no
attribution. CC BY 4.0 section 3(a) requires the creator identification and
copyright notice the licensor supplies, a notice of the licence with its URI,
a notice referring to the disclaimer of warranties, a link to the material and
an indication of modification. `dea_attribution` builds that block for each
kind of published file, and `dea_attribution_footer` wraps it as one Parquet
footer entry.

The two Waterbodies entries carry the data citation and the paper citation
that the product page asks for (its FAQs tab and the Overview tab's "Cite this
product" rows, fetched 2026-11-15).

Every value is a constant with no dates or run ids, so rewriting a file
produces the same bytes.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Final, Literal

AttributionKind = Literal["observation", "change", "verification", "collection"]

DEA_ATTRIBUTION_KEY: Final = "dea_attribution"
DEA_ATTRIBUTION_ADDED_KEY: Final = "dea_attribution_added_after_the_fact"

CC_BY_4_NAME: Final = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
CC_BY_4_URI: Final = "https://creativecommons.org/licenses/by/4.0/"
CC_BY_4_LEGALCODE_URI: Final = (
    "https://creativecommons.org/licenses/by/4.0/legalcode.en"
)

DEA_CREATOR: Final = "Geoscience Australia (Digital Earth Australia)"
DEA_COPYRIGHT: Final = "© Commonwealth of Australia (Geoscience Australia)"

DEA_WATERBODIES_PAGE: Final = (
    "https://knowledge.dea.ga.gov.au/data/product/dea-waterbodies-landsat/"
)
DEA_WATERBODIES_CITATION: Final = (
    "Dunn, B., Krause, C., Newey, V., Lymburner, L., Alger, M.J., Adams, C., "
    "Yuan, F., Ma, S., Barzinpour, A., Ayers, D., McKenna, C., Schenk, L. 2024. "
    "Digital Earth Australia Waterbodies v3.0. Geoscience Australia, Canberra. "
    "https://dx.doi.org/10.26186/148920"
)

DEA_WATERBODIES_PAPER_CITATION: Final = (
    "Krause, C.E., Newey, V., Alger, M.J. and Lymburner, L., 2021. Mapping and "
    "Monitoring the Multi-Decadal Dynamics of Australia\u2019s Open Waterbodies "
    "using Landsat. Remote Sensing, 13, 1437. https://doi.org/10.3390/rs13081437"
)

_DEA_EXPLORER_COLLECTIONS: Final = "https://explorer.dea.ga.gov.au/stac/collections"

_WATERBODIES_POLYGONS: Final[dict[str, Any]] = {
    "name": "DEA Waterbodies v3.0 polygons",
    "sources": [DEA_WATERBODIES_PAGE],
    "content": "geometry and uid of the DEA Waterbodies polygons, polygon_id dea-<uid>",
    "modification": (
        "Subset to the Swan Coastal Plain by a bounding-box query of the DEA WFS; "
        "only the geometry and uid are kept; the uid is kept in polygon_id as "
        "dea-<uid>; the geometry is stored in EPSG:4326 and reprojected to "
        "EPSG:32750 to compute the pixel statistics."
    ),
    "citation": DEA_WATERBODIES_CITATION,
    "paper_citation": DEA_WATERBODIES_PAPER_CITATION,
}

_WATERBODIES_TIMESERIES: Final[dict[str, Any]] = {
    "name": "DEA Waterbodies v3.0 per-lake time series",
    "sources": [DEA_WATERBODIES_PAGE],
    "content": "wet percentage (pc_wet) of the DEA passes paired with pipeline passes",
    "modification": (
        "Read per lake, converted from percent to a fraction, paired with "
        "pipeline passes by UTC date, and compared as per-pass differences in "
        "percentage points (water_vs_dea_waterbodies) and a per-lake Spearman "
        "correlation (water_spearman_vs_dea_waterbodies)."
    ),
    "citation": DEA_WATERBODIES_CITATION,
    "paper_citation": DEA_WATERBODIES_PAPER_CITATION,
}

_WATER_OBSERVATIONS: Final[dict[str, Any]] = {
    "name": "DEA Sentinel-2 Water Observations (ga_s2_wo_provisional_3)",
    "sources": [f"{_DEA_EXPLORER_COLLECTIONS}/ga_s2_wo_provisional_3"],
    "content": (
        "agreement and wet shares computed from the water flags of the same "
        "Sentinel-2 pass"
    ),
    "modification": (
        "Not redistributed as pixels; agreement with the pipeline's water call "
        "and the wet shares are computed over the pixels both products call "
        "clear (dea_wo_agreement in observation files, the water_vs_dea_s2_wo "
        "checks in verification reports)."
    ),
}

_NBART: Final[dict[str, Any]] = {
    "name": "DEA Sentinel-2 ARD NBART (ga_s2am_ard_3, ga_s2bm_ard_3, ga_s2cm_ard_3)",
    "sources": [
        f"{_DEA_EXPLORER_COLLECTIONS}/ga_s2am_ard_3",
        f"{_DEA_EXPLORER_COLLECTIONS}/ga_s2bm_ard_3",
        f"{_DEA_EXPLORER_COLLECTIONS}/ga_s2cm_ard_3",
    ],
    "content": "NDVI medians computed from nbart_red and nbart_nir_1 of the same pass",
    "modification": (
        "Not redistributed as pixels; an NDVI median is computed per polygon "
        "over the pipeline's clear pixels and compared with the pipeline's NDVI "
        "median (the ndvi_vs_dea_nbart checks in verification reports)."
    ),
}

_DATASETS_BY_KIND: Final[dict[str, tuple[dict[str, Any], ...]]] = {
    "observation": (_WATERBODIES_POLYGONS, _WATER_OBSERVATIONS),
    "change": (_WATERBODIES_POLYGONS,),
    "verification": (
        _WATER_OBSERVATIONS,
        _NBART,
        _WATERBODIES_TIMESERIES,
        _WATERBODIES_POLYGONS,
    ),
    "collection": (
        _WATERBODIES_POLYGONS,
        _WATERBODIES_TIMESERIES,
        _WATER_OBSERVATIONS,
        _NBART,
    ),
}


def dea_attribution(kind: AttributionKind) -> dict[str, Any]:
    """Return a new CC BY 4.0 attribution block for a kind of published file.

    Args:
        kind: The published file kind, which selects the DEA datasets listed.

    Raises:
        ValueError: If the kind is not one of the four known kinds.
    """
    if kind not in _DATASETS_BY_KIND:
        raise ValueError(f"unknown attribution kind {kind!r}")
    return {
        "notice": (
            f"Contains data from {DEA_CREATOR}, {DEA_COPYRIGHT}, licensed under "
            f"CC BY 4.0 ({CC_BY_4_URI}). The data were modified as each entry in "
            "datasets states."
        ),
        "creator": DEA_CREATOR,
        "copyright": DEA_COPYRIGHT,
        "licence": CC_BY_4_NAME,
        "licence_uri": CC_BY_4_URI,
        "licence_text_uri": CC_BY_4_LEGALCODE_URI,
        "disclaimer": (
            "The licensor offers the material as-is and as-available and makes no "
            "representations or warranties of any kind; see section 5 of the "
            "licence."
        ),
        "modified": True,
        "datasets": [copy.deepcopy(dataset) for dataset in _DATASETS_BY_KIND[kind]],
    }


def dea_attribution_footer(kind: Literal["observation", "change"]) -> dict[str, str]:
    """Return the attribution as one Parquet footer entry with stable JSON text."""
    return {DEA_ATTRIBUTION_KEY: json.dumps(dea_attribution(kind), sort_keys=True)}
