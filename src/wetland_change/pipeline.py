"""One incremental run: discover, guard, read, summarise, write, ledger."""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa

from wetland_change import __version__
from wetland_change.aoi import AoiPolygon, union_bbox_4326
from wetland_change.catalogue.item import SceneItem
from wetland_change.catalogue.search import Discovery, StacClient, discover
from wetland_change.change import build_baseline, score_observations
from wetland_change.config import PipelineConfig, WaterConfig
from wetland_change.ledger import (
    RUN_KIND_BACKFILL,
    RUN_KIND_RUN,
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
    KIND_SCORE,
    RunManifest,
    config_sha256,
    manifest_path,
    new_run_id,
    write_manifest,
)
from wetland_change.outputs.changes import change_path, write_changes
from wetland_change.outputs.geoparquet import read_observations, write_observations
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


def _new_manifest(
    cfg: PipelineConfig,
    *,
    run_id: str,
    now: datetime,
    config_path: Path,
    before: datetime | None,
    discovery: Discovery,
    kind: str,
    output_root_override: str | None,
    datetime_start: datetime | None = None,
    datetime_end: datetime | None = None,
) -> RunManifest:
    return RunManifest(
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
        kind=kind,
        datetime_start=datetime_start,
        datetime_end=datetime_end,
        output_root_override=output_root_override,
    )


def _process_one(
    scene: SceneItem,
    *,
    ledger: pa.Table,
    cfg: PipelineConfig,
    reader: RasterReader,
    store: OutputStore,
    polygons: list[AoiPolygon],
    run_id: str,
    now: datetime,
    run_kind: str,
) -> tuple[LedgerEntry, str | None]:
    """Process one scene to a ledger entry and the observation file it wrote.
    Any Exception becomes a failed entry."""
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
        return (
            entry_for(
                scene,
                status="failed",
                attempts=attempts,
                run_id=run_id,
                processed_at=now,
                error=f"{type(exc).__name__}: {exc}",
                run_kind=run_kind,
            ),
            None,
        )
    return (
        entry_for(
            scene,
            status="succeeded",
            attempts=attempts,
            run_id=run_id,
            processed_at=now,
            n_rows=len(rows),
            observation_path=path,
            run_kind=run_kind,
        ),
        path,
    )


def _tally(manifest: RunManifest, entry: LedgerEntry, path: str | None) -> None:
    if entry.status == "failed":
        manifest.failed += 1
        return
    manifest.processed += 1
    if path:
        manifest.observation_files.append(path)


@dataclass(frozen=True)
class ScoreResult:
    files: list[str]
    rows: int
    removed: list[str]


def score_changes(
    store: OutputStore,
    *,
    min_valid_fraction: float,
    dates: Collection[date] | None = None,
    date_range: tuple[date, date] | None = None,
) -> ScoreResult:
    """Score stored observations by UTC acquisition date and write change files.

    Each date is scored against history of the same polygon and month from
    strictly earlier UTC dates only (ADR 0004), so a rerun over an unchanged
    store is byte-identical. A change file whose item is no longer flagged is
    deleted. `dates` and the inclusive `date_range` narrow the stored dates.
    """
    observations = read_observations(store)
    frame = pd.DataFrame(observations.drop(columns="geometry"))
    geometry_by_polygon = dict(
        zip(observations["polygon_id"], observations.geometry, strict=True)
    )
    frame["acq_date"] = frame["datetime"].dt.tz_convert(UTC).dt.date
    wanted = sorted(set(frame["acq_date"]))
    if dates is not None:
        wanted = [d for d in wanted if d in set(dates)]
    if date_range is not None:
        first, last = date_range
        wanted = [d for d in wanted if first <= d <= last]
    files: list[str] = []
    removed: list[str] = []
    rows = 0
    for day in wanted:
        day_rows = frame[frame["acq_date"] == day]
        history = frame[
            (frame["acq_date"] < day)
            & (frame["polygon_id"].isin(day_rows["polygon_id"]))
            & (frame["datetime"].dt.month == day.month)
        ]
        baseline = build_baseline(history, min_valid_fraction=min_valid_fraction)
        scores = score_observations(
            day_rows, baseline, min_valid_fraction=min_valid_fraction
        )
        flagged = scores[scores["flagged"]]
        geometries = {
            polygon_id: geometry_by_polygon[polygon_id]
            for polygon_id in day_rows["polygon_id"]
        }
        written: set[str] = set()
        for _, group in flagged.groupby("item_id", sort=True):
            written.add(write_changes(group, geometries, store))
            rows += len(group)
        files.extend(sorted(written))
        candidates = {
            change_path(row.datetime.year, row.tile, row.item_id)
            for row in day_rows.itertuples()
        }
        for relpath in sorted(candidates - written):
            if store.delete(relpath):
                removed.append(relpath)
    return ScoreResult(files=sorted(files), rows=rows, removed=sorted(removed))


def run_once(
    cfg: PipelineConfig,
    *,
    client: StacClient,
    reader: RasterReader,
    store: OutputStore,
    polygons: list[AoiPolygon],
    now: datetime,
    config_path: Path,
    output_root_override: str | None = None,
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
    manifest = _new_manifest(
        cfg,
        run_id=run_id,
        now=now,
        config_path=config_path,
        before=before,
        discovery=discovery,
        kind=RUN_KIND_RUN,
        output_root_override=output_root_override,
    )
    entries: list[LedgerEntry] = []
    written_dates: set[date] = set()
    for scene in discovery.scenes:
        entry, path = _process_one(
            scene,
            ledger=ledger,
            cfg=cfg,
            reader=reader,
            store=store,
            polygons=polygons,
            run_id=run_id,
            now=now,
            run_kind=RUN_KIND_RUN,
        )
        entries.append(entry)
        if path is not None and entry.datetime is not None:
            written_dates.add(entry.datetime.astimezone(UTC).date())
        _tally(manifest, entry, path)
    for item_id, reason in discovery.rejected:
        entries.append(
            rejected_entry(
                item_id,
                reason,
                run_id=run_id,
                processed_at=now,
                run_kind=RUN_KIND_RUN,
            )
        )
    manifest.ledger_files = write_ledger(entries, store, run_id=run_id)
    manifest.watermark_after = watermark(read_ledger(store))
    if written_dates:
        scored = score_changes(
            store,
            min_valid_fraction=cfg.water.min_valid_fraction,
            dates=written_dates,
        )
        manifest.change_rows = scored.rows
        manifest.change_files = scored.files
        manifest.change_files_removed = scored.removed
    manifest.finished_at = now
    write_manifest(manifest, store)
    return manifest


def _refuse_reused_run_id(store: OutputStore, run_id: str) -> None:
    """Part numbering restarts at 0, so a run id already on disk would have its
    manifest or ledger parts overwritten, losing the interrupted run's rows.
    """
    prefix = f"ledger_{run_id}_"
    reused = store.exists(manifest_path(run_id)) or any(
        Path(p).name.startswith(prefix) for p in store.list_files("ledger")
    )
    if reused:
        raise ValueError(
            f"run id {run_id} already has a manifest or ledger parts in the output "
            "root; rerun with a later --now so the earlier rows are not overwritten"
        )


def backfill_once(
    cfg: PipelineConfig,
    *,
    start: datetime,
    end: datetime,
    client: StacClient,
    reader: RasterReader,
    store: OutputStore,
    polygons: list[AoiPolygon],
    now: datetime,
    config_path: Path,
    output_root_override: str | None = None,
) -> RunManifest:
    """Run stages 1 to 6 for items acquired in the closed interval [start, end].

    Items already in the ledger (by id and `updated`) are skipped, so a repeat
    writes nothing new. The ledger is checkpointed after every scene, so an
    interrupted backfill resumes where it stopped. Rows are tagged backfill,
    so the daily watermark ignores them. Failed items under the attempt cap
    are retried on rerun.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("backfill start and end must be timezone-aware")
    if start > end:
        raise ValueError(f"backfill start {start} is after end {end}")
    run_id = new_run_id(now)
    _refuse_reused_run_id(store, run_id)
    ledger = read_ledger(store)
    before = watermark(ledger)
    discovery = discover(
        client,
        cfg.stac,
        bbox=union_bbox_4326(polygons),
        polygons_4326=[p.geometry_4326 for p in polygons],
        created_from=None,
        seen=seen_keys(ledger) | exhausted_keys(ledger),
        retry_ids=(),
        datetime_range=(start, end),
    )
    manifest = _new_manifest(
        cfg,
        run_id=run_id,
        now=now,
        config_path=config_path,
        before=before,
        discovery=discovery,
        kind=RUN_KIND_BACKFILL,
        output_root_override=output_root_override,
        datetime_start=start,
        datetime_end=end,
    )
    next_part = 0
    if discovery.rejected:
        rejected = [
            rejected_entry(
                item_id,
                reason,
                run_id=run_id,
                processed_at=now,
                run_kind=RUN_KIND_BACKFILL,
            )
            for item_id, reason in discovery.rejected
        ]
        manifest.ledger_files += write_ledger(
            rejected, store, run_id=run_id, part=next_part
        )
        next_part += 1
    for scene in discovery.scenes:
        entry, path = _process_one(
            scene,
            ledger=ledger,
            cfg=cfg,
            reader=reader,
            store=store,
            polygons=polygons,
            run_id=run_id,
            now=now,
            run_kind=RUN_KIND_BACKFILL,
        )
        _tally(manifest, entry, path)
        manifest.ledger_files += write_ledger(
            [entry], store, run_id=run_id, part=next_part
        )
        next_part += 1
    manifest.watermark_after = watermark(read_ledger(store))
    manifest.finished_at = now
    write_manifest(manifest, store)
    return manifest


def score_once(
    cfg: PipelineConfig,
    *,
    start: datetime,
    end: datetime,
    store: OutputStore,
    now: datetime,
    config_path: Path,
    output_root_override: str | None = None,
) -> RunManifest:
    """Rescore every stored UTC date in [start, end] and write a score manifest.

    Used after a backfill, which does not score. Change files whose item is
    no longer flagged are deleted.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("score start and end must be timezone-aware")
    if start > end:
        raise ValueError(f"score start {start} is after end {end}")
    run_id = new_run_id(now)
    if store.exists(manifest_path(run_id)):
        raise ValueError(
            f"run id {run_id} already has a manifest in the output root; "
            "rerun with a later --now"
        )
    scored = score_changes(
        store,
        min_valid_fraction=cfg.water.min_valid_fraction,
        date_range=(start.astimezone(UTC).date(), end.astimezone(UTC).date()),
    )
    manifest = RunManifest(
        run_id=run_id,
        started_at=now,
        finished_at=now,
        package_version=__version__,
        config_sha256=config_sha256(config_path),
        endpoint=cfg.stac.endpoint,
        collection=cfg.stac.collection,
        watermark_before=None,
        watermark_after=None,
        kind=KIND_SCORE,
        datetime_start=start,
        datetime_end=end,
        output_root_override=output_root_override,
        change_rows=scored.rows,
        change_files=scored.files,
        change_files_removed=scored.removed,
    )
    write_manifest(manifest, store)
    return manifest
