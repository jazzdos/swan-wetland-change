"""Run every Milestone 1 check over the scenes of one run."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
from rasterio.windows import Window

from wetland_change.aoi import AoiPolygon, union_bbox_4326
from wetland_change.catalogue.item import SceneItem, parse_item, parse_timestamp
from wetland_change.catalogue.search import StacClient, open_client
from wetland_change.config import PipelineConfig
from wetland_change.ledger import RUN_KIND_RUN, latest_entries, read_ledger
from wetland_change.manifest import manifest_path
from wetland_change.outputs.geoparquet import observation_path
from wetland_change.raster.read import (
    BandStack,
    RasterioReader,
    RasterReader,
    read_stack,
)
from wetland_change.stats import rasterise
from wetland_change.store import OutputStore
from wetland_change.verify.checks import Check, write_report
from wetland_change.verify.copernicus import (
    CDSE_STAC,
    CHECK_NAME,
    discovery_checks,
    run_window,
)
from wetland_change.verify.ndvi import (
    CHECK_NAME as NDVI_CHECK,
)
from wetland_change.verify.ndvi import (
    CORRELATION_CHECK_NAME as NDVI_CORRELATION_CHECK,
)
from wetland_change.verify.ndvi import (
    NbartItem,
    find_nbart_item,
    ndvi_correlation_check,
    ndvi_scene_check,
)
from wetland_change.verify.pixels import pixel_check
from wetland_change.verify.scaling import scaling_check
from wetland_change.verify.scl import scl_checks
from wetland_change.verify.waterbodies import (
    CHECK_NAME as WATERBODIES_CHECK,
)
from wetland_change.verify.waterbodies import (
    SeriesLoader,
    fetch_series,
    read_observations,
    waterbody_checks,
)
from wetland_change.verify.wo import (
    WoLookup,
    dea_reader,
    find_wo_href,
    pooled_wet_area_check,
    wo_check,
)
from wetland_change.windows import PlannedWindow, plan_window

logger = logging.getLogger(__name__)


def _history_paths(ledger: pa.Table, *, newest: datetime) -> set[str]:
    """Observation files of every succeeded item up to and including `newest`,
    so re-verifying an older run is repeatable after later passes are stored."""
    latest = latest_entries(ledger)
    if latest.empty:
        return set()
    stamp = pd.Timestamp(newest)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp
    stored = latest[
        (latest["status"] == "succeeded")
        & latest["observation_path"].notna()
        & (latest["datetime"] <= stamp)
    ]
    return {str(p) for p in stored["observation_path"]}


def scenes_for_run(
    cfg: PipelineConfig,
    store: OutputStore,
    run_id: str,
    *,
    ledger: pa.Table | None = None,
) -> list[SceneItem]:
    """Succeeded scenes of `run_id`; reads the ledger only when none is given."""
    frame = (read_ledger(store) if ledger is None else ledger).to_pandas()
    rows = frame[(frame["run_id"] == run_id) & (frame["status"] == "succeeded")]
    return [
        parse_item(
            json.loads(source),
            collection=cfg.stac.collection,
            required_assets=cfg.stac.required_assets,
        )
        for source in rows["source_item"]
    ]


class ManifestReadError(OSError):
    """A run manifest exists but could not be read (permissions, credentials, I/O)."""


def read_manifest_bytes(store: OutputStore, path: str) -> bytes:
    """Read one run manifest, raising ManifestReadError naming the path."""
    try:
        return store.read_bytes(path)
    except OSError as exc:
        raise ManifestReadError(
            f"cannot read run manifest {path} under {store.uri}: {exc}"
        ) from exc


def latest_run_id(store: OutputStore) -> str | None:
    """Newest daily run (kind run) that processed at least one scene.

    Backfill chunks and no-op runs are skipped. A manifest without a kind
    counts as a daily run.

    A manifest that is not valid JSON is skipped. A manifest that cannot be
    read raises ManifestReadError, so an access failure never falls back to an
    older run.
    """
    runs = sorted(p for p in store.list_files("runs") if p.endswith(".json"))
    for path in reversed(runs):
        raw = read_manifest_bytes(store, path)
        try:
            manifest = json.loads(raw)
            processed = int(manifest.get("processed", 0))
            kind = manifest.get("kind", RUN_KIND_RUN)
        except (ValueError, TypeError):
            continue
        if kind == RUN_KIND_RUN and processed > 0:
            return path.rsplit("/", 1)[-1].removesuffix(".json")
    return None


def run_exists(store: OutputStore, run_id: str) -> bool:
    return store.exists(manifest_path(run_id))


def _error_check(name: str, exc: Exception, **detail: object) -> Check:
    logger.warning("%s failed: %s: %s", name, type(exc).__name__, exc)
    return Check(
        name,
        None,
        None,
        None,
        "check did not run",
        {**detail, "error": f"{type(exc).__name__}: {exc}"},
    )


def _guard(name: str, func: Callable[[], list[Check]], **detail: object) -> list[Check]:
    """Run one check; an exception becomes a skipped check carrying the error."""
    try:
        return func()
    except Exception as exc:
        return [_error_check(name, exc, **detail)]


PixelChecker = Callable[[SceneItem, RasterReader, Window], Check]
NbartLookup = Callable[[SceneItem, tuple[float, float, float, float]], NbartItem | None]


def stored_ndvi(store: OutputStore, scene: SceneItem) -> dict[str, float]:
    """Pipeline ndvi_median per polygon for one scene; {} when it has no file."""
    path = observation_path(scene.year, scene.tile, scene.item_id)
    if not store.exists(path):
        return {}
    frame = pd.read_parquet(
        BytesIO(store.read_bytes(path)), columns=["polygon_id", "ndvi_median"]
    )
    return {
        str(pid): float(value)
        for pid, value in zip(frame["polygon_id"], frame["ndvi_median"], strict=True)
    }


def _verify_scene(
    cfg: PipelineConfig,
    scene: SceneItem,
    reader: RasterReader,
    polygons: list[AoiPolygon],
    wo_lookup: WoLookup,
    wo_reader_factory: Callable[[], RasterReader],
    pixel_checker: PixelChecker,
    nbart_lookup: NbartLookup,
    nbart_reader_factory: Callable[[], RasterReader],
    store: OutputStore,
) -> list[Check]:
    item = scene.item_id
    checks: list[Check] = []
    checks.extend(
        _guard(
            "reflectance_scaling",
            lambda: [
                scaling_check(scene, reader.read_text(scene.product_metadata_href))
            ],
            item=item,
        )
    )
    checks.extend(_guard("scl_shares", lambda: scl_checks(scene, reader), item=item))
    try:
        grid = reader.open_grid(scene.bands["green"].href)
    except Exception as exc:
        return [*checks, _error_check("scene_grid", exc, item=item)]
    planned_first: PlannedWindow | None = None
    wo_href: str | None = None
    wo_reader: RasterReader | None = None
    wo_resolved = False
    nbart: NbartItem | None = None
    nbart_reader: RasterReader | None = None
    stored: dict[str, float] = {}
    nbart_resolved = False
    for polygon in polygons:
        planned = plan_window(polygon.geometry, grid)
        if planned is None:
            continue
        planned_first = planned_first or planned
        if not wo_resolved:
            wo_resolved = True
            try:
                wo_href = wo_lookup(scene, union_bbox_4326(polygons))
                wo_reader = wo_reader_factory() if wo_href else None
            except Exception as exc:
                checks.append(_error_check("water_vs_dea_s2_wo", exc, item=item))
                wo_href = None
            else:
                if wo_href is None:
                    checks.append(
                        Check(
                            "water_vs_dea_s2_wo",
                            None,
                            None,
                            None,
                            "DEA STAC",
                            {"item": item, "reason": "no DEA WO scene found"},
                        )
                    )
        if not nbart_resolved:
            nbart_resolved = True
            try:
                nbart = nbart_lookup(scene, union_bbox_4326(polygons))
                if nbart is not None:
                    stored = stored_ndvi(store, scene)
                    nbart_reader = nbart_reader_factory()
            except Exception as exc:
                checks.append(_error_check(NDVI_CHECK, exc, item=item))
                nbart = None
            else:
                if nbart is None:
                    checks.append(
                        Check(
                            NDVI_CHECK,
                            None,
                            None,
                            None,
                            "DEA STAC",
                            {
                                "item": item,
                                "reason": "no DEA ARD item for this acquisition",
                            },
                        )
                    )
        # One stack read and rasterisation per polygon, shared by WO and NDVI.
        loaded: list[tuple[BandStack, np.ndarray]] = []

        def _load(
            polygon: AoiPolygon = polygon,
            planned: PlannedWindow = planned,
            loaded: list[tuple[BandStack, np.ndarray]] = loaded,
        ) -> tuple[BandStack, np.ndarray]:
            if not loaded:
                stack = read_stack(scene, planned, reader)
                inside = rasterise(polygon.geometry, stack.transform, stack.shape)
                loaded.append((stack, inside))
            return loaded[0]

        if wo_href is not None and wo_reader is not None:

            def _wo(
                polygon: AoiPolygon = polygon,
                planned: PlannedWindow = planned,
                href: str = wo_href,
                dea: RasterReader = wo_reader,
                load: Callable[[], tuple[BandStack, np.ndarray]] = _load,
            ) -> list[Check]:
                stack, inside = load()
                result = wo_check(
                    scene,
                    stack,
                    planned,
                    inside,
                    water=cfg.water,
                    wo_href=href,
                    reader=dea,
                    scene_grid=grid,
                    polygon_id=polygon.polygon_id,
                    min_clear_pixels=cfg.verify.min_clear_pixels,
                )
                return [result]

            checks.extend(
                _guard(
                    "water_vs_dea_s2_wo", _wo, item=item, polygon_id=polygon.polygon_id
                )
            )
        if nbart is not None and nbart_reader is not None:
            if polygon.polygon_id not in stored:
                checks.append(
                    Check(
                        NDVI_CHECK,
                        None,
                        None,
                        None,
                        nbart.reference,
                        {
                            "item": item,
                            "polygon_id": polygon.polygon_id,
                            "reason": "no observation row for this polygon",
                        },
                    )
                )
                continue

            def _ndvi(
                polygon: AoiPolygon = polygon,
                planned: PlannedWindow = planned,
                item_dea: NbartItem = nbart,
                dea: RasterReader = nbart_reader,
                measured: float = stored[polygon.polygon_id],
                load: Callable[[], tuple[BandStack, np.ndarray]] = _load,
            ) -> list[Check]:
                stack, inside = load()
                result = ndvi_scene_check(
                    scene,
                    stack,
                    planned,
                    inside,
                    measured_median=measured,
                    nbart=item_dea,
                    reader=dea,
                    scene_grid=grid,
                    expected_epsg=cfg.aoi.operation_epsg,
                    min_pixels=cfg.verify.min_clear_pixels,
                )
                result.detail["polygon_id"] = polygon.polygon_id
                return [result]

            checks.extend(
                _guard(NDVI_CHECK, _ndvi, item=item, polygon_id=polygon.polygon_id)
            )
    if planned_first is not None:
        window = planned_first.window10
        checks.extend(
            _guard(
                "pixels_vs_planetary_computer",
                lambda: [pixel_checker(scene, reader, window)],
                item=item,
            )
        )
    return checks


def verify_run(
    cfg: PipelineConfig,
    store: OutputStore,
    run_id: str,
    *,
    polygons: list[AoiPolygon],
    reader: RasterReader | None = None,
    wo_lookup: WoLookup = find_wo_href,
    wo_reader_factory: Callable[[], RasterReader] = dea_reader,
    pixel_checker: PixelChecker = pixel_check,
    nbart_lookup: NbartLookup | None = None,
    nbart_reader_factory: Callable[[], RasterReader] = dea_reader,
    docs_dir: Path | None = Path("docs/research"),
    es_client: StacClient | None = None,
    cdse_client: StacClient | None = None,
    waterbody_polygons: list[AoiPolygon] | None = None,
    waterbodies_loader: SeriesLoader = fetch_series,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[Check]:
    reader = reader or RasterioReader()
    checks: list[Check] = []
    ledger = read_ledger(store)
    scenes = scenes_for_run(cfg, store, run_id, ledger=ledger)
    lookup = nbart_lookup if nbart_lookup is not None else find_nbart_item
    for scene in scenes:
        checks.extend(
            _verify_scene(
                cfg,
                scene,
                reader,
                polygons,
                wo_lookup,
                wo_reader_factory,
                pixel_checker,
                lookup,
                nbart_reader_factory,
                store,
            )
        )
    # One run-level wet area gate over every scored live water check
    # (docs/decisions/0008-exit-code-for-live-water-check-failures.md).
    pooled = pooled_wet_area_check(checks)
    if pooled is not None:
        checks.append(pooled)
    listed_at = clock()
    if scenes:
        scored = [
            c
            for c in checks
            if c.name == NDVI_CHECK
            and c.passed is not None
            and "ndvi_median" in c.detail
            and "dea_ndvi_median" in c.detail
        ]
        checks.extend(
            _guard(
                NDVI_CORRELATION_CHECK,
                lambda: [
                    ndvi_correlation_check(
                        [c.detail["ndvi_median"] for c in scored],
                        [c.detail["dea_ndvi_median"] for c in scored],
                        detail={
                            "run_id": run_id,
                            "rows": [
                                [c.detail.get("item"), c.detail.get("polygon_id")]
                                for c in scored
                            ],
                        },
                    )
                ],
                run_id=run_id,
            )
        )

        def _discovery() -> list[Check]:
            manifest = json.loads(store.read_bytes(manifest_path(run_id)))
            started_at = parse_timestamp(manifest["started_at"])
            start, end = run_window([s.datetime for s in scenes], started_at)
            return discovery_checks(
                es_client or open_client(cfg.stac.endpoint),
                cdse_client or open_client(CDSE_STAC),
                cfg.stac,
                bbox=union_bbox_4326(polygons),
                polygons_4326=[p.geometry_4326 for p in polygons],
                start=start,
                end=end,
                now=listed_at,
            )

        checks.extend(_guard(CHECK_NAME, _discovery, run_id=run_id))

        def _waterbodies() -> list[Check]:
            lakes = (
                waterbody_polygons
                if waterbody_polygons is not None
                else [p for p in polygons if p.layer == "dea_waterbody"]
            )
            if not lakes:
                logger.info("no DEA waterbody polygons; skipping %s", WATERBODIES_CHECK)
                return []
            if not scenes:
                return []
            run_paths = {observation_path(s.year, s.tile, s.item_id) for s in scenes}
            history_paths = _history_paths(
                ledger,
                newest=max(s.datetime for s in scenes),
            )
            # One listing, not one exists call per path: the history holds every
            # stored pass.
            stored = set(store.list_files("observations"))
            paths = sorted((run_paths | history_paths) & stored)
            history = read_observations(store, paths)
            run_ids = {s.item_id for s in scenes}
            run_rows = history[history["item_id"].isin(run_ids)]
            # A run without lake rows still scores the stored history, so the
            # Spearman verdict does not depend on which tiles the run touched.
            if history.empty:
                return []
            return waterbody_checks(
                run_rows,
                waterbodies_loader,
                lakes,
                cfg=cfg.verify.waterbodies,
                min_valid_fraction=cfg.water.min_valid_fraction,
                history=history,
            )

        checks.extend(_guard(WATERBODIES_CHECK, _waterbodies, run_id=run_id))
    write_report(
        checks,
        store=store,
        run_id=run_id,
        docs_dir=docs_dir,
        generated_at=listed_at,
    )
    return checks
