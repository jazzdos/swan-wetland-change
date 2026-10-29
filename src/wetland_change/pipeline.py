"""One incremental run: discover, guard, read, summarise, write, ledger."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from wetland_change import __version__
from wetland_change.aoi import AoiPolygon, union_bbox_4326
from wetland_change.catalogue.item import SceneItem
from wetland_change.catalogue.search import StacClient, discover
from wetland_change.config import PipelineConfig, WaterConfig
from wetland_change.ledger import (
    LedgerEntry,
    attempts_so_far,
    entry_for,
    exhausted_keys,
    read_ledger,
    rejected_entry,
    retry_ids,
    seen_keys,
    watermark,
    write_ledger,
)
from wetland_change.manifest import (
    RunManifest,
    config_sha256,
    new_run_id,
    write_manifest,
)
from wetland_change.outputs.geoparquet import write_observations
from wetland_change.raster.read import RasterReader, read_stack
from wetland_change.raster.scaling import check_band_scaling, parse_product_metadata
from wetland_change.stats import ObservationRow, summarise
from wetland_change.store import OutputStore
from wetland_change.windows import plan_window

logger = logging.getLogger(__name__)


class SceneGridError(ValueError):
    """The scene is not on the operation grid."""


def process_scene(
    scene: SceneItem,
    polygons: list[AoiPolygon],
    *,
    reader: RasterReader,
    water: WaterConfig,
    operation_epsg: int,
    run_id: str,
) -> list[ObservationRow]:
    """Rows for every polygon the scene covers. Raises on any guard failure."""
    grid = reader.open_grid(scene.bands["green"].href)
    if grid.epsg != operation_epsg or scene.epsg != operation_epsg:
        raise SceneGridError(
            f"{scene.item_id}: grid EPSG {grid.epsg}, item EPSG {scene.epsg}, "
            f"operation EPSG {operation_epsg}"
        )
    esa = parse_product_metadata(reader.read_text(scene.product_metadata_href))
    for band in scene.bands.values():
        check_band_scaling(band, esa)
    rows: list[ObservationRow] = []
    for polygon in polygons:
        planned = plan_window(polygon.geometry, grid)
        if planned is None:
            continue
        stack = read_stack(scene, planned, reader)
        rows.append(
            summarise(polygon, scene, stack, planned, water=water, run_id=run_id)
        )
    return rows


def run_once(
    cfg: PipelineConfig,
    *,
    client: StacClient,
    reader: RasterReader,
    store: OutputStore,
    polygons: list[AoiPolygon],
    now: datetime,
    config_path: Path,
) -> RunManifest:
    """Process everything new since the ledger watermark. Never aborts on a
    single scene; failures go to the ledger and are retried next run."""
    run_id = new_run_id(now)
    ledger = read_ledger(store)
    before = watermark(ledger)
    created_from = (
        before - timedelta(days=cfg.stac.watermark_overlap_days) if before else None
    )
    discovery = discover(
        client,
        cfg.stac,
        bbox=union_bbox_4326(polygons),
        polygons_4326=[p.geometry_4326 for p in polygons],
        created_from=created_from,
        seen=seen_keys(ledger) | exhausted_keys(ledger),
        retry_ids=retry_ids(ledger),
    )
    manifest = RunManifest(
        run_id=run_id,
        started_at=now,
        finished_at=None,
        package_version=__version__,
        config_sha256=config_sha256(config_path),
        endpoint=cfg.stac.endpoint,
        collection=cfg.stac.collection,
        watermark_before=before,
        watermark_after=before,
        discovered=len(discovery.scenes),
        rejected=len(discovery.rejected),
        skipped_seen=discovery.skipped_seen,
        skipped_filter=discovery.skipped_filter,
    )
    entries: list[LedgerEntry] = []
    for scene in discovery.scenes:
        attempts = attempts_so_far(ledger, scene.item_id) + 1
        try:
            rows = process_scene(
                scene,
                polygons,
                reader=reader,
                water=cfg.water,
                operation_epsg=cfg.aoi.operation_epsg,
                run_id=run_id,
            )
            path = write_observations(rows, store) if rows else None
        except Exception as exc:
            logger.exception("scene %s failed (attempt %d)", scene.item_id, attempts)
            entries.append(
                entry_for(
                    scene,
                    status="failed",
                    attempts=attempts,
                    run_id=run_id,
                    processed_at=now,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            manifest.failed += 1
            continue
        entries.append(
            entry_for(
                scene,
                status="succeeded",
                attempts=attempts,
                run_id=run_id,
                processed_at=now,
                n_rows=len(rows),
                observation_path=path,
            )
        )
        manifest.processed += 1
        if path:
            manifest.observation_files.append(path)
    for item_id, reason in discovery.rejected:
        entries.append(rejected_entry(item_id, reason, run_id=run_id, processed_at=now))
    manifest.ledger_files = write_ledger(entries, store, run_id=run_id)
    manifest.watermark_after = watermark(read_ledger(store))
    manifest.finished_at = now
    write_manifest(manifest, store)
    return manifest
