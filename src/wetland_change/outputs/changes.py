"""GeoParquet 1.1 change files: the flagged scores of one source item.

One file per item under `changes/year=YYYY/tile=<MGRS>/`, written like the
observation files so a rerun overwrites with byte-identical content.
"""

from __future__ import annotations

from collections.abc import Mapping

import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry

from wetland_change.outputs.geoparquet import to_geoparquet_bytes
from wetland_change.store import OutputStore

CHANGE_COLUMNS: tuple[str, ...] = (
    "polygon_id",
    "item_id",
    "item_ids",
    "datetime",
    "tile",
    "month",
    "n_scenes",
    "scene_coverage",
    "valid_fraction",
    "metric",
    "value",
    "z",
    "baseline_median",
    "baseline_mad",
    "baseline_n",
)
_INT_COLUMNS = ("month", "n_scenes", "baseline_n")
_FLOAT_COLUMNS = (
    "scene_coverage",
    "valid_fraction",
    "value",
    "z",
    "baseline_median",
    "baseline_mad",
)


def change_path(year: int, tile: str, item_id: str) -> str:
    return f"changes/year={year}/tile={tile}/chg_{item_id}.parquet"


def changes_to_frame(
    scores: pd.DataFrame, geometries: Mapping[str, BaseGeometry]
) -> gpd.GeoDataFrame:
    """Flagged score rows as a typed, sorted GeoDataFrame in EPSG:4326."""
    ordered = scores.loc[:, list(CHANGE_COLUMNS)].sort_values(
        ["polygon_id", "metric"], kind="stable"
    )
    frame = ordered.reset_index(drop=True)
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    frame = frame.astype(
        {
            **dict.fromkeys(_INT_COLUMNS, "int64"),
            **dict.fromkeys(_FLOAT_COLUMNS, "float64"),
        }
    )
    geometry = [geometries[polygon_id] for polygon_id in frame["polygon_id"]]
    return gpd.GeoDataFrame(frame, geometry=geometry, crs="EPSG:4326")


def write_changes(
    scores: pd.DataFrame, geometries: Mapping[str, BaseGeometry], store: OutputStore
) -> str:
    """Write one item's flagged scores; returns the relative path."""
    if scores.empty:
        raise ValueError("no scores to write")
    items = sorted(set(scores["item_id"]))
    if len(items) != 1:
        raise ValueError(f"one file per item; got {items}")
    first = scores.iloc[0]
    year = pd.Timestamp(first["datetime"]).year
    relpath = change_path(year, str(first["tile"]), items[0])
    store.write_bytes(
        relpath, to_geoparquet_bytes(changes_to_frame(scores, geometries))
    )
    return relpath
