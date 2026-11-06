"""GeoParquet 1.1 observation files with the bbox covering column.

One file per source item under `observations/year=YYYY/tile=<MGRS>/`, so a
rerun overwrites rather than appends. Rows are sorted and written through a
buffer, which makes a rewrite byte-identical.

The footer carries the `geo` key plus the keys of `outputs.provenance`:
source_epsg, operation_epsg, geometry_epsg, units, scl_classes_dropped,
scl_classes_clear, clear_pixel_rule, water_settings and water_units_note.
source_epsg equals operation_epsg because `process_scene` refuses any scene
whose EPSG differs from the operation EPSG. Files written before these keys
existed still read, because readers use only the `geo` key.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from io import BytesIO

import geopandas as gpd
import pandas as pd
import pyarrow.parquet as pq

from wetland_change.config import WaterConfig
from wetland_change.outputs.provenance import footer_metadata
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


def to_geoparquet_bytes(frame: gpd.GeoDataFrame, metadata: Mapping[str, str]) -> bytes:
    """GeoParquet 1.1 bytes with `metadata` merged into the footer.

    The `geo` key written by geopandas is kept; `metadata` keys are added in
    sorted order so a rewrite is byte-identical.
    """
    plain = BytesIO()
    frame.to_parquet(
        plain, index=False, schema_version="1.1.0", write_covering_bbox=True
    )
    table = pq.read_table(BytesIO(plain.getvalue()))
    merged = {
        **(table.schema.metadata or {}),
        **{key.encode(): value.encode() for key, value in sorted(metadata.items())},
    }
    out = BytesIO()
    pq.write_table(table.replace_schema_metadata(merged), out, compression="snappy")
    return out.getvalue()


def write_observations(
    rows: Sequence[ObservationRow],
    store: OutputStore,
    *,
    water: WaterConfig,
    operation_epsg: int,
) -> str:
    """Write one item's rows with provenance footer keys; returns the path."""
    if not rows:
        raise ValueError("no rows to write")
    items = {r.item_id for r in rows}
    if len(items) != 1:
        raise ValueError(f"one file per item; got {sorted(items)}")
    first = rows[0]
    relpath = observation_path(first.datetime.year, first.tile, first.item_id)
    frame = rows_to_frame(rows)
    footer = footer_metadata(
        frame, kind="observation", water=water, operation_epsg=operation_epsg
    )
    store.write_bytes(relpath, to_geoparquet_bytes(frame, footer))
    return relpath


def observation_paths(store: OutputStore, exclude: Collection[str] = ()) -> list[str]:
    """Paths of the stored `obs_*.parquet` files, sorted, minus those in `exclude`."""
    skipped = set(exclude)
    return [
        path
        for path in store.list_files("observations")
        if path.rsplit("/", 1)[-1].startswith("obs_")
        and path.endswith(".parquet")
        and path not in skipped
    ]


def _empty_observations() -> gpd.GeoDataFrame:
    frame = pd.DataFrame({col: [] for col in OBSERVATION_COLUMNS})
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    return gpd.GeoDataFrame(frame, geometry=[], crs="EPSG:4326")


def read_observations(
    store: OutputStore, exclude: Collection[str] = ()
) -> gpd.GeoDataFrame:
    """Every stored observation, sorted by item then polygon.

    The store is listed once; files named in `exclude` are not read.
    """
    paths = observation_paths(store, exclude)
    if not paths:
        return _empty_observations()
    frames = [gpd.read_parquet(BytesIO(store.read_bytes(path))) for path in paths]
    combined = pd.concat(frames, ignore_index=True)
    ordered = combined.sort_values(["item_id", "polygon_id"], kind="stable")
    return gpd.GeoDataFrame(
        ordered.reset_index(drop=True), geometry="geometry", crs="EPSG:4326"
    )
