"""Command line: discover, run, verify."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from wetland_change.aoi import AoiPolygon, load_ramsar, union_bbox_4326
from wetland_change.catalogue.search import discover as discover_items
from wetland_change.catalogue.search import open_client
from wetland_change.config import PipelineConfig, load_config
from wetland_change.ledger import (
    exhausted_keys,
    read_ledger,
    retry_ids,
    seen_keys,
    watermark,
)
from wetland_change.pipeline import run_once
from wetland_change.raster.read import RasterioReader
from wetland_change.store import OutputStore

app = typer.Typer(add_completion=False, no_args_is_help=True)

ConfigOption = Annotated[Path, typer.Option("--config", help="Pipeline TOML")]


def _load(config: Path) -> tuple[PipelineConfig, list[AoiPolygon]]:
    cfg = load_config(config)
    polygons = load_ramsar(
        cfg.aoi.ramsar_path,
        site_prefixes=cfg.aoi.site_prefixes,
        operation_epsg=cfg.aoi.operation_epsg,
    )
    if not polygons:
        raise typer.BadParameter("no AOI polygons matched; run scripts/fetch_aoi.py")
    return cfg, polygons


@app.callback()
def _main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)


@app.command()
def discover(config: ConfigOption = Path("config/pipeline.toml")) -> None:
    """List scenes the next run would process, without reading any raster."""
    cfg, polygons = _load(config)
    ledger = read_ledger(OutputStore(cfg.output.root))
    before = watermark(ledger)
    result = discover_items(
        open_client(cfg.stac.endpoint),
        cfg.stac,
        bbox=union_bbox_4326(polygons),
        polygons_4326=[p.geometry_4326 for p in polygons],
        created_from=(
            before - timedelta(days=cfg.stac.watermark_overlap_days) if before else None
        ),
        seen=seen_keys(ledger) | exhausted_keys(ledger),
        retry_ids=retry_ids(ledger),
    )
    for scene in result.scenes:
        typer.echo(
            f"{scene.item_id}\t{scene.tile}\t{scene.cloud_cover:.2f}\t{scene.created.isoformat()}"
        )
    typer.echo(
        f"{len(result.scenes)} to process, {result.skipped_seen} seen, "
        f"{result.skipped_filter} filtered, {len(result.rejected)} rejected"
    )


@app.command()
def run(
    config: ConfigOption = Path("config/pipeline.toml"),
    now: Annotated[datetime | None, typer.Option(help="Run time, UTC")] = None,
) -> None:
    """One incremental run against the configured output root."""
    cfg, polygons = _load(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    manifest = run_once(
        cfg,
        client=open_client(cfg.stac.endpoint),
        reader=RasterioReader(),
        store=OutputStore(cfg.output.root),
        polygons=polygons,
        now=when,
        config_path=config,
    )
    typer.echo(manifest.to_json())
    if manifest.failed:
        raise typer.Exit(code=2)


@app.command()
def verify(
    config: ConfigOption = Path("config/pipeline.toml"),
    run_id: Annotated[
        str | None, typer.Option(help="Defaults to the latest run")
    ] = None,
) -> None:
    """Score the known-good checks for one run and write the report."""
    from wetland_change.verify.run import latest_run_id, run_exists, verify_run

    cfg, polygons = _load(config)
    store = OutputStore(cfg.output.root)
    target = run_id or latest_run_id(store)
    if target is None:
        raise typer.BadParameter("no run with processed scenes in the output root")
    if not run_exists(store, target):
        raise typer.BadParameter(f"no run {target!r} in the output root")
    checks = verify_run(cfg, store, target, polygons=polygons)
    for check in checks:
        status = (
            "skip" if check.passed is None else ("pass" if check.passed else "FAIL")
        )
        typer.echo(f"{status}\t{check.name}\t{check.measured}\t{check.reference}")
    if any(check.passed is False for check in checks):
        raise typer.Exit(code=3)
    if not any(check.passed is not None for check in checks):
        typer.echo(f"no checks were scored for run {target}", err=True)
        raise typer.Exit(code=4)
