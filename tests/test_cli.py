from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import box as shapely_box
from shapely.geometry.base import BaseGeometry
from typer.testing import CliRunner

from tests.test_pipeline import NOW, FakeClient, FakeSearch, _config, _polygons, _run
from tests.test_verify_copernicus import BBOX, cdse_item, es_item
from tests.test_verify_freshness import row
from wetland_change import cli
from wetland_change.aoi import AoiPolygon
from wetland_change.cli import app
from wetland_change.ledger import write_ledger
from wetland_change.store import OutputStore
from wetland_change.verify.copernicus import CDSE_STAC

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
        "verify",
        "freshness",
        "build-catalogue",
    ):
        assert command in result.output


def test_run_help_mentions_config() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.output


def test_build_catalogue_help_exits_zero() -> None:
    result = runner.invoke(app, ["build-catalogue", "--help"])
    assert result.exit_code == 0


def test_backfill_help_lists_range_and_output_root() -> None:
    result = runner.invoke(app, ["backfill", "--help"])
    assert result.exit_code == 0
    for option in ("--start", "--end", "--output-root", "--config"):
        assert option in result.output


@pytest.mark.parametrize(
    "command", ["run", "verify", "freshness", "discover", "score", "build-catalogue"]
)
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
        assert option in result.output


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
