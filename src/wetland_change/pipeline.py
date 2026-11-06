"""One incremental run: discover, guard, read, summarise, write, ledger."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Collection, Sequence
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
from wetland_change.config import PipelineConfig, StacConfig, WaterConfig
from wetland_change.ledger import (
    COMPACT_MIN_PARTS,
    RUN_KIND_BACKFILL,
    RUN_KIND_RUN,
    LedgerEntry,
    attempts_so_far,
    compact_ledger,
    entry_for,
    exhausted_ids,
    exhausted_keys,
    ledger_with,
    observation_months,
    read_ledger_parts,
    rejected_entry,
    rejected_keys,
    requeue_entries,
    retry_ids,
    scored_dates,
    seen_keys,
    unfinished_runs,
    watermark,
    write_ledger,
)
from wetland_change.manifest import (
    KIND_REQUEUE,
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
from wetland_change.runtime import capture_environment
from wetland_change.stac import build_and_write, ensure_publishable_base_url
from wetland_change.stats import ObservationRow, rasterise, summarise
from wetland_change.store import OutputStore
from wetland_change.verify.wo import (
    WoLookup,
    dea_reader,
    observation_agreement,
    resolve_scene_wo,
)
from wetland_change.windows import plan_window

logger = logging.getLogger(__name__)


class SceneGridError(ValueError):
    """The scene is not on the operation grid."""


class RunIdReusedError(ValueError):
    """A run id that already has a manifest or ledger parts in the output root."""


def process_scene(
    scene: SceneItem,
    polygons: list[AoiPolygon],
    *,
    reader: RasterReader,
    water: WaterConfig,
    operation_epsg: int,
    run_id: str,
    wo_lookup: WoLookup | None = None,
    wo_reader_factory: Callable[[], RasterReader] = dea_reader,
    wo_min_clear_pixels: int = 1,
) -> list[ObservationRow]:
    """Rows for every polygon the scene covers. Raises on any guard failure.

    With `wo_lookup`, each row's `dea_wo_agreement` is the agreement with DEA
    Water Observations when DEA holds a WO item for the scene, computed by
    `verify.wo` so it equals the verification report's number. A DEA error of
    any kind is logged and leaves the column null; it never fails the scene.
    The column is also null when fewer than `wo_min_clear_pixels` pixels are
    mutually clear, the floor the report applies (`verify.min_clear_pixels`).
    """
    grid = reader.open_grid(scene.bands["green"].href)
    if grid.epsg != operation_epsg or scene.epsg != operation_epsg:
        raise SceneGridError(
            f"{scene.item_id}: grid EPSG {grid.epsg}, item EPSG {scene.epsg}, "
            f"operation EPSG {operation_epsg}"
        )
    esa = parse_product_metadata(reader.read_text(scene.product_metadata_href))
    for band in scene.bands.values():
        check_band_scaling(band, esa)
    scene_wo = (
        resolve_scene_wo(
            scene,
            union_bbox_4326(polygons),
            lookup=wo_lookup,
            reader_factory=wo_reader_factory,
        )
        if wo_lookup is not None
        else None
    )
    rows: list[ObservationRow] = []
    for polygon in polygons:
        planned = plan_window(polygon.geometry, grid)
        if planned is None:
            continue
        stack = read_stack(scene, planned, reader)
        row = summarise(polygon, scene, stack, planned, water=water, run_id=run_id)
        if scene_wo is not None:
            inside = rasterise(polygon.geometry, stack.transform, stack.shape)
            row = dataclasses.replace(
                row,
                dea_wo_agreement=observation_agreement(
                    scene,
                    stack,
                    planned,
                    inside,
                    water=water,
                    polygon_id=polygon.polygon_id,
                    wo=scene_wo,
                    scene_grid=grid,
                    min_clear_pixels=wo_min_clear_pixels,
                ),
            )
        rows.append(row)
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
    env = capture_environment()
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
        operation_epsg=cfg.aoi.operation_epsg,
        runtime=env.runtime,
        uv_lock_sha256=env.uv_lock_sha256,
        git_commit=env.git_commit,
    )


def _rejected_entries(
    discovery: Discovery, *, run_id: str, now: datetime, run_kind: str
) -> list[LedgerEntry]:
    return [
        rejected_entry(
            item_id,
            reason,
            run_id=run_id,
            processed_at=now,
            run_kind=run_kind,
            updated=discovery.rejected_updated.get(item_id),
        )
        for item_id, reason in discovery.rejected
    ]


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
    wo_lookup: WoLookup | None = None,
    wo_reader_factory: Callable[[], RasterReader] = dea_reader,
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
            wo_lookup=wo_lookup,
            wo_reader_factory=wo_reader_factory,
            wo_min_clear_pixels=cfg.verify.min_clear_pixels,
        )
        path = (
            write_observations(
                rows, store, water=cfg.water, operation_epsg=cfg.aoi.operation_epsg
            )
            if rows
            else None
        )
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


def _with_later_dates(frame: pd.DataFrame, dates: Collection[date]) -> list[date]:
    """`dates` plus every stored later date that shares a polygon and month.

    Month comes from `frame["datetime"].dt.month`, the same expression the
    history filter in `score_changes` uses, and matches across years.
    """
    month = frame["datetime"].dt.month
    chosen = frame[frame["acq_date"].isin(set(dates))]
    earliest = (
        chosen.assign(month=month)
        .groupby(["polygon_id", "month"])["acq_date"]
        .min()
        .to_dict()
    )
    keys = list(zip(frame["polygon_id"], month, strict=True))
    later = {
        acq_date
        for key, acq_date in zip(keys, frame["acq_date"], strict=True)
        if key in earliest and acq_date > earliest[key]
    }
    return sorted(set(chosen["acq_date"]) | later)


def score_changes(
    store: OutputStore,
    *,
    min_valid_fraction: float,
    water: WaterConfig,
    operation_epsg: int,
    dates: Collection[date] | None = None,
    date_range: tuple[date, date] | None = None,
    rescore_later: bool = False,
    ledger: pa.Table | None = None,
) -> ScoreResult:
    """Score stored observations by UTC acquisition date and write change files.

    Each date is scored against history of the same polygon and month from
    strictly earlier UTC dates only (ADR 0004), so a rerun over an unchanged
    store is byte-identical. A change file whose item is no longer flagged is
    deleted. `dates` and the inclusive `date_range` narrow the stored dates.
    With `rescore_later`, `dates` also takes in every stored later date that has
    a row for the same polygon and month as one of them (any year), because a
    newly stored earlier observation changes those dates' baselines. The
    `date_range` narrowing applies after that widening.

    With `ledger` and `dates`, an observation file is not read when the ledger
    shows that all its rows fall in UTC months outside the months of `dates`.
    Both the later-date widening and the history filter match on polygon and
    calendar month, so those months are closed under them. A file with no
    ledger row (a test fixture or an interrupted attempt) is always read.
    `dates=None` reads every file, and `date_range` alone excludes nothing.

    `water` and `operation_epsg` go into each change file's footer, so the
    water settings recorded are those of the config at scoring time.
    """
    exclude: set[str] = set()
    if ledger is not None and dates is not None:
        months = {d.month for d in dates}
        exclude = {
            path
            for path, found in observation_months(ledger).items()
            if found and not found & months
        }
    observations = read_observations(store, exclude=exclude)
    frame = pd.DataFrame(observations.drop(columns="geometry"))
    geometry_by_polygon = dict(
        zip(observations["polygon_id"], observations.geometry, strict=True)
    )
    frame["acq_date"] = frame["datetime"].dt.tz_convert(UTC).dt.date
    wanted = sorted(set(frame["acq_date"]))
    if dates is not None:
        if rescore_later:
            dates = _with_later_dates(frame, dates)
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
            written.add(
                write_changes(
                    group,
                    geometries,
                    store,
                    water=water,
                    operation_epsg=operation_epsg,
                )
            )
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


def discovery_created_from(
    stac: StacConfig, *, before: datetime | None, now: datetime
) -> datetime:
    """Lower `created` bound for a daily run: the watermark less the overlap, or
    the initial lookback before `now` when there is no daily watermark."""
    if before is not None:
        return before - timedelta(days=stac.watermark_overlap_days)
    return now - timedelta(days=stac.initial_lookback_days)


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
    build_catalogue: bool = True,
    wo_lookup: WoLookup | None = None,
    wo_reader_factory: Callable[[], RasterReader] = dea_reader,
) -> RunManifest:
    """Process everything new since the ledger watermark, or since the initial
    lookback when the ledger has no daily rows. Never aborts on a single scene;
    failures go to the ledger and are retried next run. The ledger is
    checkpointed after every scene, so an interrupted run resumes after its
    last finished scene.

    The ledger is listed and read once; the final table is that read plus the
    entries this run wrote, and scoring, the catalogue and compaction use it.

    A daily run that raised after checkpointing scenes leaves ledger rows and
    no `runs/<run_id>.json`. This run finds such runs from the ledger as read
    at its start and a single listing of `runs/`, adds their dates to the one
    `score_changes` call after the scene loop, and writes a manifest for each
    (`recovered_by` set, skipped tallies and watermarks empty) before its own.
    Backfill rows are never recovered. Scoring runs after the loop so new
    scenes are still processed and checkpointed when an old date cannot be
    scored.
    With `wo_lookup`, each observation's `dea_wo_agreement` is filled at
    processing time from DEA Water Observations (`process_scene`); DEA errors
    leave it null and never fail a scene.
    `build_catalogue=False` skips the catalogue build. Compaction runs last and
    a failure there is logged, not raised.
    """
    ensure_publishable_base_url(cfg.catalogue.base_url, store)
    run_id = new_run_id(now)
    ledger, paths = read_ledger_parts(store)
    _refuse_reused_run_id(store, run_id, ledger=ledger, paths=paths)
    unfinished = unfinished_runs(ledger, _finished_run_ids(store))
    before = watermark(ledger)
    created_from = discovery_created_from(cfg.stac, before=before, now=now)
    if before is not None:
        logger.info(
            "discovery bound: watermark less overlap, created >= %s", created_from
        )
    else:
        logger.info(
            "discovery bound: no daily watermark, %d day lookback, created >= %s",
            cfg.stac.initial_lookback_days,
            created_from,
        )
    discovery = discover(
        client,
        cfg.stac,
        bbox=union_bbox_4326(polygons),
        polygons_4326=[p.geometry_4326 for p in polygons],
        created_from=created_from,
        seen=seen_keys(ledger) | exhausted_keys(ledger),
        rejected_seen=rejected_keys(ledger),
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
    next_part = 0
    new_entries: list[LedgerEntry] = []
    if discovery.rejected:
        rejected = _rejected_entries(
            discovery, run_id=run_id, now=now, run_kind=RUN_KIND_RUN
        )
        manifest.ledger_files += write_ledger(
            rejected, store, run_id=run_id, part=next_part
        )
        new_entries += rejected
        next_part += 1
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
            wo_lookup=wo_lookup,
            wo_reader_factory=wo_reader_factory,
        )
        manifest.ledger_files += write_ledger(
            [entry], store, run_id=run_id, part=next_part
        )
        new_entries.append(entry)
        next_part += 1
        if path is not None and entry.datetime is not None:
            written_dates.add(entry.datetime.astimezone(UTC).date())
        _tally(manifest, entry, path)
    final = ledger_with(ledger, new_entries)
    manifest.watermark_after = watermark(final)
    manifest.exhausted_items = exhausted_ids(final)
    manifest.exhausted = len(manifest.exhausted_items)
    score_dates = set(written_dates)
    for crashed_id, rows in unfinished.items():
        crashed_dates = scored_dates(rows)
        logger.info(
            "run %s has ledger rows and no manifest; finishing it (%d dates to score)",
            crashed_id,
            len(crashed_dates),
        )
        score_dates |= crashed_dates
    scored: ScoreResult | None = None
    if score_dates:
        scored = score_changes(
            store,
            min_valid_fraction=cfg.water.min_valid_fraction,
            water=cfg.water,
            operation_epsg=cfg.aoi.operation_epsg,
            dates=score_dates,
            rescore_later=True,
            ledger=final,
        )
        manifest.change_rows = scored.rows
        manifest.change_files = scored.files
        manifest.change_files_removed = scored.removed
    for crashed_id, rows in unfinished.items():
        write_manifest(
            _recovered_manifest(manifest, crashed_id, rows, now, scored, paths),
            store,
        )
    manifest.recovered_runs = sorted(unfinished)
    manifest.finished_at = now
    write_manifest(manifest, store)
    if build_catalogue:
        build_and_write(store, base_url=cfg.catalogue.base_url, ledger=final)
    _compact_after_run(store, final, paths, manifest)
    return manifest


def _finished_run_ids(store: OutputStore) -> set[str]:
    """Run ids that have a manifest under `runs/` (empty before the first run)."""
    return {Path(p).stem for p in store.list_files("runs") if p.endswith(".json")}


def _recovered_manifest(
    current: RunManifest,
    run_id: str,
    rows: pd.DataFrame,
    now: datetime,
    scored: ScoreResult | None,
    paths: Sequence[str],
) -> RunManifest:
    """Manifest of a daily run that raised before writing its own.

    Only what the ledger knows is filled in. skipped_seen, skipped_filter and
    both watermarks, package_version, config_sha256, operation_epsg, runtime,
    uv_lock_sha256 and git_commit stay empty, because only the crashed process
    knew them; `recovered_by` marks the manifest. Scoring fields come from the
    combined scoring result of the run that recovered it.
    """
    status = rows["status"]
    processed = int((status == "succeeded").sum())
    failed = int((status == "failed").sum())
    succeeded = rows[(status == "succeeded") & rows["observation_path"].notna()]
    return RunManifest(
        run_id=run_id,
        started_at=rows["processed_at"].min().to_pydatetime(),
        finished_at=now,
        package_version=None,
        config_sha256=None,
        endpoint=current.endpoint,
        collection=current.collection,
        watermark_before=None,
        watermark_after=None,
        discovered=processed + failed,
        processed=processed,
        failed=failed,
        rejected=int((status == "rejected").sum()),
        observation_files=sorted(str(p) for p in succeeded["observation_path"]),
        ledger_files=[p for p in paths if f"ledger_{run_id}" in Path(p).name],
        change_rows=scored.rows if scored else 0,
        change_files=list(scored.files) if scored else [],
        change_files_removed=list(scored.removed) if scored else [],
        kind=RUN_KIND_RUN,
        output_root_override=current.output_root_override,
        recovered_by=current.run_id,
    )


def _compact_after_run(
    store: OutputStore, final: pa.Table, paths: Sequence[str], manifest: RunManifest
) -> None:
    """Merge the ledger parts when there are enough; a failure is logged only.

    The run's work is already written, and compaction keeps every row, so a
    failed merge only leaves more parts for the next run to merge.
    """
    try:
        compact_ledger(
            store,
            final,
            [*paths, *manifest.ledger_files],
            run_id=manifest.run_id,
            min_parts=COMPACT_MIN_PARTS,
        )
    except Exception:
        logger.exception(
            "ledger compaction failed; run %s is unaffected", manifest.run_id
        )


def _refuse_reused_run_id(
    store: OutputStore, run_id: str, *, ledger: pa.Table, paths: Sequence[str]
) -> None:
    """Part numbering restarts at 0, so a run id already on disk would have its
    manifest or ledger parts overwritten, losing the interrupted run's rows.

    Compaction removes the part names of an interrupted run that has no
    manifest, so the run id is also looked up in the ledger table.
    """
    prefix = f"ledger_{run_id}_"
    reused = (
        store.exists(manifest_path(run_id))
        or any(Path(p).name.startswith(prefix) for p in paths)
        or run_id in set(ledger["run_id"].to_pylist())
    )
    if reused:
        raise RunIdReusedError(
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

    Backfill rows leave `dea_wo_agreement` null: backfill dates are mostly past
    DEA's three month retention of the provisional WO product, so no lookup is
    made.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("backfill start and end must be timezone-aware")
    if start > end:
        raise ValueError(f"backfill start {start} is after end {end}")
    ensure_publishable_base_url(cfg.catalogue.base_url, store)
    run_id = new_run_id(now)
    ledger, paths = read_ledger_parts(store)
    _refuse_reused_run_id(store, run_id, ledger=ledger, paths=paths)
    before = watermark(ledger)
    discovery = discover(
        client,
        cfg.stac,
        bbox=union_bbox_4326(polygons),
        polygons_4326=[p.geometry_4326 for p in polygons],
        created_from=None,
        seen=seen_keys(ledger) | exhausted_keys(ledger),
        rejected_seen=rejected_keys(ledger),
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
    new_entries: list[LedgerEntry] = []
    if discovery.rejected:
        rejected = _rejected_entries(
            discovery, run_id=run_id, now=now, run_kind=RUN_KIND_BACKFILL
        )
        manifest.ledger_files += write_ledger(
            rejected, store, run_id=run_id, part=next_part
        )
        new_entries += rejected
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
        new_entries.append(entry)
        next_part += 1
    final = ledger_with(ledger, new_entries)
    manifest.watermark_after = watermark(final)
    manifest.exhausted_items = exhausted_ids(final)
    manifest.exhausted = len(manifest.exhausted_items)
    manifest.finished_at = now
    write_manifest(manifest, store)
    _compact_after_run(store, final, paths, manifest)
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
    ensure_publishable_base_url(cfg.catalogue.base_url, store)
    run_id = new_run_id(now)
    if store.exists(manifest_path(run_id)):
        raise ValueError(
            f"run id {run_id} already has a manifest in the output root; "
            "rerun with a later --now"
        )
    scored = score_changes(
        store,
        min_valid_fraction=cfg.water.min_valid_fraction,
        water=cfg.water,
        operation_epsg=cfg.aoi.operation_epsg,
        date_range=(start.astimezone(UTC).date(), end.astimezone(UTC).date()),
    )
    env = capture_environment()
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
        operation_epsg=cfg.aoi.operation_epsg,
        runtime=env.runtime,
        uv_lock_sha256=env.uv_lock_sha256,
        git_commit=env.git_commit,
    )
    write_manifest(manifest, store)
    return manifest


def requeue_once(
    cfg: PipelineConfig,
    *,
    item_ids: Sequence[str],
    all_exhausted: bool,
    store: OutputStore,
    now: datetime,
    config_path: Path,
    output_root_override: str | None = None,
) -> RunManifest:
    """Append fresh-attempt ledger rows for exhausted items and write a manifest.

    The next daily run retries them with a full set of attempts. Existing
    ledger files are not edited, and no catalogue is built.
    """
    if all_exhausted == bool(item_ids):
        raise ValueError("give either item ids or --all, not both or neither")
    run_id = new_run_id(now)
    ledger, paths = read_ledger_parts(store)
    _refuse_reused_run_id(store, run_id, ledger=ledger, paths=paths)
    selected = exhausted_ids(ledger) if all_exhausted else sorted(set(item_ids))
    if not selected:
        raise ValueError("nothing to requeue: no item has exhausted its attempts")
    entries = requeue_entries(ledger, selected, run_id=run_id, processed_at=now)
    ledger_files = write_ledger(entries, store, run_id=run_id, part=0)
    remaining = exhausted_ids(ledger_with(ledger, entries))
    env = capture_environment()
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
        ledger_files=ledger_files,
        kind=KIND_REQUEUE,
        output_root_override=output_root_override,
        exhausted=len(remaining),
        exhausted_items=remaining,
        requeued_items=[entry.item_id for entry in entries],
        operation_epsg=cfg.aoi.operation_epsg,
        runtime=env.runtime,
        uv_lock_sha256=env.uv_lock_sha256,
        git_commit=env.git_commit,
    )
    write_manifest(manifest, store)
    return manifest
