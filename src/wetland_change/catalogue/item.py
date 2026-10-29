"""Parse and guard one Earth Search item before any byte is read.

The guard refuses anything that would silently corrupt reflectance: a
different collection, an `earthsearch:boa_offset_applied` flag (offset
already baked in), a missing asset, or a reflectance band without
`raster:bands` scale and offset.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

REFLECTANCE_BANDS: tuple[str, ...] = ("green", "red", "nir", "swir16")
OFFSET_APPLIED_KEY = "earthsearch:boa_offset_applied"


class ItemGuardError(ValueError):
    """The item must not be processed; the message says why."""


@dataclass(frozen=True)
class BandSpec:
    key: str
    href: str
    nodata: int
    scale: float
    offset: float
    resolution: int


@dataclass(frozen=True)
class SceneItem:
    item_id: str
    collection: str
    product_uri: str
    datetime: dt.datetime
    created: dt.datetime
    updated: dt.datetime
    tile: str
    processing_baseline: str
    epsg: int
    cloud_cover: float
    geometry_4326: BaseGeometry
    bands: dict[str, BandSpec]
    scl_href: str
    product_metadata_href: str
    raw: dict[str, Any]

    @property
    def year(self) -> int:
        return self.datetime.year


def parse_timestamp(value: str) -> dt.datetime:
    """RFC 3339 with a trailing Z to an aware datetime."""
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _epsg(props: dict[str, Any]) -> int:
    if props.get("proj:epsg") is not None:
        return int(props["proj:epsg"])
    code = props.get("proj:code")
    if isinstance(code, str) and code.upper().startswith("EPSG:"):
        return int(code.split(":")[1])
    raise ItemGuardError("item has neither proj:epsg nor an EPSG proj:code")


def _band(key: str, asset: dict[str, Any]) -> BandSpec:
    bands = asset.get("raster:bands") or []
    if not bands or "scale" not in bands[0] or "offset" not in bands[0]:
        raise ItemGuardError(f"asset {key!r} has no raster:bands scale and offset")
    spec = bands[0]
    return BandSpec(
        key=key,
        href=str(asset["href"]),
        nodata=int(spec.get("nodata", 0)),
        scale=float(spec["scale"]),
        offset=float(spec["offset"]),
        resolution=int(spec["spatial_resolution"]),
    )


def parse_item(
    item: dict[str, Any], *, collection: str, required_assets: list[str]
) -> SceneItem:
    """Validate an item dict and extract what the pipeline needs."""
    item_id = str(item.get("id", "<no id>"))
    if item.get("collection") != collection:
        raise ItemGuardError(
            f"{item_id}: collection {item.get('collection')!r} is not {collection!r}"
        )
    props: dict[str, Any] = item["properties"]
    if OFFSET_APPLIED_KEY in props:
        raise ItemGuardError(f"{item_id}: {OFFSET_APPLIED_KEY} present; offset trap")
    assets: dict[str, Any] = item.get("assets", {})
    needed = set(required_assets) | set(REFLECTANCE_BANDS) | {"scl", "product_metadata"}
    missing = sorted(key for key in needed if key not in assets)
    if missing:
        raise ItemGuardError(f"{item_id}: missing assets {missing}")
    bands = {key: _band(key, assets[key]) for key in REFLECTANCE_BANDS}
    return SceneItem(
        item_id=item_id,
        collection=str(item["collection"]),
        product_uri=str(props["s2:product_uri"]),
        datetime=parse_timestamp(props["datetime"]),
        created=parse_timestamp(props["created"]),
        updated=parse_timestamp(props["updated"]),
        tile=str(props["grid:code"]).removeprefix("MGRS-"),
        processing_baseline=str(props["s2:processing_baseline"]),
        epsg=_epsg(props),
        cloud_cover=float(props["eo:cloud_cover"]),
        geometry_4326=shape(item["geometry"]),
        bands=bands,
        scl_href=str(assets["scl"]["href"]),
        product_metadata_href=str(assets["product_metadata"]["href"]),
        raw=item,
    )
