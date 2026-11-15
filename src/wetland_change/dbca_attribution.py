"""The one source of the DBCA-010 Ramsar Sites attribution and licence notice.

Term T3 of docs/research/2026-11-14-public-release-licences.md covers the
published files that carry DBCA-010 Ramsar Sites material, which is treated as
CC BY-NC 4.0. Section 3(a)(1) of that licence asks for the creator and any
copyright notice the licensor supplies, a notice of the licence with its URI, a
notice referring to the disclaimer of warranties, a link to the material and an
indication of modification. `dbca_attribution` builds that block for each kind
of published file, and `dbca_attribution_footer` wraps it as one Parquet footer
entry.

The licence is the custodian's catalogue entry as recorded in data/SOURCES.md.
The observation and change files and the STAC collection carry the block, and
each STAC item carries the text. The verification JSON, ledger, run manifests,
STAC catalog and write index hold no DBCA-010 material (the verification JSON
holds polygon ids only) and carry none.

Every value is a constant with no dates or run ids, so rewriting a file
produces the same bytes.
"""

from __future__ import annotations

import json
from typing import Any, Final, Literal

DbcaKind = Literal["observation", "change", "collection"]

DBCA_ATTRIBUTION_KEY: Final = "dbca_attribution"
DBCA_ATTRIBUTION_ADDED_KEY: Final = "dbca_attribution_added_after_the_fact"

CC_BY_NC_4_NAME: Final = (
    "Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)"
)
CC_BY_NC_4_SPDX: Final = "CC-BY-NC-4.0"
CC_BY_NC_4_URI: Final = "https://creativecommons.org/licenses/by-nc/4.0/"
CC_BY_NC_4_LEGALCODE_URI: Final = (
    "https://creativecommons.org/licenses/by-nc/4.0/legalcode.en"
)

DBCA_CREATOR: Final = (
    "Department of Biodiversity, Conservation and Attractions (DBCA), Western Australia"
)
DBCA_COPYRIGHT: Final = (
    "No copyright notice is supplied with the dataset: the DBCA-010 catalogue "
    "entry has an empty citation field (fetched 2026-11-14)."
)
DBCA_DATASET: Final = "DBCA-010 Ramsar Sites"
DBCA_DATASET_URI: Final = "https://catalogue.data.wa.gov.au/dataset/ramsar-sites"
DBCA_SERVICE_URI: Final = (
    "https://public-services.slip.wa.gov.au/public/rest/services/"
    "SLIP_Public_Services/Environment/MapServer/9"
)

DBCA_ATTRIBUTION_TEXT: Final = (
    f"Contains {DBCA_DATASET} data ({DBCA_DATASET_URI}) from the {DBCA_CREATOR}, "
    f"licensed under CC BY-NC 4.0 ({CC_BY_NC_4_URI}). Modified: selected by "
    "site, reprojected to EPSG:4326 and used as zonal boundaries."
)
DBCA_LICENCE_BASIS: Final = (
    "CC BY-NC 4.0 is the licence on the custodian's catalogue entry "
    "(catalogue.data.wa.gov.au, fetched 2026-11-14), adopted 2026-11-15 and not "
    "confirmed in writing by DBCA; see "
    "docs/research/2026-11-14-public-release-licences.md."
)
DBCA_DISCLAIMER: Final = (
    "The licensor offers the material as-is and as-available and makes no "
    "representations or warranties of any kind; see section 5 of the licence."
)
DBCA_MODIFICATION: Final = (
    "Fetched from the SLIP service reprojected from GDA2020 to EPSG:4326 "
    "(outSR=4326); sites kept whose ram_ramsarname starts with a configured "
    "prefix; only the geometry, ram_ramsarname and objectid kept; the geometry "
    "is stored in EPSG:4326 and reprojected to EPSG:32750 as the zonal boundary "
    "for the statistics."
)

_CONTENT_BY_KIND: Final[dict[str, str]] = {
    "observation": (
        "Ramsar site boundaries (geometry), the site name (ram_ramsarname, "
        "stored as site) and the object id (objectid, stored in polygon_id as "
        "ramsar-<objectid>) of the DBCA-010 polygons the rows describe."
    ),
    "change": (
        "Ramsar site boundaries (geometry, taken from the observations) and the "
        "object id (objectid, stored in polygon_id as ramsar-<objectid>) of the "
        "DBCA-010 polygons the rows describe."
    ),
    "collection": (
        "The observation and change assets hold DBCA-010 Ramsar site boundaries "
        "and object ids; the observation assets also hold the site names."
    ),
}

_FILE_LICENCE_BY_KIND: Final[dict[str, str]] = {
    "observation": (
        f"This file holds adapted DBCA-010 material and is shared under "
        f"CC BY-NC 4.0 ({CC_BY_NC_4_URI}), for non-commercial use only."
    ),
    "change": (
        f"This file holds adapted DBCA-010 material and is shared under "
        f"CC BY-NC 4.0 ({CC_BY_NC_4_URI}), for non-commercial use only."
    ),
    "collection": (
        f"The observation and change assets of this collection hold adapted "
        f"DBCA-010 material and are shared under CC BY-NC 4.0 ({CC_BY_NC_4_URI}), "
        "for non-commercial use only."
    ),
}


def dbca_attribution(kind: DbcaKind) -> dict[str, Any]:
    """Return a new CC BY-NC 4.0 attribution block for a kind of published file.

    Args:
        kind: The published file kind, which selects the content and file
            licence statements.

    Raises:
        ValueError: If the kind is not one of the three known kinds.
    """
    if kind not in _CONTENT_BY_KIND:
        raise ValueError(f"unknown attribution kind {kind!r}")
    return {
        "notice": DBCA_ATTRIBUTION_TEXT,
        "creator": DBCA_CREATOR,
        "copyright": DBCA_COPYRIGHT,
        "dataset": DBCA_DATASET,
        "dataset_uri": DBCA_DATASET_URI,
        "sources": [DBCA_DATASET_URI, DBCA_SERVICE_URI],
        "licence": CC_BY_NC_4_NAME,
        "licence_uri": CC_BY_NC_4_URI,
        "licence_text_uri": CC_BY_NC_4_LEGALCODE_URI,
        "licence_basis": DBCA_LICENCE_BASIS,
        "file_licence": _FILE_LICENCE_BY_KIND[kind],
        "disclaimer": DBCA_DISCLAIMER,
        "modified": True,
        "content": _CONTENT_BY_KIND[kind],
        "modification": DBCA_MODIFICATION,
    }


def dbca_attribution_footer(kind: DbcaKind) -> dict[str, str]:
    """Return the attribution as one Parquet footer entry with stable JSON text."""
    return {DBCA_ATTRIBUTION_KEY: json.dumps(dbca_attribution(kind), sort_keys=True)}
