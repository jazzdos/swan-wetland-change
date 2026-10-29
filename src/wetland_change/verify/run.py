"""Run every Milestone 1 check over the scenes of one run."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from rasterio.windows import Window

from wetland_change.aoi import AoiPolygon, union_bbox_4326
from wetland_change.catalogue.item import SceneItem, parse_item
from wetland_change.config import PipelineConfig
from wetland_change.ledger import read_ledger
from wetland_change.manifest import manifest_path
from wetland_change.raster.read import RasterioReader, RasterReader, read_stack
from wetland_change.stats import rasterise
from wetland_change.store import OutputStore
from wetland_change.verify.checks import Check, write_report
from wetland_change.verify.pixels import pixel_check
from wetland_change.verify.scaling import scaling_check
from wetland_change.verify.scl import scl_checks
from wetland_change.verify.wo import dea_reader, find_wo_href, wo_check
from wetland_change.windows import PlannedWindow, plan_window

logger = logging.getLogger(__name__)


def scenes_for_run(
    cfg: PipelineConfig, store: OutputStore, run_id: str
) -> list[SceneItem]:
    frame = read_ledger(store).to_pandas()
    rows = frame[(frame["run_id"] == run_id) & (frame["status"] == "succeeded")]
    return [
        parse_item(
            json.loads(source),
            collection=cfg.stac.collection,
            required_assets=cfg.stac.required_assets,
        )
        for source in rows["source_item"]
    ]


def latest_run_id(store: OutputStore) -> str | None:
    """Newest run that processed at least one scene (no-op runs are skipped)."""
    runs = sorted(p for p in store.list_files("runs") if p.endswith(".json"))
    for path in reversed(runs):
        try:
            processed = int(json.loads(store.read_bytes(path)).get("processed", 0))
        except (ValueError, TypeError, OSError):
            continue
        if processed > 0:
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


WoLookup = Callable[[SceneItem, tuple[float, float, float, float]], str | None]
PixelChecker = Callable[[SceneItem, RasterReader, Window], Check]


def _verify_scene(
    cfg: PipelineConfig,
    scene: SceneItem,
    reader: RasterReader,
    polygons: list[AoiPolygon],
    wo_lookup: WoLookup,
    wo_reader_factory: Callable[[], RasterReader],
    pixel_checker: PixelChecker,
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
        if wo_href is None or wo_reader is None:
            continue

        def _wo(
            polygon: AoiPolygon = polygon,
            planned: PlannedWindow = planned,
            href: str = wo_href,
            dea: RasterReader = wo_reader,
        ) -> list[Check]:
            stack = read_stack(scene, planned, reader)
            inside = rasterise(polygon.geometry, stack.transform, stack.shape)
            result = wo_check(
                scene,
                stack,
                planned,
                inside,
                water=cfg.water,
                wo_href=href,
                reader=dea,
                scene_grid=grid,
            )
            result.detail["polygon_id"] = polygon.polygon_id
            return [result]

        checks.extend(
            _guard("water_vs_dea_s2_wo", _wo, item=item, polygon_id=polygon.polygon_id)
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
    docs_dir: Path | None = Path("docs/research"),
) -> list[Check]:
    reader = reader or RasterioReader()
    checks: list[Check] = []
    for scene in scenes_for_run(cfg, store, run_id):
        checks.extend(
            _verify_scene(
                cfg,
                scene,
                reader,
                polygons,
                wo_lookup,
                wo_reader_factory,
                pixel_checker,
            )
        )
    write_report(
        checks,
        store=store,
        run_id=run_id,
        docs_dir=docs_dir,
        generated_at=datetime.now(UTC),
    )
    return checks
