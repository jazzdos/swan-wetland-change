"""verify_run and the verify command under the layer rule of ADR 0012.

Live water and NDVI rows on the ramsar layer keep their verdict. Rows on any
other layer are measured and stored but hold no verdict and cannot fail the run
(docs/decisions/0012-live-check-limits-apply-to-their-calibrated-layer.md).
The live check functions are replaced by fakes that return a chosen outcome
per polygon, so each case names the rows it changes.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from shapely.geometry.base import BaseGeometry
from typer.testing import CliRunner

import wetland_change.verify.run as run_mod
from tests.test_verify import (
    DictReader,
    FakeReader,
    _built_run,
    _dea_dn,
    _nbart_item,
    _stack_and_window,
)
from wetland_change import cli
from wetland_change.aoi import AoiPolygon
from wetland_change.verify.checks import Check
from wetland_change.verify.run import scenes_for_run, verify_run
from wetland_change.verify.wo import WO_WET

REAL_VERIFY_RUN = verify_run

WATER = "water_vs_dea_s2_wo"
NDVI = "ndvi_vs_dea_nbart"
POOLED = "water_vs_dea_s2_wo_pooled_wet_area"
CORRELATION = "ndvi_correlation_vs_dea_nbart"
RAMSAR = ["ramsar-52", "ramsar-301", "ramsar-302", "ramsar-303", "ramsar-304"]
DEA = ["dea-wb0", "dea-wb1", "dea-wb2", "dea-wb3", "dea-wb4"]
ADVISORY_KEYS = {
    "layer",
    "polygon_id",
    "advisory",
    "advisory_rule",
    "within_ramsar_limit",
    "wet_area_only",
}

# outcome -> (passed, agreement, wet_area_pipeline, wet_area_wo,
# wet_area_diff_pp, wet_area_passed)
WATER_OUTCOMES = {
    "pass": (True, 0.99, 0.50, 0.50, 0.0, True),
    "agreement_fail": (False, 0.80, 0.50, 0.50, 0.0, True),
    "wet_only": (False, 0.95, 0.56, 0.50, 6.0, False),
    "dea_fail": (False, 0.70, 0.90, 0.10, 80.0, False),
}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("network disabled in offline tests")

    monkeypatch.setattr(run_mod, "open_client", refuse)
    monkeypatch.setattr(run_mod, "find_nbart_item", refuse)


def _discovery_fake(*args: Any, **kwargs: Any) -> list[Check]:
    return [Check("discovery_vs_copernicus", True, 0.0, 0.0, "fake", {"tile": "50HLK"})]


def _pixel_fake(*args: Any) -> Check:
    return Check("pixels_vs_planetary_computer", True, 1.0, 1.0, "fake")


def _medians() -> dict[str, float]:
    return {pid: round(0.20 + 0.05 * i, 2) for i, pid in enumerate(RAMSAR + DEA)}


def _layered(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    water: dict[str, str] | None = None,
    ndvi: dict[str, str] | None = None,
) -> tuple[Any, Any, str, list[AoiPolygon], dict[str, Any]]:
    """A built run with five ramsar and five waterbody polygons on the scene.

    `water` and `ndvi` map polygon_id to an outcome. Ramsar polygons default to
    "pass" and waterbody polygons to "dea_fail", which fails both live checks
    well outside the ramsar limits.
    """
    cfg, store, run_id, base = _built_run(fixture_item, fixture_polygon, tmp_path)
    first = base[0]
    extra = [
        AoiPolygon(pid, "extra", layer, first.geometry, first.geometry_4326)
        for pid, layer in [
            *[(pid, "ramsar") for pid in RAMSAR[1:]],
            *[(pid, "dea_waterbody") for pid in DEA],
        ]
    ]
    polygons = [*base, *extra]
    medians = _medians()
    by_median = {value: pid for pid, value in medians.items()}
    water_by = {pid: "pass" for pid in RAMSAR} | {pid: "dea_fail" for pid in DEA}
    ndvi_by = dict(water_by)
    water_by.update(water or {})
    ndvi_by.update(ndvi or {})

    def fake_wo(
        scene: Any, stack: Any, planned: Any, inside: Any, *, polygon_id: str, **_: Any
    ) -> Check:
        passed, agreement, pipeline, wo, diff, wet_passed = WATER_OUTCOMES[
            water_by[polygon_id]
        ]
        return Check(
            WATER,
            passed,
            agreement,
            0.91,
            f"wo.tif#{polygon_id}",
            {
                "item": scene.item_id,
                "polygon_id": polygon_id,
                "agreement_min": 0.91,
                "n_mutually_clear": 1000,
                "wet_area_pipeline": pipeline,
                "wet_area_wo": wo,
                "wet_area_diff_pp": diff,
                "wet_area_max_pp": 5.0,
                "wet_area_passed": wet_passed,
            },
        )

    def fake_ndvi(
        scene: Any,
        stack: Any,
        planned: Any,
        inside: Any,
        *,
        measured_median: float,
        **_: Any,
    ) -> Check:
        pid = by_median[measured_median]
        outcome = ndvi_by[pid]
        dea_median = {
            "pass": measured_median + 0.01,
            "fail": measured_median + 0.30,
            "dea_fail": 0.90,
        }[outcome]
        abs_diff = abs(dea_median - measured_median)
        return Check(
            NDVI,
            outcome == "pass",
            abs_diff,
            0.05,
            f"nbart#{pid}",
            {
                "item": scene.item_id,
                "ndvi_median": measured_median,
                "dea_ndvi_median": dea_median,
                "abs_diff": abs_diff,
            },
        )

    monkeypatch.setattr(run_mod, "stored_ndvi", lambda store, scene: dict(medians))
    monkeypatch.setattr(run_mod, "wo_check", fake_wo)
    monkeypatch.setattr(run_mod, "ndvi_scene_check", fake_ndvi)
    monkeypatch.setattr(
        run_mod,
        "scl_checks",
        lambda scene, reader: [Check("scl_share_water", True, 0.0, 1.0, "fake")],
    )
    monkeypatch.setattr(run_mod, "discovery_checks", _discovery_fake)
    kwargs: dict[str, Any] = {
        "wo_lookup": lambda scene, bbox: "wo.tif",
        "wo_reader_factory": lambda: object(),
        "nbart_lookup": lambda scene, bbox: _nbart_item(),
        "nbart_reader_factory": lambda: object(),
        "pixel_checker": _pixel_fake,
        "es_client": object(),
        "cdse_client": object(),
        "waterbody_polygons": [],
        "docs_dir": tmp_path / "docs",
    }
    return cfg, store, run_id, polygons, kwargs


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    cfg: Any,
    polygons: list[AoiPolygon],
    kwargs: dict[str, Any],
    run_id: str,
) -> Any:
    monkeypatch.setattr(cli, "_load", lambda config: (cfg, polygons))
    monkeypatch.setattr(
        "wetland_change.verify.run.verify_run",
        functools.partial(REAL_VERIFY_RUN, **kwargs),
    )
    return CliRunner().invoke(cli.app, ["verify", "--run-id", run_id])


def _report(store: Any, run_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        store.read_bytes(f"verification/{run_id}.json")
    )
    return payload


def _rows(payload: dict[str, Any], name: str) -> dict[str, dict[str, Any]]:
    return {
        c["detail"]["polygon_id"]: c
        for c in payload["checks"]
        if c["name"] == name and "polygon_id" in c["detail"]
    }


def _line(output: str, prefix: str) -> str:
    lines = [line for line in output.splitlines() if line.startswith(prefix)]
    assert lines, output
    return lines[0]


def test_cli_verify_exits_0_when_only_waterbody_live_rows_fail(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfg, _, run_id, polygons, kwargs = _layered(
        monkeypatch, fixture_item, fixture_polygon, tmp_path
    )
    result = _invoke(monkeypatch, cfg, polygons, kwargs, run_id)
    assert result.exit_code == 0, result.output


def test_verify_report_for_a_waterbody_only_failure(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfg, store, run_id, polygons, kwargs = _layered(
        monkeypatch, fixture_item, fixture_polygon, tmp_path
    )
    REAL_VERIFY_RUN(cfg, store, run_id, polygons=polygons, **kwargs)
    assert _report(store, run_id)["all_passed"] is True


@pytest.mark.parametrize(
    ("water", "ndvi", "check", "polygon_ref"),
    [
        ({"ramsar-52": "agreement_fail"}, {}, WATER, "wo.tif#ramsar-52"),
        ({}, {"ramsar-52": "fail"}, NDVI, "nbart#ramsar-52"),
    ],
    ids=["water", "ndvi"],
)
def test_cli_verify_exits_3_when_a_ramsar_live_row_fails(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
    water: dict[str, str],
    ndvi: dict[str, str],
    check: str,
    polygon_ref: str,
) -> None:
    cfg, _, run_id, polygons, kwargs = _layered(
        monkeypatch, fixture_item, fixture_polygon, tmp_path, water, ndvi
    )
    result = _invoke(monkeypatch, cfg, polygons, kwargs, run_id)
    assert result.exit_code == 3, result.output
    assert polygon_ref in _line(result.output, f"FAIL\t{check}")


def test_cli_verify_warns_on_a_ramsar_wet_area_only_failure(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfg, _, run_id, polygons, kwargs = _layered(
        monkeypatch,
        fixture_item,
        fixture_polygon,
        tmp_path,
        water={"ramsar-52": "wet_only"},
    )
    result = _invoke(monkeypatch, cfg, polygons, kwargs, run_id)
    assert result.exit_code == 0, result.output
    assert "ramsar-52" in _line(result.output, f"warn\t{WATER}")
    assert "1 live water checks failed on wet area alone" in result.output


def test_report_marks_waterbody_rows_advisory(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfg, store, run_id, polygons, kwargs = _layered(
        monkeypatch, fixture_item, fixture_polygon, tmp_path
    )
    REAL_VERIFY_RUN(cfg, store, run_id, polygons=polygons, **kwargs)
    payload = _report(store, run_id)
    water_rows = _rows(payload, WATER)
    ndvi_rows = _rows(payload, NDVI)
    medians = _medians()
    for pid in DEA:
        row = water_rows[pid]
        assert row["passed"] is None
        assert row["measured"] == pytest.approx(0.70)
        assert row["reference"] == f"wo.tif#{pid}"
        assert row["detail"]["layer"] == "dea_waterbody"
        assert row["detail"]["advisory"] is True
        assert row["detail"]["within_ramsar_limit"] is False
        assert row["detail"]["item"]
        row = ndvi_rows[pid]
        assert row["passed"] is None
        assert row["measured"] == pytest.approx(0.90 - medians[pid])
        assert row["reference"] == f"nbart#{pid}"
        assert row["detail"]["layer"] == "dea_waterbody"
        assert row["detail"]["advisory"] is True
        assert row["detail"]["within_ramsar_limit"] is False
        assert row["detail"]["item"]
    assert payload["n_advisory"] == 10
    matrix = {row["row"]: row for row in payload["matrix"]}
    live = matrix["Water extent, live"]
    assert live["status"] == "pass"
    assert (live["n_fail"], live["n_warn"], live["n_advisory"]) == (0, 0, 5)
    assert matrix["NDVI"]["status"] == "pass"
    assert matrix["NDVI"]["n_advisory"] == 5
    assert matrix["End to end"]["status"] == "pass"
    assert len(payload["advisory"]) == 2
    summaries = {s["check"]: s for s in payload["advisory"]}
    water_summary = summaries[WATER]
    assert water_summary["layer"] == "dea_waterbody"
    assert water_summary["n_rows"] == 5
    assert water_summary["n_scored"] == 5
    assert water_summary["n_outside_ramsar_limit"] == 5
    assert water_summary["pooled_agreement"] == pytest.approx(0.70)
    assert water_summary["pooled_wet_gap_pp"] == pytest.approx(80.0)
    ndvi_summary = summaries[NDVI]
    assert ndvi_summary["layer"] == "dea_waterbody"
    assert ndvi_summary["n_rows"] == 5
    assert ndvi_summary["n_outside_ramsar_limit"] == 5
    assert ndvi_summary["median_abs_diff"] == pytest.approx(0.35)


def test_pooled_checks_use_ramsar_rows_only(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfg, store, run_id, polygons, kwargs = _layered(
        monkeypatch, fixture_item, fixture_polygon, tmp_path
    )
    REAL_VERIFY_RUN(cfg, store, run_id, polygons=polygons, **kwargs)
    payload = _report(store, run_id)
    (pooled,) = [c for c in payload["checks"] if c["name"] == POOLED]
    assert pooled["detail"]["layer"] == "ramsar"
    assert pooled["detail"]["n_checks"] == 5
    assert pooled["measured"] == pytest.approx(0.0)
    assert pooled["passed"] is True
    (correlation,) = [c for c in payload["checks"] if c["name"] == CORRELATION]
    assert correlation["detail"]["layer"] == "ramsar"
    assert correlation["detail"]["n_rows"] == 5
    assert len(correlation["detail"]["rows"]) == 5
    assert all(row[1] in RAMSAR for row in correlation["detail"]["rows"])
    assert correlation["measured"] == pytest.approx(1.0)
    assert correlation["passed"] is True


def test_output_lines_summarise_waterbody_rows_once_per_check(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfg, _, run_id, polygons, kwargs = _layered(
        monkeypatch, fixture_item, fixture_polygon, tmp_path
    )
    result = _invoke(monkeypatch, cfg, polygons, kwargs, run_id)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert not [line for line in lines if any(pid in line for pid in DEA)]
    advisory = [line for line in lines if line.startswith("advisory\t")]
    assert len(advisory) == 2
    water = [x for x in advisory if x.startswith(f"advisory\t{WATER}\tdea_waterbody\t")]
    ndvi = [x for x in advisory if x.startswith(f"advisory\t{NDVI}\tdea_waterbody\t")]
    assert len(water) == 1 and len(ndvi) == 1
    assert "pooled agreement" in water[0] and "pooled wet gap" in water[0]
    assert "median absolute difference" in ndvi[0]
    markdown = (tmp_path / "docs" / f"verification-{run_id}.md").read_text()
    markdown_lines = markdown.splitlines()
    assert not [line for line in markdown_lines if any(p in line for p in DEA)]
    assert "## Advisory" in markdown_lines
    table = [
        line
        for line in markdown_lines
        if line.startswith("| ") and "dea_waterbody" in line
    ]
    assert len(table) == 2
    assert any(line.startswith(f"| {WATER} | dea_waterbody |") for line in table)
    assert any(line.startswith(f"| {NDVI} | dea_waterbody |") for line in table)


def test_waterbody_twin_row_matches_its_ramsar_row_but_holds_no_verdict(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfg, store, run_id, base = _built_run(fixture_item, fixture_polygon, tmp_path)
    twin = AoiPolygon(
        "dea-twin", "twin", "dea_waterbody", base[0].geometry, base[0].geometry_4326
    )
    scene = scenes_for_run(cfg, store, run_id)[0]
    stack, _, _, grid = _stack_and_window(scene, fixture_polygon)
    arrays = {
        "red.tif": _dea_dn(stack, stack.red),
        "nir.tif": _dea_dn(stack, stack.nir),
    }
    real_stored = run_mod.stored_ndvi

    def stored_with_twin(store: Any, scene: Any) -> dict[str, float]:
        stored = real_stored(store, scene)
        return {**stored, "dea-twin": stored["ramsar-52"]}

    monkeypatch.setattr(run_mod, "stored_ndvi", stored_with_twin)
    monkeypatch.setattr(run_mod, "discovery_checks", _discovery_fake)
    checks = verify_run(
        cfg,
        store,
        run_id,
        polygons=[*base, twin],
        wo_lookup=lambda scene, bbox: "wo.tif",
        wo_reader_factory=lambda: FakeReader(
            grid=grid, data=np.full((48, 48), WO_WET, np.uint8)
        ),
        nbart_lookup=lambda scene, bbox: _nbart_item(),
        nbart_reader_factory=lambda: DictReader(grid=grid, arrays=arrays),
        pixel_checker=_pixel_fake,
        es_client=object(),
        cdse_client=object(),
        waterbody_polygons=[],
        docs_dir=None,
    )
    for name in (WATER, NDVI):
        rows = {
            c.detail["polygon_id"]: c
            for c in checks
            if c.name == name and "polygon_id" in c.detail
        }
        lake, copy = rows["ramsar-52"], rows["dea-twin"]
        assert lake.passed is not None
        assert copy.passed is None
        assert copy.measured == lake.measured
        assert copy.reference.split("#")[0] == lake.reference.split("#")[0]
        assert copy.detail["within_ramsar_limit"] == lake.passed
        assert copy.detail["layer"] == "dea_waterbody"
        assert copy.advisory is True and lake.advisory is False
        assert {k: v for k, v in copy.detail.items() if k not in ADVISORY_KEYS} == {
            k: v for k, v in lake.detail.items() if k not in ADVISORY_KEYS
        }


def test_scene_level_rows_keep_their_verdict(
    monkeypatch: pytest.MonkeyPatch,
    fixture_item: dict[str, Any],
    fixture_polygon: BaseGeometry,
    tmp_path: Path,
) -> None:
    cfg, store, run_id, polygons, kwargs = _layered(
        monkeypatch, fixture_item, fixture_polygon, tmp_path
    )

    def unreachable(scene: Any, bbox: Any) -> str:
        raise RuntimeError("DEA STAC unreachable")

    kwargs["wo_lookup"] = unreachable
    checks = REAL_VERIFY_RUN(cfg, store, run_id, polygons=polygons, **kwargs)
    (row,) = [c for c in checks if c.name == WATER]
    assert row.errored
    assert "polygon_id" not in row.detail
    assert "advisory" not in row.detail
    assert _report(store, run_id)["n_errored"] >= 1
