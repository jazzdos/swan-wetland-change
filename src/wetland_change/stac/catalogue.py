"""Build, validate and write the STAC catalogue from the ledger alone.

Items come from the ledger's `source_item` JSON, never a fresh fetch. Output
is deterministic: no clock reads, sorted keys, items ordered by id.

`write_catalogue` writes only objects that are new or changed. Every object's
bytes are built in memory, then compared with `stac/write-index.json`, a
sidecar mapping each object key to the sha256 of the bytes last written, plus
the normalised `base_url`. One `list_files("stac")` call tells it which
objects exist and whether the index exists, so there is no per-object
request. An object is written when the index base_url differs, its key is
missing from the listing, or its digest differs from the index entry. The
index is written last, so a crash leaves a stale index that causes a rewrite,
never a skip. A missing, unreadable or malformed index counts as empty. The
index is not linked from the catalogue, so `validate_all` never sees it, and
its key is never in the returned list.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import tempfile
from collections.abc import Collection
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pyarrow as pa
import pystac
import stac_geoparquet.arrow
from shapely.geometry import shape

from wetland_change.catalogue.item import parse_timestamp
from wetland_change.ledger import read_ledger
from wetland_change.outputs.changes import change_path
from wetland_change.store import OutputStore
from wetland_change.verify.checks import report_path

CATALOG_ID = "swan-wetland-change-catalog"
COLLECTION_ID = "swan-wetland-change"
LICENSE = "CC-BY-SA-4.0"
SWAN_COASTAL_PLAIN_BBOX = [114.9, -33.3, 115.9, -31.5]
PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"
ITEMS_PARQUET_KEY = f"stac/{COLLECTION_ID}/items.parquet"
WRITE_INDEX_KEY = "stac/write-index.json"
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


def _item(
    entry: dict[str, Any], base_url: str, available: Collection[str]
) -> pystac.Item:
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
    when, tile = entry["datetime"], entry["tile"]
    if when is not None and tile is not None:
        changes = change_path(when.astimezone(dt.UTC).year, tile, entry["item_id"])
        if changes in available:
            item.add_asset(
                "changes",
                pystac.Asset(
                    href=f"{base_url}/{changes}",
                    title="Changes (GeoParquet)",
                    media_type=PARQUET_MEDIA_TYPE,
                    roles=["data"],
                ),
            )
    if entry["run_id"] is not None:
        report = report_path(entry["run_id"])
        if report in available:
            item.add_asset(
                "verification",
                pystac.Asset(
                    href=f"{base_url}/{report}",
                    title="Verification report",
                    media_type="application/json",
                    roles=["metadata"],
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


def build_catalogue(
    ledger: pa.Table, *, base_url: str, available: Collection[str] = frozenset()
) -> pystac.Catalog:
    """`available` holds the store-relative paths that exist, gating item assets."""
    base_url = base_url.rstrip("/")
    items = [_item(entry, base_url, available) for entry in processed_entries(ledger)]
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
    if items:
        collection.add_asset(
            "items",
            pystac.Asset(
                href=f"{base_url}/{ITEMS_PARQUET_KEY}",
                title="Catalogue items (stac-geoparquet)",
                media_type=PARQUET_MEDIA_TYPE,
                roles=["data"],
            ),
        )
    catalog = pystac.Catalog(
        id=CATALOG_ID,
        description="Sentinel-2 wetland observations for the Swan Coastal Plain.",
        title="Swan wetland change catalogue",
        catalog_type=pystac.CatalogType.ABSOLUTE_PUBLISHED,
    )
    catalog.add_child(collection)
    catalog.normalize_hrefs(f"{base_url}/stac")
    return catalog


def items_parquet_bytes(items: list[dict[str, Any]]) -> bytes:
    """stac-geoparquet file bytes; `to_parquet` needs a real path, not a BytesIO."""
    table = stac_geoparquet.arrow.parse_stac_items_to_arrow(items)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "items.parquet"
        stac_geoparquet.arrow.to_parquet(table, path)
        return path.read_bytes()


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
    collection_assets = [
        c.assets.get("items")
        for c in catalog.get_children()
        if isinstance(c, pystac.Collection)
    ]
    items_asset = next((a for a in collection_assets if a is not None), None)
    items_key: str | None = None
    if items_asset is not None:
        if not items_asset.href.startswith(prefix):
            raise ValueError(
                f"items asset href {items_asset.href!r} does not start with "
                f"base_url {prefix!r}; write_catalogue base_url must match "
                "build_catalogue base_url"
            )
        items_key = items_asset.href.removeprefix(prefix)
    payloads: dict[str, bytes] = {}
    if items_key is not None:
        all_items = sorted(catalog.get_items(recursive=True), key=lambda i: i.id)
        dicts = [
            i.to_dict(include_self_link=True, transform_hrefs=False) for i in all_items
        ]
        payloads[items_key] = items_parquet_bytes(dicts)
    for obj, key in zip(objects, keys, strict=True):
        text = (
            json.dumps(
                obj.to_dict(include_self_link=True, transform_hrefs=False),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        payloads[key] = text.encode()
    digests = {key: hashlib.sha256(data).hexdigest() for key, data in payloads.items()}
    normalised = prefix.rstrip("/")
    listing = set(store.list_files("stac"))
    old_url, old_digests = _read_write_index(store, listing)
    same_url = old_url == normalised
    written = sorted(
        key
        for key, digest in digests.items()
        if not same_url or key not in listing or old_digests.get(key) != digest
    )
    for key in written:
        store.write_bytes(key, payloads[key])
    if written or not same_url or old_digests != digests:
        index = {"base_url": normalised, "objects": digests}
        store.write_bytes(
            WRITE_INDEX_KEY,
            (json.dumps(index, indent=2, sort_keys=True) + "\n").encode(),
        )
    return written


def _read_write_index(
    store: OutputStore, listing: Collection[str]
) -> tuple[str | None, dict[str, str]]:
    """The recorded base_url and digests; (None, {}) when absent or malformed."""
    if WRITE_INDEX_KEY not in listing:
        return None, {}
    try:
        doc = json.loads(store.read_bytes(WRITE_INDEX_KEY))
    except (OSError, ValueError):
        return None, {}
    if not isinstance(doc, dict):
        return None, {}
    url, objects = doc.get("base_url"), doc.get("objects")
    if not isinstance(url, str) or not isinstance(objects, dict):
        return None, {}
    return url, {k: v for k, v in objects.items() if isinstance(v, str)}


class PlaceholderBaseUrlError(ValueError):
    """The configured base_url is a placeholder and the store is remote."""


def ensure_publishable_base_url(base_url: str, store: OutputStore) -> None:
    """Refuse a placeholder `.invalid` base_url when the store is not local.

    Local roots are never rejected, so tests and dry runs can keep the
    placeholder. A remote root would publish links that cannot resolve.
    """
    if store.uri.startswith("file://"):
        return
    host = urlsplit(base_url).hostname or ""
    if host == "invalid" or host.endswith(".invalid"):
        raise PlaceholderBaseUrlError(
            f"catalogue.base_url {base_url!r} is a placeholder; set it in "
            "config/pipeline.toml to the bucket_url output of infra before "
            f"publishing to {store.uri}"
        )


def build_and_write(
    store: OutputStore, *, base_url: str, ledger: pa.Table | None = None
) -> list[str]:
    """Build, validate and write the catalogue; returns keys actually written.

    A caller that already holds the ledger passes it to skip the store read.
    """
    ensure_publishable_base_url(base_url, store)
    available = set(store.list_files("changes")) | set(store.list_files("verification"))
    catalog = build_catalogue(
        read_ledger(store) if ledger is None else ledger,
        base_url=base_url,
        available=available,
    )
    validate_catalogue(catalog)
    return write_catalogue(catalog, store, base_url=base_url)
