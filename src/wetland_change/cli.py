"""Command line: discover, run, backfill, score, verify, freshness, build-catalogue."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from wetland_change.aoi import (
    AoiPolygon,
    load_ramsar,
    load_waterbodies,
    union_bbox_4326,
)
from wetland_change.catalogue.search import StacClient, open_client
from wetland_change.catalogue.search import discover as discover_items
from wetland_change.config import PipelineConfig, load_config
from wetland_change.ledger import (
    exhausted_keys,
    read_ledger,
    retry_ids,
    seen_keys,
    watermark,
)
from wetland_change.pipeline import (
    backfill_once,
    discovery_created_from,
    run_once,
    score_once,
)
from wetland_change.raster.read import RasterioReader
from wetland_change.stac import build_and_write
from wetland_change.store import OutputStore

app = typer.Typer(add_completion=False, no_args_is_help=True)

ConfigOption = Annotated[Path, typer.Option("--config", help="Pipeline TOML")]
OutputRootOption = Annotated[
    str | None,
    typer.Option(
        "--output-root",
        help="Output root path or URI; overrides output.root in the config file",
    ),
]
NOW_HELP = (
    "Run time as YYYY-MM-DD[THH:MM:SS]. A value without a zone is read as local "
    "time on this machine, then converted to UTC. Omitted means the current time."
)


def _store(cfg: PipelineConfig, output_root: str | None) -> OutputStore:
    return OutputStore(output_root or cfg.output.root)


def _load(config: Path) -> tuple[PipelineConfig, list[AoiPolygon]]:
    cfg = load_config(config)
    polygons = load_ramsar(
        cfg.aoi.ramsar_path,
        site_prefixes=cfg.aoi.site_prefixes,
        operation_epsg=cfg.aoi.operation_epsg,
    )
    if not polygons:
        raise typer.BadParameter("no AOI polygons matched; run scripts/fetch_aoi.py")
    # DEA Waterbodies lakes are the verification unit (water_vs_dea_waterbodies).
    if cfg.aoi.waterbodies_path.exists():
        polygons = [
            *polygons,
            *load_waterbodies(
                cfg.aoi.waterbodies_path, operation_epsg=cfg.aoi.operation_epsg
            ),
        ]
    else:
        logging.getLogger(__name__).warning(
            "%s not found; DEA Waterbodies check skipped (run scripts/fetch_aoi.py)",
            cfg.aoi.waterbodies_path,
        )
    return cfg, polygons


@app.callback()
def _main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)


@app.command()
def discover(
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
) -> None:
    """List scenes the next run would process, without reading any raster."""
    cfg, polygons = _load(config)
    ledger = read_ledger(_store(cfg, output_root))
    before = watermark(ledger)
    result = discover_items(
        open_client(cfg.stac.endpoint),
        cfg.stac,
        bbox=union_bbox_4326(polygons),
        polygons_4326=[p.geometry_4326 for p in polygons],
        created_from=discovery_created_from(
            cfg.stac, before=before, now=datetime.now(UTC)
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
    output_root: OutputRootOption = None,
    now: Annotated[datetime | None, typer.Option(help=NOW_HELP)] = None,
) -> None:
    """One incremental run against the configured output root."""
    cfg, polygons = _load(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    manifest = run_once(
        cfg,
        client=open_client(cfg.stac.endpoint),
        reader=RasterioReader(),
        store=_store(cfg, output_root),
        polygons=polygons,
        now=when,
        config_path=config,
        output_root_override=output_root,
    )
    typer.echo(manifest.to_json())
    if manifest.failed:
        raise typer.Exit(code=2)


@app.command()
def backfill(
    start: Annotated[
        datetime,
        typer.Option(
            "--start",
            formats=["%Y-%m-%d"],
            help="First acquisition date, UTC, inclusive",
        ),
    ],
    end: Annotated[
        datetime,
        typer.Option(
            "--end", formats=["%Y-%m-%d"], help="Last acquisition date, UTC, inclusive"
        ),
    ],
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
    now: Annotated[datetime | None, typer.Option(help=NOW_HELP)] = None,
) -> None:
    """Run stages 1 to 6 over acquisitions from --start to --end, skipping items
    already in the ledger.
    """
    if end < start:
        raise typer.BadParameter("--end is before --start")
    first = start.replace(tzinfo=UTC)
    last = end.replace(tzinfo=UTC) + timedelta(days=1) - timedelta(microseconds=1)
    cfg, polygons = _load(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        manifest = backfill_once(
            cfg,
            start=first,
            end=last,
            client=open_client(cfg.stac.endpoint),
            reader=RasterioReader(),
            store=_store(cfg, output_root),
            polygons=polygons,
            now=when,
            config_path=config,
            output_root_override=output_root,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(manifest.to_json())
    if manifest.failed:
        raise typer.Exit(code=2)


@app.command()
def score(
    start: Annotated[
        datetime,
        typer.Option(
            "--start",
            formats=["%Y-%m-%d"],
            help="First acquisition date, UTC, inclusive",
        ),
    ],
    end: Annotated[
        datetime,
        typer.Option(
            "--end", formats=["%Y-%m-%d"], help="Last acquisition date, UTC, inclusive"
        ),
    ],
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
    now: Annotated[datetime | None, typer.Option(help=NOW_HELP)] = None,
) -> None:
    """Score stored observations from --start to --end against the seasonal
    baseline and write change rows. Use after a backfill.
    """
    if end < start:
        raise typer.BadParameter("--end is before --start")
    first = start.replace(tzinfo=UTC)
    last = end.replace(tzinfo=UTC) + timedelta(days=1) - timedelta(microseconds=1)
    cfg = load_config(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        manifest = score_once(
            cfg,
            start=first,
            end=last,
            store=_store(cfg, output_root),
            now=when,
            config_path=config,
            output_root_override=output_root,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(manifest.to_json())


@app.command()
def verify(
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
    run_id: Annotated[
        str | None, typer.Option(help="Defaults to the latest run")
    ] = None,
) -> None:
    """Score the known-good checks for one run and write the report."""
    from wetland_change.verify.run import latest_run_id, run_exists, verify_run

    cfg, polygons = _load(config)
    store = _store(cfg, output_root)
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


class _UnreachableClient:
    """Stands in for a catalogue that failed to open; every search re-raises."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def search(self, **kwargs: Any) -> Any:
        raise self._exc


def _open_or_stub(endpoint: str) -> StacClient:
    """Open a client, or a stub whose searches raise, so one dead catalogue
    gives skipped checks for that source only."""
    try:
        return open_client(endpoint)
    except Exception as exc:
        return _UnreachableClient(exc)


@app.command()
def freshness(
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
    now: Annotated[datetime | None, typer.Option(help=NOW_HELP)] = None,
) -> None:
    """Check the scheduled job is alive: newest processed item under 7 days old \
and ledger counts matching Earth Search and Copernicus per tile over 30 days."""
    from wetland_change.verify.copernicus import CDSE_STAC
    from wetland_change.verify.freshness import freshness_checks

    cfg, polygons = _load(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    ledger = read_ledger(_store(cfg, output_root))
    checks = freshness_checks(
        ledger,
        _open_or_stub(cfg.stac.endpoint),
        _open_or_stub(CDSE_STAC),
        cfg.stac,
        bbox=union_bbox_4326(polygons),
        polygons_4326=[p.geometry_4326 for p in polygons],
        now=when,
    )
    for check in checks:
        status = (
            "skip" if check.passed is None else ("pass" if check.passed else "FAIL")
        )
        tile = check.detail.get("tile", "")
        typer.echo(f"{status}\t{check.name}\t{check.measured}\t{tile}")
    if any(check.passed is False for check in checks):
        raise typer.Exit(code=3)
    if any(check.passed is None for check in checks):
        typer.echo("some freshness checks did not run", err=True)
        raise typer.Exit(code=4)


@app.command("build-catalogue")
def build_catalogue_command(
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
) -> None:
    """Rebuild the STAC catalogue and items.parquet from the ledger."""
    cfg = load_config(config)
    written = build_and_write(_store(cfg, output_root), base_url=cfg.catalogue.base_url)
    for path in written:
        typer.echo(path)
    typer.echo(f"{len(written)} files written")
