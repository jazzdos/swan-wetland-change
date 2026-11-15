"""Command line: discover, run, backfill, score, requeue, verify, freshness,
build-catalogue, compact-ledger, add-observation-footers, add-dea-attribution,
add-copernicus-notice, add-dbca-attribution.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import pyarrow as pa
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
    compact_ledger,
    exhausted_keys,
    read_ledger,
    read_ledger_parts,
    rejected_keys,
    retry_ids,
    seen_keys,
    watermark,
)
from wetland_change.manifest import new_run_id
from wetland_change.outputs.attribution_backfill import add_missing_attribution
from wetland_change.outputs.dbca_backfill import add_missing_dbca_attribution
from wetland_change.outputs.footer_backfill import add_missing_footers
from wetland_change.outputs.notice_backfill import add_missing_notice
from wetland_change.pipeline import (
    RunIdReusedError,
    backfill_once,
    discovery_created_from,
    requeue_once,
    run_once,
    score_once,
)
from wetland_change.raster.read import RasterioReader
from wetland_change.runtime import capture_environment
from wetland_change.stac import PlaceholderBaseUrlError, build_and_write
from wetland_change.store import OutputStore
from wetland_change.verify.wo import dea_reader, find_wo_href

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
        rejected_seen=rejected_keys(ledger),
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
    catalogue: Annotated[
        bool,
        typer.Option(
            "--catalogue/--no-catalogue",
            help="Build the STAC catalogue at the end of the run (default), or "
            "leave it to a later build-catalogue",
        ),
    ] = True,
) -> None:
    """One incremental run against the configured output root."""
    cfg, polygons = _load(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        manifest = run_once(
            cfg,
            client=open_client(cfg.stac.endpoint),
            reader=RasterioReader(),
            store=_store(cfg, output_root),
            polygons=polygons,
            now=when,
            config_path=config,
            output_root_override=output_root,
            build_catalogue=catalogue,
            wo_lookup=find_wo_href,
            wo_reader_factory=dea_reader,
        )
    except (PlaceholderBaseUrlError, RunIdReusedError) as exc:
        raise typer.BadParameter(str(exc)) from exc
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
    except pa.ArrowException:
        raise
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
    except pa.ArrowException:
        raise
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(manifest.to_json())


@app.command()
def requeue(
    item_ids: Annotated[
        list[str] | None,
        typer.Argument(help="Ids of exhausted items to requeue"),
    ] = None,
    all_exhausted: Annotated[
        bool, typer.Option("--all", help="Requeue every exhausted item")
    ] = False,
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
    now: Annotated[datetime | None, typer.Option(help=NOW_HELP)] = None,
) -> None:
    """Requeue exhausted items so the next run retries them with fresh attempts."""
    cfg = load_config(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        manifest = requeue_once(
            cfg,
            item_ids=item_ids or [],
            all_exhausted=all_exhausted,
            store=_store(cfg, output_root),
            now=when,
            config_path=config,
            output_root_override=output_root,
        )
    except pa.ArrowException:
        raise
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(manifest.to_json())


@app.command()
def verify(
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
    run_id: Annotated[
        str | None,
        typer.Option(
            help="Defaults to the latest daily run (kind run) with processed scenes"
        ),
    ] = None,
) -> None:
    """Score the known-good checks for one run and write the report.

    Exits 3 when a check failed, 4 when nothing was scored, 5 when the run
    manifest cannot be read, and 6 when a reference check could not run
    because its source raised an error. A live water check that passes
    agreement and fails only the wet area clause is reported as warn and does
    not change the exit code; the pooled wet area check still can
    (docs/decisions/0008-exit-code-for-live-water-check-failures.md).
    """
    from wetland_change.manifest import manifest_path
    from wetland_change.verify.checks import check_note, verdict_checks
    from wetland_change.verify.layers import advisory_note, advisory_summaries
    from wetland_change.verify.run import (
        ManifestReadError,
        latest_run_id,
        read_manifest_bytes,
        run_exists,
        verify_run,
    )

    cfg, polygons = _load(config)
    store = _store(cfg, output_root)
    try:
        target = run_id or latest_run_id(store)
    except ManifestReadError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=5) from exc
    if target is None:
        raise typer.BadParameter(
            "no daily run with processed scenes in the output root"
        )
    if not run_exists(store, target):
        raise typer.BadParameter(f"no run {target!r} in the output root")
    try:
        read_manifest_bytes(store, manifest_path(target))
    except ManifestReadError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=5) from exc
    all_checks = verify_run(cfg, store, target, polygons=polygons)
    # Advisory rows (ADR 0012) hold no verdict: the CLI prints one summary line
    # per live check and layer instead of a line per row, and they never move
    # the exit code.
    checks = verdict_checks(all_checks)
    n_warned = 0
    for check in checks:
        if check.passed is None:
            status = "skip"
        elif check.wet_area_only_failure:
            status = "warn"
            n_warned += 1
        else:
            status = "pass" if check.passed else "FAIL"
        fields = [status, check.name, str(check.measured), check.reference]
        note = check_note(check)
        if note:
            fields.append(note)
        typer.echo("\t".join(fields))
    for summary in advisory_summaries(all_checks):
        typer.echo(
            "\t".join(
                [
                    "advisory",
                    str(summary["check"]),
                    str(summary["layer"]),
                    advisory_note(summary),
                ]
            )
        )
    if n_warned:
        typer.echo(
            f"{n_warned} live water checks failed on wet area alone for run "
            f"{target}; exit code unchanged "
            "(docs/decisions/0008-exit-code-for-live-water-check-failures.md)",
            err=True,
        )
    if any(check.blocking for check in checks):
        raise typer.Exit(code=3)
    n_errored = sum(check.errored for check in checks)
    if n_errored:
        typer.echo(
            f"{n_errored} reference checks could not run for run {target}", err=True
        )
        raise typer.Exit(code=6)
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
    """Check the scheduled job is alive: newest processed item under 7 days old, \
no item failed three times without succeeding, and ledger counts matching \
Earth Search and Copernicus per tile over 30 days."""
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
    try:
        written = build_and_write(
            _store(cfg, output_root), base_url=cfg.catalogue.base_url
        )
    except PlaceholderBaseUrlError as exc:
        raise typer.BadParameter(str(exc)) from exc
    for path in written:
        typer.echo(path)
    typer.echo(f"{len(written)} files written")


@app.command("compact-ledger")
def compact_ledger_command(
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
    now: Annotated[datetime | None, typer.Option(help=NOW_HELP)] = None,
) -> None:
    """Merge every ledger part into one file under ledger/compacted/.

    The merged file is written and read back before any part is deleted. Run
    it when no workflow is running: a run that lists the ledger while parts are
    being deleted re-reads once, but a second miss fails that run.
    """
    cfg = load_config(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    store = _store(cfg, output_root)
    ledger, paths = read_ledger_parts(store)
    if len(paths) < 2:
        typer.echo("nothing to compact")
        return
    written = compact_ledger(store, ledger, paths, run_id=new_run_id(when), min_parts=1)
    for path in written:
        typer.echo(path)
    typer.echo(f"{len(paths)} parts merged")


@app.command("add-observation-footers")
def add_observation_footers_command(
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="List the files that would be rewritten; write nothing"
        ),
    ] = False,
    now: Annotated[datetime | None, typer.Option(help=NOW_HELP)] = None,
) -> None:
    """Add the provenance footer to observation files that lack it.

    Only those files are rewritten; --dry-run lists them without writing.
    """
    cfg = load_config(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    commit = capture_environment().git_commit
    if commit is None:
        raise typer.BadParameter("no git commit found; run from a checkout")
    result = add_missing_footers(
        _store(cfg, output_root),
        water=cfg.water,
        operation_epsg=cfg.aoi.operation_epsg,
        commit=commit,
        on=when.date(),
        dry_run=dry_run,
    )
    for path in result.rewritten:
        typer.echo(path)
    for path, message in result.failed:
        typer.echo(f"{path}\t{message}", err=True)
    verb = "would rewrite" if dry_run else "rewritten"
    typer.echo(
        f"scanned {result.scanned}, {verb} {len(result.rewritten)}, "
        f"skipped {len(result.skipped)}, failed {len(result.failed)}"
    )
    if result.failed:
        raise typer.Exit(code=1)


@app.command("add-dea-attribution")
def add_dea_attribution_command(
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="List the files that would be rewritten; write nothing"
        ),
    ] = False,
    now: Annotated[datetime | None, typer.Option(help=NOW_HELP)] = None,
) -> None:
    """Add the CC BY 4.0 DEA attribution to observation, change and verification
    files that lack it.

    Only those files are rewritten; --dry-run lists them without writing.
    """
    cfg = load_config(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    commit = capture_environment().git_commit
    if commit is None:
        raise typer.BadParameter("no git commit found; run from a checkout")
    result = add_missing_attribution(
        _store(cfg, output_root), commit=commit, on=when.date(), dry_run=dry_run
    )
    for path in result.rewritten:
        typer.echo(path)
    for path, message in result.failed:
        typer.echo(f"{path}\t{message}", err=True)
    verb = "would rewrite" if dry_run else "rewritten"
    typer.echo(
        f"scanned {result.scanned}, {verb} {len(result.rewritten)}, "
        f"skipped {len(result.skipped)}, failed {len(result.failed)}"
    )
    if result.failed:
        raise typer.Exit(code=1)


@app.command("add-copernicus-notice")
def add_copernicus_notice_command(
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="List the files that would be rewritten; write nothing"
        ),
    ] = False,
    now: Annotated[datetime | None, typer.Option(help=NOW_HELP)] = None,
) -> None:
    """Add the Copernicus Sentinel data notice to observation, change, verification
    and ledger files that lack it.

    Only those files are rewritten; --dry-run lists them without writing.
    """
    cfg = load_config(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    commit = capture_environment().git_commit
    if commit is None:
        raise typer.BadParameter("no git commit found; run from a checkout")
    result = add_missing_notice(
        _store(cfg, output_root), commit=commit, on=when.date(), dry_run=dry_run
    )
    for path in result.rewritten:
        typer.echo(path)
    for path, message in result.failed:
        typer.echo(f"{path}\t{message}", err=True)
    verb = "would rewrite" if dry_run else "rewritten"
    typer.echo(
        f"scanned {result.scanned}, {verb} {len(result.rewritten)}, "
        f"skipped {len(result.skipped)}, failed {len(result.failed)}"
    )
    if result.failed:
        raise typer.Exit(code=1)


@app.command("add-dbca-attribution")
def add_dbca_attribution_command(
    config: ConfigOption = Path("config/pipeline.toml"),
    output_root: OutputRootOption = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="List the files that would be rewritten; write nothing"
        ),
    ] = False,
    now: Annotated[datetime | None, typer.Option(help=NOW_HELP)] = None,
) -> None:
    """Add the DBCA-010 CC BY-NC 4.0 attribution to observation and change files
    that lack it.

    Only those files are rewritten; --dry-run lists them without writing.
    """
    cfg = load_config(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    commit = capture_environment().git_commit
    if commit is None:
        raise typer.BadParameter("no git commit found; run from a checkout")
    result = add_missing_dbca_attribution(
        _store(cfg, output_root), commit=commit, on=when.date(), dry_run=dry_run
    )
    for path in result.rewritten:
        typer.echo(path)
    for path, message in result.failed:
        typer.echo(f"{path}\t{message}", err=True)
    verb = "would rewrite" if dry_run else "rewritten"
    typer.echo(
        f"scanned {result.scanned}, {verb} {len(result.rewritten)}, "
        f"skipped {len(result.skipped)}, failed {len(result.failed)}"
    )
    if result.failed:
        raise typer.Exit(code=1)
