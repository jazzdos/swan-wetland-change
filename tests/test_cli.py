from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import time
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import click
import pyarrow.parquet as pq
import pytest
from shapely.geometry import box as shapely_box
from shapely.geometry.base import BaseGeometry
from typer.testing import CliRunner

from tests.test_pipeline import NOW, FakeClient, FakeSearch, _config, _polygons, _run
from tests.test_verify_copernicus import BBOX, cdse_item, es_item
from tests.test_verify_freshness import row
from wetland_change import cli
from wetland_change.aoi import AoiPolygon
from wetland_change.attribution import DEA_ATTRIBUTION_ADDED_KEY, DEA_ATTRIBUTION_KEY
from wetland_change.cli import app
from wetland_change.ledger import (
    MAX_ATTEMPTS,
    latest_entries,
    read_ledger,
    write_ledger,
)
from wetland_change.outputs.footer_backfill import ADDED_KEY
from wetland_change.outputs.provenance import FOOTER_KEYS
from wetland_change.runtime import Environment
from wetland_change.sentinel_notice import (
    COPERNICUS_NOTICE_ADDED_KEY,
    COPERNICUS_NOTICE_KEY,
)
from wetland_change.store import OutputStore
from wetland_change.verify import freshness as freshness_module
from wetland_change.verify.checks import Check
from wetland_change.verify.copernicus import CDSE_STAC
from wetland_change.verify.wo import POOLED_WET_AREA_CHECK, dea_reader, find_wo_href

runner = CliRunner()


def _patch_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: FakeClient,
    polygons: list[Any],
) -> Path:
    cfg = _config(tmp_path / "configured")
    monkeypatch.setattr(cli, "_load", lambda config: (cfg, polygons))
    monkeypatch.setattr(cli, "open_client", lambda endpoint: client)
    config_file = tmp_path / "pipeline.toml"
    config_file.write_text("# test config\n")
    return config_file


def _only_manifest(root: Path) -> dict[str, Any]:
    files = sorted((root / "runs").glob("*.json"))
    assert len(files) == 1
    payload: dict[str, Any] = json.loads(files[0].read_text())
    return payload


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "discover",
        "run",
        "backfill",
        "score",
        "requeue",
        "verify",
        "freshness",
        "build-catalogue",
        "compact-ledger",
        "add-observation-footers",
        "add-dea-attribution",
        "add-copernicus-notice",
    ):
        assert command in click.unstyle(result.output)


def test_run_help_mentions_config() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--config" in click.unstyle(result.output)


def test_build_catalogue_help_exits_zero() -> None:
    result = runner.invoke(app, ["build-catalogue", "--help"])
    assert result.exit_code == 0


def test_run_help_lists_the_catalogue_switch() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--no-catalogue" in click.unstyle(result.output)


def test_compact_ledger_help_lists_options() -> None:
    result = runner.invoke(app, ["compact-ledger", "--help"])
    assert result.exit_code == 0
    text = click.unstyle(result.output)
    for option in ("--config", "--output-root", "--now"):
        assert option in text


def test_backfill_help_lists_range_and_output_root() -> None:
    result = runner.invoke(app, ["backfill", "--help"])
    assert result.exit_code == 0
    for option in ("--start", "--end", "--output-root", "--config"):
        assert option in click.unstyle(result.output)


@pytest.mark.parametrize(
    "command",
    [
        "run",
        "verify",
        "freshness",
        "discover",
        "score",
        "requeue",
        "build-catalogue",
        "compact-ledger",
        "add-observation-footers",
        "add-dea-attribution",
        "add-copernicus-notice",
    ],
)
def test_output_root_listed_on_every_command(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "--output-root" in click.unstyle(result.output)


@pytest.fixture
def perth_tz(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TZ", "Australia/Perth")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.usefixtures("perth_tz")
@pytest.mark.parametrize("command", ["run", "backfill", "score", "freshness"])
def test_now_without_zone_is_read_as_local_time(
    command: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    box_4326 = shapely_box(*BBOX)
    polygons = [AoiPolygon("p", "site", "ramsar", box_4326, box_4326)]
    cfg_file = _patch_cli(monkeypatch, tmp_path, FakeClient([]), polygons)
    monkeypatch.setattr(cli, "load_config", lambda config: _config(tmp_path / "c"))
    seen: dict[str, Any] = {}

    def fake_once(*args: Any, **kwargs: Any) -> Any:
        seen["now"] = kwargs["now"]
        return SimpleNamespace(to_json=lambda: "{}", failed=False)

    def fake_freshness(*args: Any, **kwargs: Any) -> list[Any]:
        seen["now"] = kwargs["now"]
        return []

    monkeypatch.setattr(cli, "run_once", fake_once)
    monkeypatch.setattr(cli, "backfill_once", fake_once)
    monkeypatch.setattr(cli, "score_once", fake_once)
    monkeypatch.setattr(freshness_module, "freshness_checks", fake_freshness)
    args = [
        command,
        "--config",
        str(cfg_file),
        "--output-root",
        str(tmp_path / "out"),
        "--now",
        "2026-10-29T10:00:00",
    ]
    if command in ("backfill", "score"):
        args += ["--start", "2026-10-01", "--end", "2026-10-02"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, (result.output, result.exception)
    assert seen["now"].isoformat() == "2026-10-29T02:00:00+00:00"


@pytest.mark.parametrize(
    "command", ["run", "backfill", "score", "freshness", "requeue"]
)
def test_now_help_states_local_time_reading(command: str) -> None:
    result = runner.invoke(app, [command, "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    text = " ".join(click.unstyle(result.output).replace("│", " ").split())
    assert "without a zone is read as local time" in text


def test_run_output_root_override_writes_manifest_there(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfgfile = _patch_cli(
        monkeypatch, tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon)
    )
    override = tmp_path / "override"
    result = runner.invoke(
        app, ["run", "--config", str(cfgfile), "--output-root", str(override)]
    )
    assert result.exit_code == 0, (result.output, result.exception)
    payload = _only_manifest(override)
    assert payload["output_root_override"] == str(override)
    assert payload["kind"] == "run"
    assert payload["processed"] == 1
    assert payload["config_sha256"] == hashlib.sha256(cfgfile.read_bytes()).hexdigest()
    assert not (tmp_path / "configured").exists()


def test_run_refuses_a_reused_run_id(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfgfile = _patch_cli(
        monkeypatch, tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon)
    )
    root = tmp_path / "out"
    args = [
        "run",
        "--config",
        str(cfgfile),
        "--output-root",
        str(root),
        "--now",
        "2026-10-29T10:00:00",
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, (first.output, first.exception)
    before = {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
    assert before
    second = runner.invoke(app, args)
    assert second.exit_code == 2, (second.output, second.exception)
    assert isinstance(second.exception, SystemExit)
    text = " ".join(click.unstyle(second.output).replace("│", " ").split())
    assert "already has" in text
    assert second.stdout == ""
    after = {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
    assert after == before


def test_run_no_catalogue_leaves_no_stac_directory(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfgfile = _patch_cli(
        monkeypatch, tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon)
    )
    skipped = tmp_path / "skipped"
    built = tmp_path / "built"
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(cfgfile),
            "--output-root",
            str(skipped),
            "--no-catalogue",
        ],
    )
    assert result.exit_code == 0, (result.output, result.exception)
    assert _only_manifest(skipped)["processed"] == 1
    assert not (skipped / "stac").exists()
    result = runner.invoke(
        app, ["run", "--config", str(cfgfile), "--output-root", str(built)]
    )
    assert result.exit_code == 0, (result.output, result.exception)
    assert (built / "stac" / "catalog.json").exists()


def _seed_parts(root: Path, count: int) -> OutputStore:
    """`count` single-scene ledger parts from separate runs, none compacted."""
    store = OutputStore(str(root))
    for day in range(count):
        write_ledger(
            [
                row(
                    f"2026-10-{day + 1:02d}",
                    item_id=f"item-{day}",
                    run_id=f"seed{day:02d}",
                )
            ],
            store,
            run_id=f"seed{day:02d}",
        )
    return store


def test_compact_ledger_merges_parts_and_keeps_the_latest_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _patch_cli(monkeypatch, tmp_path, FakeClient([]), [])
    monkeypatch.setattr(cli, "load_config", lambda config: _config(tmp_path / "unused"))
    root = tmp_path / "root"
    store = _seed_parts(root, 3)
    before = latest_entries(read_ledger(store)).reset_index(drop=True)
    result = runner.invoke(
        app,
        [
            "compact-ledger",
            "--config",
            str(cfgfile),
            "--output-root",
            str(root),
            "--now",
            "2026-10-30T12:00:00",
        ],
    )
    assert result.exit_code == 0, (result.output, result.exception)
    remaining = [p for p in store.list_files("ledger") if p.endswith(".parquet")]
    assert len(remaining) == 1
    assert remaining[0].startswith("ledger/compacted/ledger_compact_2026103")
    assert remaining[0] in result.output
    assert "3 parts merged" in result.output
    after = latest_entries(read_ledger(store)).reset_index(drop=True)
    assert after.equals(before)
    assert not (tmp_path / "unused").exists()


def test_compact_ledger_with_fewer_than_two_parts_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _patch_cli(monkeypatch, tmp_path, FakeClient([]), [])
    monkeypatch.setattr(cli, "load_config", lambda config: _config(tmp_path / "unused"))
    root = tmp_path / "root"
    store = _seed_parts(root, 1)
    files = store.list_files("ledger")
    result = runner.invoke(
        app, ["compact-ledger", "--config", str(cfgfile), "--output-root", str(root)]
    )
    assert result.exit_code == 0, (result.output, result.exception)
    assert "nothing to compact" in result.output
    assert store.list_files("ledger") == files


def test_backfill_cli_day_range_is_inclusive(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfgfile = _patch_cli(
        monkeypatch, tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon)
    )
    bf = tmp_path / "bf"
    result = runner.invoke(
        app,
        [
            "backfill",
            "--start",
            "2026-10-27",
            "--end",
            "2026-10-27",
            "--config",
            str(cfgfile),
            "--output-root",
            str(bf),
        ],
    )
    assert result.exit_code == 0, (result.output, result.exception)
    payload = _only_manifest(bf)
    assert payload["kind"] == "backfill"
    assert payload["processed"] == 1
    assert payload["datetime_start"] == "2026-10-27T00:00:00+00:00"
    assert payload["datetime_end"] == "2026-10-27T23:59:59.999999+00:00"
    assert payload["output_root_override"] == str(bf)


def test_backfill_cli_rejects_end_before_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(config: Path) -> None:
        raise AssertionError("config must not be loaded before range validation")

    monkeypatch.setattr(cli, "_load", explode)
    result = runner.invoke(
        app, ["backfill", "--start", "2026-10-28", "--end", "2026-10-27"]
    )
    assert result.exit_code == 2


def test_verify_reads_the_override_root(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfgfile = _patch_cli(
        monkeypatch, tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon)
    )
    override = tmp_path / "override"
    (override / "runs").mkdir(parents=True)
    (override / "runs" / "20261029T100000Z.json").write_text('{"processed": 1}')
    seen: list[tuple[str, str]] = []

    def fake(cfg: Any, store: OutputStore, run_id: str, **kwargs: Any) -> list[Any]:
        seen.append((store.uri, run_id))
        return []

    monkeypatch.setattr("wetland_change.verify.run.verify_run", fake)
    result = runner.invoke(
        app, ["verify", "--config", str(cfgfile), "--output-root", str(override)]
    )
    assert result.exit_code == 4, (result.output, result.exception)
    assert seen == [(OutputStore(str(override)).uri, "20261029T100000Z")]


def _verify_with(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    checks: list[Check],
) -> Any:
    cfgfile = _patch_cli(
        monkeypatch, tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon)
    )
    override = tmp_path / "override"
    (override / "runs").mkdir(parents=True)
    (override / "runs" / "20261029T100000Z.json").write_text('{"processed": 1}')
    monkeypatch.setattr("wetland_change.verify.run.verify_run", lambda *a, **k: checks)
    return runner.invoke(
        app, ["verify", "--config", str(cfgfile), "--output-root", str(override)]
    )


def _wo_check(
    *,
    passed: bool,
    measured: float,
    diff_pp: float,
    wet_passed: bool,
    polygon_id: str = "ramsar-12",
) -> Check:
    return Check(
        "water_vs_dea_s2_wo",
        passed,
        measured,
        0.91,
        "https://example/wo.tif",
        {
            "polygon_id": polygon_id,
            "item": "S2A_T50HLJ_20261029T021516_L2A",
            "n_mutually_clear": 1000,
            "wet_area_diff_pp": diff_pp,
            "wet_area_max_pp": 5.0,
            "wet_area_passed": wet_passed,
        },
    )


def _wet_only() -> Check:
    return _wo_check(passed=False, measured=0.9374, diff_pp=5.90, wet_passed=False)


def _pass_check() -> Check:
    return Check("reflectance_scaling", True, 1.0, 1.0, "r")


def test_verify_wet_area_only_failure_warns_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    result = _verify_with(
        monkeypatch,
        tmp_path,
        fixture_item,
        fixture_polygon,
        [_pass_check(), _wet_only()],
    )
    assert result.exit_code == 0, (result.output, result.exception)
    line = next(
        x
        for x in result.output.splitlines()
        if x.startswith("warn\twater_vs_dea_s2_wo\t")
    )
    assert "+5.90 pp" in line and "ramsar-12" in line
    assert len(line.split("\t")) == 5
    assert "FAIL" not in result.output
    assert "1 live water checks failed on wet area alone" in result.output
    assert "docs/decisions/0008-exit-code-for-live-water-check-failures.md" in (
        result.output
    )


def test_verify_agreement_failure_beside_a_warn_exits_three(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    both = _wo_check(
        passed=False,
        measured=0.90,
        diff_pp=6.0,
        wet_passed=False,
        polygon_id="ramsar-9",
    )
    result = _verify_with(
        monkeypatch, tmp_path, fixture_item, fixture_polygon, [_wet_only(), both]
    )
    assert result.exit_code == 3, (result.output, result.exception)
    assert any(
        x.startswith("FAIL\twater_vs_dea_s2_wo\t") for x in result.output.splitlines()
    )


def test_verify_errored_skip_beside_a_warn_exits_six(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    errored = Check("scl_shares", None, None, None, "r", {"error": "RuntimeError: x"})
    result = _verify_with(
        monkeypatch, tmp_path, fixture_item, fixture_polygon, [_wet_only(), errored]
    )
    assert result.exit_code == 6, (result.output, result.exception)


def test_verify_a_warn_alone_counts_as_scored(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    result = _verify_with(
        monkeypatch, tmp_path, fixture_item, fixture_polygon, [_wet_only()]
    )
    assert result.exit_code == 0, (result.output, result.exception)


def test_verify_prints_one_advisory_line_per_layer_and_ignores_advisory_rows(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    from wetland_change.verify.layers import apply_layer_rule

    failing = _wo_check(
        passed=False,
        measured=0.5,
        diff_pp=1.0,
        wet_passed=True,
        polygon_id="dea-a",
    )
    errored = Check(
        "water_vs_dea_s2_wo",
        None,
        None,
        None,
        "DEA STAC",
        {"polygon_id": "dea-b", "error": "boom"},
    )
    rows = apply_layer_rule(
        [_pass_check(), failing, errored],
        {"dea-a": "dea_waterbody", "dea-b": "dea_waterbody"},
    )
    result = _verify_with(monkeypatch, tmp_path, fixture_item, fixture_polygon, rows)
    assert result.exit_code == 0
    lines = result.output.splitlines()
    advisory = [line for line in lines if line.startswith("advisory\t")]
    assert len(advisory) == 2
    assert advisory[0].split("\t")[1:3] == ["water_vs_dea_s2_wo", "dea_waterbody"]
    assert not any("dea-a" in line or "dea-b" in line for line in lines)
    assert not [line for line in lines if line.startswith("skip\twater_vs_dea")]


def test_verify_blocking_non_water_failure_exits_three(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    bad = Check("scene_grid", False, 0.5, 1.0, "r")
    result = _verify_with(
        monkeypatch, tmp_path, fixture_item, fixture_polygon, [_wet_only(), bad]
    )
    assert result.exit_code == 3, (result.output, result.exception)
    assert any(x.startswith("FAIL\tscene_grid\t") for x in result.output.splitlines())


def _pooled(passed: bool, gap: float) -> Check:
    return Check(
        POOLED_WET_AREA_CHECK,
        passed,
        gap,
        5.0,
        "https://example/wo.tif",
        {"n_checks": 4, "n_mutually_clear": 4000},
    )


def test_verify_warns_with_a_passing_pooled_check_exit_zero(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    result = _verify_with(
        monkeypatch,
        tmp_path,
        fixture_item,
        fixture_polygon,
        [_wet_only(), _pooled(True, 1.14)],
    )
    assert result.exit_code == 0, (result.output, result.exception)
    line = next(
        x
        for x in result.output.splitlines()
        if x.startswith("pass\t" + POOLED_WET_AREA_CHECK)
    )
    assert "pooled wet area gap +1.14 pp over 4 checks, limit 5.0 pp" in line


def test_verify_failing_pooled_check_exits_three(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    result = _verify_with(
        monkeypatch,
        tmp_path,
        fixture_item,
        fixture_polygon,
        [_wet_only(), _pooled(False, 7.5)],
    )
    assert result.exit_code == 3, (result.output, result.exception)
    line = next(
        x
        for x in result.output.splitlines()
        if x.startswith("FAIL\t" + POOLED_WET_AREA_CHECK)
    )
    assert "+7.50 pp" in line


def test_verify_exits_nonzero_when_a_manifest_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfgfile = _patch_cli(
        monkeypatch, tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon)
    )
    override = tmp_path / "override"
    (override / "runs").mkdir(parents=True)
    (override / "runs" / "20261029T100000Z.json").write_text('{"processed": 1}')
    (override / "runs" / "20261030T100000Z.json").write_text('{"processed": 1}')
    original = OutputStore.read_bytes

    def flaky(self: OutputStore, relpath: str) -> bytes:
        if relpath == "runs/20261030T100000Z.json":
            raise PermissionError("denied")
        return original(self, relpath)

    def must_not_run(*args: Any, **kwargs: Any) -> list[Any]:
        raise AssertionError("verify_run must not run when a manifest is unreadable")

    monkeypatch.setattr(OutputStore, "read_bytes", flaky)
    monkeypatch.setattr("wetland_change.verify.run.verify_run", must_not_run)
    result = runner.invoke(
        app, ["verify", "--config", str(cfgfile), "--output-root", str(override)]
    )
    assert result.exit_code == 5, (result.output, result.exception)
    assert "runs/20261030T100000Z.json" in result.output, (
        result.output,
        result.exception,
    )


def test_verify_run_id_exits_nonzero_when_its_manifest_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfgfile = _patch_cli(
        monkeypatch, tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon)
    )
    override = tmp_path / "override"
    (override / "runs").mkdir(parents=True)
    (override / "runs" / "20261030T100000Z.json").write_text('{"processed": 1}')
    original = OutputStore.read_bytes

    def flaky(self: OutputStore, relpath: str) -> bytes:
        if relpath == "runs/20261030T100000Z.json":
            raise PermissionError("denied")
        return original(self, relpath)

    def must_not_run(*args: Any, **kwargs: Any) -> list[Any]:
        raise AssertionError("verify_run must not run when a manifest is unreadable")

    monkeypatch.setattr(OutputStore, "read_bytes", flaky)
    monkeypatch.setattr("wetland_change.verify.run.verify_run", must_not_run)
    result = runner.invoke(
        app,
        [
            "verify",
            "--config",
            str(cfgfile),
            "--output-root",
            str(override),
            "--run-id",
            "20261030T100000Z",
        ],
    )
    assert result.exit_code == 5, (result.output, result.exception)
    assert "runs/20261030T100000Z.json" in result.output, (
        result.output,
        result.exception,
    )


def test_build_catalogue_rebuilds_stac_in_output_root(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfg = _config(tmp_path / "configured")
    monkeypatch.setattr(cli, "load_config", lambda config: cfg)
    root = tmp_path / "separate"
    root.mkdir()
    _run(root, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW)
    out = root / "out"
    shutil.rmtree(out / "stac")
    config_file = tmp_path / "pipeline.toml"
    config_file.write_text("# test config\n")
    result = runner.invoke(
        app,
        ["build-catalogue", "--config", str(config_file), "--output-root", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert (out / "stac" / "catalog.json").exists()
    assert not (tmp_path / "configured").exists()


FRESH_NOW = "2026-10-29T10:00:00"
FRESH_SENSED_2D = "2026-10-27T02:12:11"
FRESH_SENSED_8D = "2026-10-21T02:12:11"


class RaisingClient:
    def search(self, **kwargs: Any) -> FakeSearch:
        raise RuntimeError("catalogue down")


def _patch_freshness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    es_items: list[dict[str, Any]],
    cdse: Any,
    sensed: str,
) -> tuple[Path, Path]:
    """Config, plus an output root whose ledger holds one succeeded item."""
    cfg = _config(tmp_path / "configured")
    box_4326 = shapely_box(*BBOX)
    polygons = [AoiPolygon("p", "site", "ramsar", box_4326, box_4326)]
    monkeypatch.setattr(cli, "_load", lambda config: (cfg, polygons))
    clients = {cfg.stac.endpoint: FakeClient(es_items), CDSE_STAC: cdse}
    monkeypatch.setattr(cli, "open_client", lambda endpoint: clients[endpoint])
    root = tmp_path / "root"
    write_ledger([row(sensed)], OutputStore(str(root)), run_id="r1")
    config_file = tmp_path / "pipeline.toml"
    config_file.write_text("# test config\n")
    return config_file, root


def _freshness(config_file: Path, root: Path) -> Any:
    return runner.invoke(
        app,
        [
            "freshness",
            "--config",
            str(config_file),
            "--output-root",
            str(root),
            "--now",
            FRESH_NOW,
        ],
    )


def test_freshness_help_lists_options() -> None:
    result = runner.invoke(app, ["freshness", "--help"])
    assert result.exit_code == 0
    for option in ("--config", "--output-root", "--now"):
        assert option in click.unstyle(result.output)


def test_freshness_fails_when_newest_item_is_eight_days_old(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _patch_freshness(
        monkeypatch, tmp_path, [], FakeClient([]), FRESH_SENSED_8D
    )
    result = _freshness(config_file, root)
    assert result.exit_code == 3, result.output
    lines = [line for line in result.output.splitlines() if line.startswith("FAIL")]
    assert any("freshness_newest_item" in line for line in lines)


def test_freshness_fails_when_an_item_is_exhausted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _patch_freshness(
        monkeypatch,
        tmp_path,
        [es_item(FRESH_SENSED_2D)],
        FakeClient([cdse_item(FRESH_SENSED_2D)]),
        FRESH_SENSED_2D,
    )
    exhausted = dataclasses.replace(
        row(FRESH_SENSED_2D, status="failed", item_id="stuck", run_id="r2"),
        attempts=MAX_ATTEMPTS,
        error="boom",
    )
    write_ledger([exhausted], OutputStore(str(root)), run_id="r2")
    result = _freshness(config_file, root)
    assert result.exit_code == 3, result.output
    lines = [line for line in result.output.splitlines() if line.startswith("FAIL")]
    assert len(lines) == 1
    assert "freshness_exhausted_items" in lines[0]
    assert "pass\tfreshness_newest_item\t" in result.output


def test_freshness_passes_when_ledger_and_catalogues_agree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _patch_freshness(
        monkeypatch,
        tmp_path,
        [es_item(FRESH_SENSED_2D)],
        FakeClient([cdse_item(FRESH_SENSED_2D)]),
        FRESH_SENSED_2D,
    )
    result = _freshness(config_file, root)
    assert result.exit_code == 0, result.output
    assert "FAIL" not in result.output
    assert "pass\tfreshness_newest_item\t" in result.output
    assert "pass\tfreshness_exhausted_items\t0.0" in result.output
    assert "\t50HLK" in result.output


def test_freshness_exits_four_when_copernicus_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _patch_freshness(
        monkeypatch,
        tmp_path,
        [es_item(FRESH_SENSED_2D)],
        RaisingClient(),
        FRESH_SENSED_2D,
    )
    result = _freshness(config_file, root)
    assert result.exit_code == 4, result.output
    assert "skip\tfreshness_count_vs_copernicus" in result.output
    assert "FAIL" not in result.output


def test_freshness_exits_four_when_copernicus_fails_to_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _patch_freshness(
        monkeypatch,
        tmp_path,
        [es_item(FRESH_SENSED_2D)],
        FakeClient([]),
        FRESH_SENSED_2D,
    )
    patched = cli.open_client

    def opener(endpoint: str) -> Any:
        if endpoint == CDSE_STAC:
            raise RuntimeError("landing page down")
        return patched(endpoint)

    monkeypatch.setattr(cli, "open_client", opener)
    result = _freshness(config_file, root)
    assert result.exit_code == 4, result.output
    assert "pass\tfreshness_newest_item\t" in result.output
    assert "pass\tfreshness_count_vs_earth_search\t" in result.output
    assert "skip\tfreshness_count_vs_copernicus" in result.output
    assert "FAIL" not in result.output


def test_freshness_exits_four_when_earth_search_fails_to_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _patch_freshness(
        monkeypatch,
        tmp_path,
        [],
        FakeClient([cdse_item(FRESH_SENSED_2D)]),
        FRESH_SENSED_2D,
    )
    patched = cli.open_client

    def opener(endpoint: str) -> Any:
        if endpoint != CDSE_STAC:
            raise RuntimeError("landing page down")
        return patched(endpoint)

    monkeypatch.setattr(cli, "open_client", opener)
    result = _freshness(config_file, root)
    assert result.exit_code == 4, result.output
    assert "skip\tfreshness_count_vs_earth_search" in result.output
    assert "pass\tfreshness_count_vs_copernicus\t" in result.output


def _load_polygons(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waterbodies: Path
) -> list[Any]:
    fix = Path(__file__).parent / "fixtures" / "aoi"
    cfg = _config(tmp_path / "configured")
    aoi = cfg.aoi.model_copy(
        update={
            "ramsar_path": fix / "ramsar_mini.geojson",
            "waterbodies_path": waterbodies,
            "site_prefixes": ["Forrestdale & Thomsons Lakes"],
        }
    )
    cfg = cfg.model_copy(update={"aoi": aoi})
    monkeypatch.setattr(cli, "load_config", lambda config: cfg)
    return cli._load(Path("unused.toml"))[1]


def test_load_includes_dea_waterbodies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fix = Path(__file__).parent / "fixtures" / "aoi"
    polygons = _load_polygons(monkeypatch, tmp_path, fix / "waterbodies_mini.geojson")
    assert {p.layer for p in polygons} == {"ramsar", "dea_waterbody"}


def test_load_without_waterbodies_file_keeps_ramsar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    polygons = _load_polygons(monkeypatch, tmp_path, tmp_path / "absent.geojson")
    assert {p.layer for p in polygons} == {"ramsar"}


def _s3_placeholder_stub(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, polygons: list[Any]
) -> Path:
    config_file = _patch_cli(monkeypatch, tmp_path, FakeClient([]), polygons)
    cfg = _config(tmp_path / "configured")
    assert "invalid" in cfg.catalogue.base_url
    monkeypatch.setattr(cli, "load_config", lambda config: cfg)
    monkeypatch.setattr(cli, "_store", lambda cfg, root: SimpleNamespace(uri="s3://x/"))
    return config_file


def test_build_catalogue_refuses_placeholder_base_url_on_s3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file = _s3_placeholder_stub(monkeypatch, tmp_path, [])
    result = runner.invoke(
        app,
        ["build-catalogue", "--config", str(config_file), "--output-root", "s3://x/"],
    )
    assert result.exit_code != 0
    assert "base_url" in result.output


def test_run_refuses_placeholder_base_url_on_s3(
    monkeypatch: pytest.MonkeyPatch,
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    config_file = _s3_placeholder_stub(
        monkeypatch, tmp_path, _polygons(fixture_polygon)
    )
    result = runner.invoke(
        app, ["run", "--config", str(config_file), "--output-root", "s3://x/"]
    )
    assert result.exit_code != 0
    assert "base_url" in result.output


def test_corrupt_ledger_is_not_reported_as_bad_parameter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file = _patch_cli(monkeypatch, tmp_path, FakeClient([]), [])
    cfg = _config(tmp_path / "configured")
    monkeypatch.setattr(cli, "load_config", lambda config: cfg)
    root = tmp_path / "corrupt"
    part = root / "ledger" / "year=2026" / "ledger_bad.parquet"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"not a parquet file")
    result = runner.invoke(
        app,
        ["build-catalogue", "--config", str(config_file), "--output-root", str(root)],
    )
    assert result.exit_code != 0
    assert result.exit_code != 2
    assert "Invalid value" not in result.output
    assert result.exception is not None
    assert not isinstance(result.exception, SystemExit)


def test_corrupt_ledger_is_not_reported_as_bad_parameter_for_requeue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _requeue_setup(monkeypatch, tmp_path, exhausted=False)
    part = root / "ledger" / "year=2026" / "ledger_bad.parquet"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"not a parquet file")
    result = runner.invoke(app, _requeue_args(config_file, root, "--all"))
    assert result.exit_code != 0
    assert result.exit_code != 2
    assert "Invalid value" not in result.output
    assert result.exception is not None
    assert not isinstance(result.exception, SystemExit)


def test_requeue_help_lists_options() -> None:
    result = runner.invoke(app, ["requeue", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    text = click.unstyle(result.output)
    for option in ("--all", "--config", "--output-root", "--now"):
        assert option in text
    assert "Requeue exhausted items" in " ".join(text.replace("│", " ").split())


def _requeue_setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, exhausted: bool = True
) -> tuple[Path, Path]:
    config_file = tmp_path / "pipeline.toml"
    config_file.write_text("# test config\n")
    monkeypatch.setattr(cli, "load_config", lambda config: _config(tmp_path / "c"))
    root = tmp_path / "out"
    if exhausted:
        stuck = dataclasses.replace(
            row(FRESH_SENSED_2D, status="failed", item_id="stuck", run_id="r2"),
            attempts=MAX_ATTEMPTS,
            error="boom",
        )
        write_ledger([stuck], OutputStore(str(root)), run_id="r2")
    return config_file, root


def _requeue_args(config_file: Path, root: Path, *extra: str) -> list[str]:
    return [
        "requeue",
        "--config",
        str(config_file),
        "--output-root",
        str(root),
        "--now",
        "2026-12-01T10:00:00",
        *extra,
    ]


def test_requeue_prints_manifest_and_requeues_the_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _requeue_setup(monkeypatch, tmp_path)
    result = runner.invoke(app, _requeue_args(config_file, root, "stuck"))
    assert result.exit_code == 0, (result.output, result.exception)
    payload = json.loads(result.output)
    assert payload["kind"] == "requeue"
    assert payload["requeued_items"] == ["stuck"]
    assert payload["exhausted_items"] == []
    assert (root / "runs" / f"{payload['run_id']}.json").exists()


def test_requeue_all_requeues_every_exhausted_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _requeue_setup(monkeypatch, tmp_path)
    result = runner.invoke(app, _requeue_args(config_file, root, "--all"))
    assert result.exit_code == 0, (result.output, result.exception)
    assert json.loads(result.output)["requeued_items"] == ["stuck"]


def test_requeue_without_ids_or_all_exits_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _requeue_setup(monkeypatch, tmp_path)
    result = runner.invoke(app, _requeue_args(config_file, root))
    assert result.exit_code == 2, result.output


def test_requeue_unknown_id_exits_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _requeue_setup(monkeypatch, tmp_path)
    result = runner.invoke(app, _requeue_args(config_file, root, "nope"))
    assert result.exit_code == 2, result.output


def test_requeue_all_with_nothing_exhausted_exits_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file, root = _requeue_setup(monkeypatch, tmp_path, exhausted=False)
    result = runner.invoke(app, _requeue_args(config_file, root, "--all"))
    assert result.exit_code == 2, result.output


@pytest.mark.parametrize("command", ["run", "backfill"])
def test_only_run_passes_the_dea_wo_lookup(
    command: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    box_4326 = shapely_box(*BBOX)
    polygons = [AoiPolygon("p", "site", "ramsar", box_4326, box_4326)]
    cfg_file = _patch_cli(monkeypatch, tmp_path, FakeClient([]), polygons)
    seen: dict[str, Any] = {}

    def fake_once(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(to_json=lambda: "{}", failed=False)

    monkeypatch.setattr(cli, "run_once", fake_once)
    monkeypatch.setattr(cli, "backfill_once", fake_once)
    args = [command, "--config", str(cfg_file), "--output-root", str(tmp_path / "out")]
    if command == "backfill":
        args += ["--start", "2026-10-01", "--end", "2026-10-02"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, (result.output, result.exception)
    if command == "run":
        assert seen["wo_lookup"] is find_wo_href
        assert seen["wo_reader_factory"] is dea_reader
    else:
        assert "wo_lookup" not in seen
        assert "wo_reader_factory" not in seen


def _put_unfooted(root: Path, item_ids: list[str]) -> list[str]:
    from tests.test_footer_backfill import _old_bytes, _put_old, _rows

    store = OutputStore(str(root))
    return [_put_old(store, i, _old_bytes(_rows(i))) for i in item_ids]


def _footer_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    commit: str | None = "c0ffee",
) -> Path:
    monkeypatch.setattr(cli, "load_config", lambda config: _config(tmp_path / "unused"))
    monkeypatch.setattr(
        cli,
        "capture_environment",
        lambda: Environment(runtime={}, uv_lock_sha256=None, git_commit=commit),
    )
    cfgfile = tmp_path / "pipeline.toml"
    cfgfile.write_text("# test config\n")
    return cfgfile


def _footer_args(cfgfile: Path, root: Path, *extra: str) -> list[str]:
    return [
        "add-observation-footers",
        "--config",
        str(cfgfile),
        "--output-root",
        str(root),
        "--now",
        "2026-11-06T12:00:00",
        *extra,
    ]


def _bytes_by_path(root: Path, paths: list[str]) -> dict[str, bytes]:
    store = OutputStore(str(root))
    return {p: store.read_bytes(p) for p in paths}


def test_add_observation_footers_help_lists_dry_run_and_output_root() -> None:
    result = runner.invoke(app, ["add-observation-footers", "--help"])
    assert result.exit_code == 0
    text = click.unstyle(result.output)
    assert "--dry-run" in text
    assert "--output-root" in text


def test_add_observation_footers_rewrites_old_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    result = runner.invoke(app, _footer_args(cfgfile, root))
    assert result.exit_code == 0, (result.output, result.exception)
    lines = result.stdout.splitlines()
    assert sorted(lines[:2]) == sorted(paths)
    assert lines[-1] == "scanned 2, rewritten 2, skipped 0, failed 0"
    for data in _bytes_by_path(root, paths).values():
        meta = pq.read_schema(BytesIO(data)).metadata
        for key in (*FOOTER_KEYS, ADDED_KEY):
            assert key.encode() in meta
        assert json.loads(meta[ADDED_KEY.encode()]) == {
            "commit": "c0ffee",
            "date": "2026-11-06",
        }


def test_add_observation_footers_second_run_skips_and_keeps_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    first = runner.invoke(app, _footer_args(cfgfile, root))
    assert first.exit_code == 0, (first.output, first.exception)
    before = _bytes_by_path(root, paths)
    again = runner.invoke(app, _footer_args(cfgfile, root))
    assert again.exit_code == 0, (again.output, again.exception)
    assert again.stdout.strip() == "scanned 2, rewritten 0, skipped 2, failed 0"
    assert _bytes_by_path(root, paths) == before


def test_add_observation_footers_dry_run_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    before = _bytes_by_path(root, paths)
    result = runner.invoke(app, _footer_args(cfgfile, root, "--dry-run"))
    assert result.exit_code == 0, (result.output, result.exception)
    lines = result.stdout.splitlines()
    assert sorted(lines[:2]) == sorted(paths)
    assert lines[-1] == "scanned 2, would rewrite 2, skipped 0, failed 0"
    assert _bytes_by_path(root, paths) == before


def test_add_observation_footers_exits_1_when_a_file_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    [good] = _put_unfooted(root, ["S2A_A"])
    bad = "observations/year=2026/tile=50HLK/obs_bad.parquet"
    OutputStore(str(root)).write_bytes(bad, b"junk")
    result = runner.invoke(app, _footer_args(cfgfile, root))
    assert result.exit_code == 1, (result.output, result.exception)
    assert result.stdout.splitlines() == [
        good,
        "scanned 2, rewritten 1, skipped 0, failed 1",
    ]
    [failure] = result.stderr.splitlines()
    assert failure.startswith(f"{bad}\t")
    meta = pq.read_schema(BytesIO(OutputStore(str(root)).read_bytes(good))).metadata
    assert ADDED_KEY.encode() in meta


def test_add_observation_footers_without_a_commit_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path, commit=None)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    before = _bytes_by_path(root, paths)
    result = runner.invoke(app, _footer_args(cfgfile, root))
    assert result.exit_code == 2
    assert "no git commit found" in click.unstyle(result.output)
    assert _bytes_by_path(root, paths) == before


def test_add_observation_footers_output_root_overrides_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    configured = tmp_path / "unused"
    configured_paths = _put_unfooted(configured, ["S2A_C"])
    configured_before = _bytes_by_path(configured, configured_paths)
    root = tmp_path / "root"
    _put_unfooted(root, ["S2A_A", "S2A_B"])
    result = runner.invoke(app, _footer_args(cfgfile, root))
    assert result.exit_code == 0, (result.output, result.exception)
    assert result.stdout.splitlines()[-1] == (
        "scanned 2, rewritten 2, skipped 0, failed 0"
    )
    assert _bytes_by_path(configured, configured_paths) == configured_before


def _attribution_args(cfgfile: Path, root: Path, *extra: str) -> list[str]:
    return [
        "add-dea-attribution",
        "--config",
        str(cfgfile),
        "--output-root",
        str(root),
        "--now",
        "2026-11-15T12:00:00",
        *extra,
    ]


def test_add_dea_attribution_help_lists_dry_run_and_output_root() -> None:
    result = runner.invoke(app, ["add-dea-attribution", "--help"])
    assert result.exit_code == 0
    text = click.unstyle(result.output)
    assert "--dry-run" in text
    assert "--output-root" in text


def test_add_dea_attribution_rewrites_old_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    result = runner.invoke(app, _attribution_args(cfgfile, root))
    assert result.exit_code == 0, (result.output, result.exception)
    lines = result.stdout.splitlines()
    assert sorted(lines[:2]) == sorted(paths)
    assert lines[-1] == "scanned 2, rewritten 2, skipped 0, failed 0"
    for data in _bytes_by_path(root, paths).values():
        meta = pq.read_schema(BytesIO(data)).metadata
        assert DEA_ATTRIBUTION_KEY.encode() in meta
        assert json.loads(meta[DEA_ATTRIBUTION_ADDED_KEY.encode()]) == {
            "commit": "c0ffee",
            "date": "2026-11-15",
        }


def test_add_dea_attribution_second_run_skips_and_keeps_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    first = runner.invoke(app, _attribution_args(cfgfile, root))
    assert first.exit_code == 0, (first.output, first.exception)
    before = _bytes_by_path(root, paths)
    again = runner.invoke(app, _attribution_args(cfgfile, root))
    assert again.exit_code == 0, (again.output, again.exception)
    assert again.stdout.strip() == "scanned 2, rewritten 0, skipped 2, failed 0"
    assert _bytes_by_path(root, paths) == before


def test_add_dea_attribution_dry_run_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    before = _bytes_by_path(root, paths)
    result = runner.invoke(app, _attribution_args(cfgfile, root, "--dry-run"))
    assert result.exit_code == 0, (result.output, result.exception)
    lines = result.stdout.splitlines()
    assert sorted(lines[:2]) == sorted(paths)
    assert lines[-1] == "scanned 2, would rewrite 2, skipped 0, failed 0"
    assert _bytes_by_path(root, paths) == before


def test_add_dea_attribution_exits_1_when_a_file_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    [good] = _put_unfooted(root, ["S2A_A"])
    bad = "observations/year=2026/tile=50HLK/obs_bad.parquet"
    OutputStore(str(root)).write_bytes(bad, b"junk")
    result = runner.invoke(app, _attribution_args(cfgfile, root))
    assert result.exit_code == 1, (result.output, result.exception)
    assert result.stdout.splitlines() == [
        good,
        "scanned 2, rewritten 1, skipped 0, failed 1",
    ]
    [failure] = result.stderr.splitlines()
    assert failure.startswith(f"{bad}\t")


def test_add_dea_attribution_without_a_commit_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path, commit=None)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    before = _bytes_by_path(root, paths)
    result = runner.invoke(app, _attribution_args(cfgfile, root))
    assert result.exit_code == 2
    assert "no git commit found" in click.unstyle(result.output)
    assert _bytes_by_path(root, paths) == before


def _notice_args(cfgfile: Path, root: Path, *extra: str) -> list[str]:
    return [
        "add-copernicus-notice",
        "--config",
        str(cfgfile),
        "--output-root",
        str(root),
        "--now",
        "2026-11-15T12:00:00",
        *extra,
    ]


def test_add_copernicus_notice_help_lists_dry_run_and_output_root() -> None:
    result = runner.invoke(app, ["add-copernicus-notice", "--help"])
    assert result.exit_code == 0
    text = click.unstyle(result.output)
    assert "--dry-run" in text
    assert "--output-root" in text


def test_add_copernicus_notice_rewrites_old_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    result = runner.invoke(app, _notice_args(cfgfile, root))
    assert result.exit_code == 0, (result.output, result.exception)
    lines = result.stdout.splitlines()
    assert sorted(lines[:2]) == sorted(paths)
    assert lines[-1] == "scanned 2, rewritten 2, skipped 0, failed 0"
    for data in _bytes_by_path(root, paths).values():
        meta = pq.read_schema(BytesIO(data)).metadata
        assert COPERNICUS_NOTICE_KEY.encode() in meta
        assert json.loads(meta[COPERNICUS_NOTICE_ADDED_KEY.encode()]) == {
            "commit": "c0ffee",
            "date": "2026-11-15",
        }


def test_add_copernicus_notice_second_run_skips_and_keeps_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    first = runner.invoke(app, _notice_args(cfgfile, root))
    assert first.exit_code == 0, (first.output, first.exception)
    before = _bytes_by_path(root, paths)
    again = runner.invoke(app, _notice_args(cfgfile, root))
    assert again.exit_code == 0, (again.output, again.exception)
    assert again.stdout.strip() == "scanned 2, rewritten 0, skipped 2, failed 0"
    assert _bytes_by_path(root, paths) == before


def test_add_copernicus_notice_dry_run_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    before = _bytes_by_path(root, paths)
    result = runner.invoke(app, _notice_args(cfgfile, root, "--dry-run"))
    assert result.exit_code == 0, (result.output, result.exception)
    lines = result.stdout.splitlines()
    assert sorted(lines[:2]) == sorted(paths)
    assert lines[-1] == "scanned 2, would rewrite 2, skipped 0, failed 0"
    assert _bytes_by_path(root, paths) == before


def test_add_copernicus_notice_exits_1_when_a_file_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path)
    root = tmp_path / "root"
    [good] = _put_unfooted(root, ["S2A_A"])
    bad = "observations/year=2026/tile=50HLK/obs_bad.parquet"
    OutputStore(str(root)).write_bytes(bad, b"junk")
    result = runner.invoke(app, _notice_args(cfgfile, root))
    assert result.exit_code == 1, (result.output, result.exception)
    assert result.stdout.splitlines() == [
        good,
        "scanned 2, rewritten 1, skipped 0, failed 1",
    ]
    [failure] = result.stderr.splitlines()
    assert failure.startswith(f"{bad}\t")


def test_add_copernicus_notice_without_a_commit_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _footer_setup(monkeypatch, tmp_path, commit=None)
    root = tmp_path / "root"
    paths = _put_unfooted(root, ["S2A_A", "S2A_B"])
    before = _bytes_by_path(root, paths)
    result = runner.invoke(app, _notice_args(cfgfile, root))
    assert result.exit_code == 2
    assert "no git commit found" in click.unstyle(result.output)
    assert _bytes_by_path(root, paths) == before
