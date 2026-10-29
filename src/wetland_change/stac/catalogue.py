"""Build, validate and write the STAC catalogue from the ledger alone.

Items come from the ledger's `source_item` JSON, never a fresh fetch. Output
is deterministic: no clock reads, sorted keys, items ordered by id.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pyarrow as pa
import pystac
from shapely.geometry import shape

from wetland_change.catalogue.item import parse_timestamp
from wetland_change.ledger import read_ledger
from wetland_change.store import OutputStore

CATALOG_ID = "swan-wetland-change-catalog"
COLLECTION_ID = "swan-wetland-change"
LICENSE = "CC-BY-SA-4.0"
SWAN_COASTAL_PLAIN_BBOX = [114.9, -33.3, 115.9, -31.5]
PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"
KEPT_PROPERTIES = (
    "created",
    "updated",
    "platform",
    "constellation",
    "instruments",
    "eo:cloud_cover",
    "grid:code",
    "s2:product_uri",
    "s2:processing_baseline",
    "proj:epsg",
)
PROVIDERS = (
    (
        "Element 84 (Earth Search)",
        [pystac.ProviderRole.PROCESSOR, pystac.ProviderRole.HOST],
        "https://www.element84.com/earth-search/",
    ),
    (
        "European Space Agency (ESA)",
        [pystac.ProviderRole.PRODUCER, pystac.ProviderRole.LICENSOR],
        "https://www.esa.int/",
    ),
    (
        "Department of Biodiversity, Conservation and Attractions (DBCA)",
        [pystac.ProviderRole.LICENSOR],
        "https://www.dbca.wa.gov.au/",
    ),
    (
        "Geoscience Australia (DEA)",
        [pystac.ProviderRole.LICENSOR],
        "https://www.dea.ga.gov.au/",
    ),
)


def processed_entries(ledger: pa.Table) -> list[dict[str, Any]]:
    """Latest row per item that succeeded and kept its source item, by id."""
    rows = sorted(
        ledger.to_pylist(), key=lambda r: (r["processed_at"], r["run_id"] or "")
    )
    latest = {row["item_id"]: row for row in rows}
    return [
        latest[item_id]
        for item_id in sorted(latest)
        if latest[item_id]["status"] == "succeeded"
        and latest[item_id]["source_item"] is not None
    ]


def _item(entry: dict[str, Any], base_url: str) -> pystac.Item:
    source: dict[str, Any] = json.loads(entry["source_item"])
    geometry = source["geometry"]
    bbox = source.get("bbox") or list(shape(geometry).bounds)
    props = source["properties"]
    item = pystac.Item(
        id=source["id"],
        geometry=geometry,
        bbox=bbox,
        datetime=parse_timestamp(props["datetime"]),
        properties={k: props[k] for k in KEPT_PROPERTIES if k in props},
    )
    for link in source.get("links", []):
        if link.get("rel") == "self" and str(link.get("href", "")).startswith(
            "https://"
        ):
            item.add_link(
                pystac.Link(
                    "derived_from", link["href"], media_type="application/geo+json"
                )
            )
    if entry["observation_path"] is not None:
        item.add_asset(
            "observations",
            pystac.Asset(
                href=f"{base_url}/{entry['observation_path']}",
                title="Observations (GeoParquet)",
                media_type=PARQUET_MEDIA_TYPE,
                roles=["data"],
            ),
        )
    return item


def _extent(items: list[pystac.Item]) -> pystac.Extent:
    if not items:
        open_interval: list[list[dt.datetime | None]] = [[None, None]]
        return pystac.Extent(
            pystac.SpatialExtent([SWAN_COASTAL_PLAIN_BBOX]),
            pystac.TemporalExtent(open_interval),
        )
    boxes = [item.bbox for item in items if item.bbox is not None]
    union = [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]
    times = [item.datetime for item in items if item.datetime is not None]
    return pystac.Extent(
        pystac.SpatialExtent([union]),
        pystac.TemporalExtent([[min(times), max(times)]]),
    )


def build_catalogue(ledger: pa.Table, *, base_url: str) -> pystac.Catalog:
    base_url = base_url.rstrip("/")
    items = [_item(entry, base_url) for entry in processed_entries(ledger)]
    collection = pystac.Collection(
        id=COLLECTION_ID,
        title="Swan Coastal Plain wetland change",
        description=(
            "Sentinel-2 Collection 1 NDWI and NDVI wetland observations for "
            "Swan Coastal Plain Ramsar sites, one GeoParquet file per source scene."
        ),
        extent=_extent(items),
        license=LICENSE,
        providers=[
            pystac.Provider(name=name, roles=roles, url=url)
            for name, roles, url in PROVIDERS
        ],
    )
    for item in items:
        collection.add_item(item)
    catalog = pystac.Catalog(
        id=CATALOG_ID,
        description="Sentinel-2 wetland observations for the Swan Coastal Plain.",
        title="Swan wetland change catalogue",
        catalog_type=pystac.CatalogType.ABSOLUTE_PUBLISHED,
    )
    catalog.add_child(collection)
    catalog.normalize_hrefs(f"{base_url}/stac")
    return catalog


def validate_catalogue(catalog: pystac.Catalog) -> None:
    """Validate in memory against the schemas bundled with pystac."""
    catalog.validate_all()


def write_catalogue(
    catalog: pystac.Catalog, store: OutputStore, *, base_url: str
) -> list[str]:
    prefix = f"{base_url.rstrip('/')}/"
    objects: list[pystac.STACObject] = [
        catalog,
        *catalog.get_children(),
        *catalog.get_items(recursive=True),
    ]
    keys: list[str] = []
    for obj in objects:
        href = obj.get_self_href()
        if href is None or not href.startswith(prefix):
            raise ValueError(
                f"self href {href!r} does not start with base_url {prefix!r}; "
                "write_catalogue base_url must match build_catalogue base_url"
            )
        keys.append(href.removeprefix(prefix))
    written: list[str] = []
    for obj, key in zip(objects, keys, strict=True):
        text = (
            json.dumps(
                obj.to_dict(include_self_link=True, transform_hrefs=False),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        written.append(store.write_bytes(key, text.encode()))
    return sorted(written)


def build_and_write(store: OutputStore, *, base_url: str) -> list[str]:
    catalog = build_catalogue(read_ledger(store), base_url=base_url)
    validate_catalogue(catalog)
    return write_catalogue(catalog, store, base_url=base_url)
