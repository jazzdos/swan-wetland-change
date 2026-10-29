"""GeoParquet 1.1 observation files with the bbox covering column.

One file per source item under `observations/year=YYYY/tile=<MGRS>/`, so a
rerun overwrites rather than appends. Rows are sorted and written through a
buffer, which makes a rewrite byte-identical.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

import geopandas as gpd
import pandas as pd

from wetland_change.stats import ObservationRow
from wetland_change.store import OutputStore

OBSERVATION_COLUMNS: tuple[str, ...] = (
    "polygon_id",
    "site",
    "aoi_layer",
    "item_id",
    "product_uri",
    "datetime",
    "tile",
    "processing_baseline",
    "scene_coverage",
    "n_pixels",
    "n_clear",
    "valid_fraction",
    "cloud_fraction",
    "water_ha_index",
    "water_ha_scl",
    "ndwi_median",
    "mndwi_median",
    "ndvi_median",
    "dea_wo_agreement",
    "run_id",
)


def observation_path(year: int, tile: str, item_id: str) -> str:
    return f"observations/year={year}/tile={tile}/obs_{item_id}.parquet"


def rows_to_frame(rows: Sequence[ObservationRow]) -> gpd.GeoDataFrame:
    ordered = sorted(rows, key=lambda r: (r.item_id, r.polygon_id))
    records = [{col: getattr(r, col) for col in OBSERVATION_COLUMNS} for r in ordered]
    frame = pd.DataFrame.from_records(records, columns=list(OBSERVATION_COLUMNS))
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    frame["dea_wo_agreement"] = frame["dea_wo_agreement"].astype("float64")
    return gpd.GeoDataFrame(
        frame, geometry=[r.geometry_4326 for r in ordered], crs="EPSG:4326"
    )


def to_geoparquet_bytes(frame: gpd.GeoDataFrame) -> bytes:
    buffer = BytesIO()
    frame.to_parquet(
        buffer, index=False, schema_version="1.1.0", write_covering_bbox=True
    )
    return buffer.getvalue()


def write_observations(rows: Sequence[ObservationRow], store: OutputStore) -> str:
    """Write one item's rows; returns the relative path."""
    if not rows:
        raise ValueError("no rows to write")
    items = {r.item_id for r in rows}
    if len(items) != 1:
        raise ValueError(f"one file per item; got {sorted(items)}")
    first = rows[0]
    relpath = observation_path(first.datetime.year, first.tile, first.item_id)
    store.write_bytes(relpath, to_geoparquet_bytes(rows_to_frame(rows)))
    return relpath
