from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry.base import BaseGeometry
from typer.testing import CliRunner

from tests.test_pipeline import FakeClient, _config, _polygons
from wetland_change import cli
from wetland_change.cli import app
from wetland_change.store import OutputStore

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
    for command in ("discover", "run", "backfill", "verify"):
        assert command in result.output


def test_run_help_mentions_config() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.output


def test_backfill_help_lists_range_and_output_root() -> None:
    result = runner.invoke(app, ["backfill", "--help"])
    assert result.exit_code == 0
    for option in ("--start", "--end", "--output-root", "--config"):
        assert option in result.output


@pytest.mark.parametrize("command", ["run", "verify", "discover"])
def test_output_root_listed_on_every_command(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "--output-root" in result.output


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
