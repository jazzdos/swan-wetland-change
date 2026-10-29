"""Area-of-interest polygons: Ramsar sites (reporting) and DEA Waterbodies
(verification), reprojected to the operation CRS behind a CRS guard.

GeoJSON is EPSG:4326 by specification, so a file without a `crs` member is
accepted as 4326 only when the caller says so (`assume_crs`); the guard
refuses to infer anything else (crs-guard skill).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class AoiPolygon:
    polygon_id: str
    site: str
    layer: str
    geometry: BaseGeometry
    geometry_4326: BaseGeometry


def _declares_crs(path: Path) -> bool | None:
    """True/False whether a GeoJSON file has a top-level `crs` member.

    None for other formats, where `gdf.crs` is trustworthy. GDAL assigns WGS84
    to a GeoJSON without `crs`, so the raw file is inspected instead.
    """
    if path.suffix.lower() not in {".geojson", ".json"}:
        return None
    with path.open(encoding="utf-8") as fh:
        doc = json.load(fh)
    return isinstance(doc, dict) and "crs" in doc


def _read(path: Path, assume_crs: str | None) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    declared = _declares_crs(path)
    if declared is None:
        if gdf.crs is None:
            if assume_crs is None:
                raise ValueError(f"{path} has no CRS and none was assumed")
            gdf = gdf.set_crs(assume_crs)
    elif not declared:
        if assume_crs is None:
            raise ValueError(f"{path} has no CRS and none was assumed")
        gdf = gdf.set_crs(assume_crs, allow_override=True)
    return gdf


def _to_polygons(
    gdf: gpd.GeoDataFrame,
    *,
    id_prefix: str,
    id_column: str,
    site_column: str,
    layer: str,
    operation_epsg: int,
) -> list[AoiPolygon]:
    in_4326 = gdf.to_crs(4326)
    in_op = gdf.to_crs(operation_epsg)
    out: list[AoiPolygon] = []
    for (_, row4326), (_, row_op) in zip(
        in_4326.iterrows(), in_op.iterrows(), strict=True
    ):
        out.append(
            AoiPolygon(
                polygon_id=f"{id_prefix}-{row4326[id_column]}",
                site=str(row4326[site_column]),
                layer=layer,
                geometry=row_op.geometry,
                geometry_4326=row4326.geometry,
            )
        )
    return out


def load_ramsar(
    path: Path,
    *,
    site_prefixes: list[str],
    operation_epsg: int,
    assume_crs: str | None = "EPSG:4326",
) -> list[AoiPolygon]:
    """Ramsar polygons whose `ram_ramsarname` starts with one of the prefixes."""
    gdf = _read(path, assume_crs)
    names = gdf["ram_ramsarname"].astype(str)
    keep = names.map(lambda n: any(n.startswith(p) for p in site_prefixes))
    selected = gdf[keep].sort_values("objectid")
    return _to_polygons(
        selected,
        id_prefix="ramsar",
        id_column="objectid",
        site_column="ram_ramsarname",
        layer="ramsar",
        operation_epsg=operation_epsg,
    )


def load_waterbodies(
    path: Path,
    *,
    operation_epsg: int,
    assume_crs: str | None = "EPSG:4326",
) -> list[AoiPolygon]:
    """DEA Waterbodies polygons keyed by `uid`."""
    gdf = _read(path, assume_crs).sort_values("uid")
    return _to_polygons(
        gdf,
        id_prefix="dea",
        id_column="uid",
        site_column="uid",
        layer="dea_waterbody",
        operation_epsg=operation_epsg,
    )


def union_bbox_4326(polys: list[AoiPolygon]) -> tuple[float, float, float, float]:
    """(minx, miny, maxx, maxy) in EPSG:4326 over every polygon."""
    bounds = [p.geometry_4326.bounds for p in polys]
    return (
        min(b[0] for b in bounds),
        min(b[1] for b in bounds),
        max(b[2] for b in bounds),
        max(b[3] for b in bounds),
    )
