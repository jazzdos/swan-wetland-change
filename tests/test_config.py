import csv
import hashlib
import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError

from wetland_change.config import (
    DEFAULT_CATALOGUE_BASE_URL,
    CatalogueConfig,
    PipelineConfig,
    VerifyConfig,
    WaterbodiesVerifyConfig,
    WaterConfig,
    WaterSetting,
    load_config,
)

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config" / "pipeline.toml"
DECISIONS = REPO_CONFIG.parents[1] / "docs" / "decisions"
# ADR 0007: lowest whole-history per-lake rho 0.8555 minus 0.02, rounded down.
SPEARMAN_MIN = 0.83
SHA_LINE = r"`(docs/research/[^`]+)` sha256 `([0-9a-f]{64})`"


def test_load_repo_config() -> None:
    cfg = load_config(REPO_CONFIG)
    assert isinstance(cfg, PipelineConfig)
    assert cfg.stac.collection == "sentinel-2-c1-l2a"
    assert cfg.stac.cloud_cover_max == 20.0
    assert cfg.aoi.operation_epsg == 32750
    assert cfg.water.method == "mndwi"
    assert cfg.water.threshold == -0.1
    assert "scl" in cfg.stac.required_assets


def test_rejects_other_collections(tmp_path: Path) -> None:
    text = REPO_CONFIG.read_text().replace(
        'collection = "sentinel-2-c1-l2a"', 'collection = "sentinel-2-l2a"'
    )
    bad = tmp_path / "pipeline.toml"
    bad.write_text(text)
    with pytest.raises(ValueError, match="sentinel-2-c1-l2a"):
        load_config(bad)


def test_rejects_cloud_cover_out_of_range(tmp_path: Path) -> None:
    text = REPO_CONFIG.read_text().replace(
        "cloud_cover_max = 20.0", "cloud_cover_max = 120"
    )
    bad = tmp_path / "pipeline.toml"
    bad.write_text(text)
    with pytest.raises(ValueError):
        load_config(bad)


def test_repo_config_catalogue_base_url_is_https_without_trailing_slash() -> None:
    base_url = load_config(REPO_CONFIG).catalogue.base_url
    assert base_url.startswith("https://")
    assert not base_url.endswith("/")


@pytest.mark.parametrize("url", ["http://x.test", "s3://bucket"])
def test_catalogue_rejects_non_https(url: str) -> None:
    with pytest.raises(ValidationError, match="https://"):
        CatalogueConfig(base_url=url)


def test_catalogue_strips_trailing_slashes() -> None:
    assert CatalogueConfig(base_url="https://x.test/path/").base_url == (
        "https://x.test/path"
    )


def test_missing_catalogue_section_uses_default(tmp_path: Path) -> None:
    text = REPO_CONFIG.read_text().split("[catalogue]")[0]
    path = tmp_path / "pipeline.toml"
    path.write_text(text)
    cfg = load_config(path)
    assert cfg.catalogue.base_url == DEFAULT_CATALOGUE_BASE_URL


def test_repo_config_water_overrides_match_learnings() -> None:
    cfg = load_config(REPO_CONFIG)
    adr = _adr_0010_decision()
    expected_ids = {"ramsar-15", "ramsar-28", "ramsar-56"}
    if adr["outcome"] == "override":
        expected_ids.add("ramsar-12")
    assert cfg.water.agreement_min == 0.91
    assert set(cfg.water.overrides) == expected_ids
    scl6 = cfg.water.overrides["ramsar-15"]
    assert scl6 == WaterSetting(method="scl6", agreement_min=0.94)
    assert scl6.threshold is None
    assert cfg.water.overrides["ramsar-28"] == WaterSetting(
        method="ndwi", threshold=-0.15, agreement_min=0.92
    )
    assert cfg.water.overrides["ramsar-56"] == WaterSetting(
        method="mndwi", threshold=0.05, agreement_min=0.95
    )
    if adr["outcome"] == "override":
        assert cfg.water.overrides["ramsar-12"] == WaterSetting(
            method="mndwi",
            threshold=adr["threshold"],
            agreement_min=adr["agreement_min"],
        )


def test_for_polygon_falls_back_to_global() -> None:
    water: WaterConfig = load_config(REPO_CONFIG).water
    expected = WaterSetting(method="mndwi", threshold=-0.1, agreement_min=0.91)
    assert water.for_polygon("ramsar-52") == expected
    assert water.for_polygon(None) == expected
    assert water.for_polygon("ramsar-28") == water.overrides["ramsar-28"]


@pytest.mark.parametrize(
    "snippet",
    [
        pytest.param(
            '[water.overrides.ramsar-99]\nmethod = "ndvi"\nthreshold = 0.0\n'
            "agreement_min = 0.9\n",
            id="unknown-method",
        ),
        pytest.param(
            '[water.overrides.ramsar-99]\nmethod = "ndwi"\nthreshold = 1.5\n'
            "agreement_min = 0.9\n",
            id="threshold-above-1",
        ),
        pytest.param(
            '[water.overrides.ramsar-99]\nmethod = "mndwi"\nthreshold = -1.5\n'
            "agreement_min = 0.9\n",
            id="threshold-below-minus-1",
        ),
        pytest.param(
            '[water.overrides.ramsar-99]\nmethod = "scl6"\nthreshold = 0.0\n'
            "agreement_min = 0.9\n",
            id="scl6-with-threshold",
        ),
        pytest.param(
            '[water.overrides.ramsar-99]\nmethod = "ndwi"\nagreement_min = 0.9\n',
            id="index-method-without-threshold",
        ),
        pytest.param(
            '[water.overrides.ramsar-99]\nmethod = "ndwi"\nthreshold = 0.0\n'
            "agreement_min = 1.2\n",
            id="agreement-min-above-1",
        ),
        pytest.param(
            '[water.overrides.ramsar-99]\nmethod = "scl6"\nagreement_min = 0.9\n'
            "threshhold = 0.1\n",
            id="misspelt-extra-key",
        ),
        pytest.param(
            '[water.overrides."ramsar 99"]\nmethod = "scl6"\nagreement_min = 0.9\n',
            id="bad-polygon-id",
        ),
        pytest.param(
            '[water.overrides.ramsar-99]\nmethod = "ndwi"\nthreshold = 0.0\n',
            id="missing-agreement-min",
        ),
    ],
)
def test_override_rejected(tmp_path: Path, snippet: str) -> None:
    bad = tmp_path / "pipeline.toml"
    bad.write_text(REPO_CONFIG.read_text() + "\n" + snippet)
    with pytest.raises(ValidationError):
        load_config(bad)


@pytest.mark.parametrize("value", [-1.0, 1.0])
def test_override_accepts_threshold_bounds(tmp_path: Path, value: float) -> None:
    path = tmp_path / "pipeline.toml"
    snippet = (
        "[water.overrides.ramsar-99]\n"
        'method = "ndwi"\n'
        f"threshold = {value}\n"
        "agreement_min = 0.9\n"
    )
    path.write_text(REPO_CONFIG.read_text() + "\n" + snippet)
    assert load_config(path).water.overrides["ramsar-99"].threshold == value


def test_global_threshold_out_of_range_rejected(tmp_path: Path) -> None:
    text = REPO_CONFIG.read_text().replace("threshold = -0.1\n", "threshold = 1.5\n", 1)
    bad = tmp_path / "pipeline.toml"
    bad.write_text(text)
    with pytest.raises(ValidationError):
        load_config(bad)


LEARNINGS = Path(__file__).resolve().parents[1] / "LEARNINGS.md"
S9_HEADING = "### S9 historical tolerance"


def test_repo_config_waterbodies_verify_values() -> None:
    cfg = load_config(REPO_CONFIG)
    wb = cfg.verify.waterbodies
    assert wb.tolerance_pp == 10.0
    assert wb.max_day_gap == 3
    assert wb.spearman_min == SPEARMAN_MIN
    assert wb.spearman_min_pairs == 10
    assert WaterbodiesVerifyConfig().spearman_min == SPEARMAN_MIN


def test_spearman_min_matches_adr_0007() -> None:
    adrs = list(DECISIONS.glob("0007-*.md"))
    assert len(adrs) == 1, f"expected one docs/decisions/0007-*.md, found {adrs}"
    text = adrs[0].read_text()
    decision = text.split("\n## Decision", 1)[1].split("\n## ", 1)[0]
    match = re.search(r"^spearman_min = (\d+(?:\.\d+)?)$", decision, re.MULTILINE)
    assert match is not None, "no 'spearman_min = <value>' line in the Decision section"
    assert (
        float(match.group(1))
        == load_config(REPO_CONFIG).verify.waterbodies.spearman_min
    )


def test_adr_0007_recorded_sha256_match_committed_research_files() -> None:
    adrs = list(DECISIONS.glob("0007-*.md"))
    assert len(adrs) == 1
    recorded = dict(re.findall(SHA_LINE, adrs[0].read_text()))
    for name in (
        "docs/research/2026-11-06-spearman-calibration.py",
        "docs/research/2026-11-06-spearman-calibration.csv",
    ):
        assert name in recorded, f"ADR 0007 records no sha256 for {name}"
    for name, digest in recorded.items():
        actual = hashlib.sha256(
            (REPO_CONFIG.parents[1] / name).read_bytes()
        ).hexdigest()
        assert digest == actual, f"ADR 0007 sha256 for {name} is stale"


def test_adr_0008_recorded_sha256_match_committed_research_files() -> None:
    adrs = list(DECISIONS.glob("0008-*.md"))
    assert len(adrs) == 1, f"expected one docs/decisions/0008-*.md, found {adrs}"
    recorded = dict(re.findall(SHA_LINE, adrs[0].read_text()))
    for name in (
        "docs/research/2026-11-06-exit-rule-shares.py",
        "docs/research/2026-11-06-exit-rule-shares.csv",
        "docs/research/2026-11-06-ramsar-12-gap.py",
        "docs/research/2026-11-06-ramsar-12-gap.csv",
        "docs/research/2026-11-05-wet-area-gap.csv",
    ):
        assert name in recorded, f"ADR 0008 records no sha256 for {name}"
    for name, digest in recorded.items():
        actual = hashlib.sha256(
            (REPO_CONFIG.parents[1] / name).read_bytes()
        ).hexdigest()
        assert digest == actual, f"ADR 0008 sha256 for {name} is stale"


def _load_exit_rule_script() -> ModuleType:
    path = (
        REPO_CONFIG.parents[1] / "docs" / "research" / "2026-11-06-exit-rule-shares.py"
    )
    spec = importlib.util.spec_from_file_location("exit_rule_shares", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_adr_0008_shares_match_recomputation() -> None:
    adrs = list(DECISIONS.glob("0008-*.md"))
    assert len(adrs) == 1, f"expected one docs/decisions/0008-*.md, found {adrs}"
    text = adrs[0].read_text()
    stated = {
        candidate: (int(failing), int(total))
        for candidate, failing, total in re.findall(
            r"^Measured dates failing under (K\d): (\d+) of (\d+)$",
            text,
            re.MULTILINE,
        )
    }
    assert sorted(stated) == ["K1", "K2", "K3", "K4"]
    match = re.search(r"^Chosen rule: (K\d)$", text, re.MULTILINE)
    assert match is not None, "no 'Chosen rule: K<n>' line in ADR 0008"

    script = _load_exit_rule_script()
    rows = script.load_rows(
        REPO_CONFIG.parents[1] / "docs" / "research" / "2026-11-05-wet-area-gap.csv"
    )
    result = script.choose(script.date_outcomes(rows))
    measured_total = sum(1 for o in script.date_outcomes(rows) if o["measured"])
    for candidate, (failing, total) in stated.items():
        assert result["counts"][candidate] == failing, candidate
        assert total == measured_total, candidate
    assert result["chosen"] == match.group(1)


def test_adr_0009_recorded_sha256_match_committed_research_files() -> None:
    adrs = list(DECISIONS.glob("0009-*.md"))
    assert len(adrs) == 1, f"expected one docs/decisions/0009-*.md, found {adrs}"
    recorded = dict(re.findall(SHA_LINE, adrs[0].read_text()))
    for name in (
        "docs/research/2026-11-06-wo-availability.py",
        "docs/research/2026-11-06-wo-availability.csv",
    ):
        assert name in recorded, f"ADR 0009 records no sha256 for {name}"
    for name, digest in recorded.items():
        actual = hashlib.sha256(
            (REPO_CONFIG.parents[1] / name).read_bytes()
        ).hexdigest()
        assert digest == actual, f"ADR 0009 sha256 for {name} is stale"


def _load_wo_availability_script() -> ModuleType:
    path = (
        REPO_CONFIG.parents[1] / "docs" / "research" / "2026-11-06-wo-availability.py"
    )
    spec = importlib.util.spec_from_file_location("wo_availability", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_adr_0009_availability_matches_recomputation() -> None:
    adrs = list(DECISIONS.glob("0009-*.md"))
    assert len(adrs) == 1, f"expected one docs/decisions/0009-*.md, found {adrs}"
    text = adrs[0].read_text()
    share = re.search(
        r"^Share available at first processing: (\d+) of (\d+)$", text, re.MULTILINE
    )
    assert share is not None, "no 'Share available at first processing: K of N' line"
    chosen = re.search(r"^Chosen outcome: (populate|amend)$", text, re.MULTILINE)
    assert chosen is not None, "no 'Chosen outcome: populate|amend' line in ADR 0009"

    script = _load_wo_availability_script()
    rows = script.load_rows(
        REPO_CONFIG.parents[1] / "docs" / "research" / "2026-11-06-wo-availability.csv"
    )
    summary = script.summarise_rows(rows)
    assert summary["n_available"] == int(share.group(1))
    assert summary["n"] == int(share.group(2))
    assert script.decide(summary) == chosen.group(1)

    learnings = (REPO_CONFIG.parents[1] / "LEARNINGS.md").read_text()
    outcome = re.search(r"^Outcome: (populate|amend)$", learnings, re.MULTILINE)
    assert outcome is not None, "no 'Outcome: populate|amend' line in LEARNINGS.md"
    assert outcome.group(1) == chosen.group(1)


def test_waterbodies_tolerance_matches_learnings() -> None:
    text = LEARNINGS.read_text()
    assert S9_HEADING in text, f"LEARNINGS.md has no {S9_HEADING!r} heading"
    section = text.split(S9_HEADING, 1)[1]
    match = re.search(r"Chosen tolerance: (\d+(?:\.\d+)?) percentage points", section)
    assert match is not None, (
        f"no 'Chosen tolerance: N percentage points' sentence after {S9_HEADING!r}"
    )
    cfg = load_config(REPO_CONFIG)
    assert float(match.group(1)) == cfg.verify.waterbodies.tolerance_pp


def test_missing_verify_section_uses_defaults(tmp_path: Path) -> None:
    text = REPO_CONFIG.read_text().split("[verify]")[0]
    assert "[verify" not in text
    path = tmp_path / "pipeline.toml"
    path.write_text(text)
    cfg = load_config(path)
    assert cfg.verify.waterbodies == WaterbodiesVerifyConfig(
        tolerance_pp=10.0,
        max_day_gap=3,
        spearman_min=SPEARMAN_MIN,
        spearman_min_pairs=10,
    )


def test_waterbodies_tolerance_zero_rejected(tmp_path: Path) -> None:
    text = REPO_CONFIG.read_text().replace("tolerance_pp = 10.0", "tolerance_pp = 0")
    path = tmp_path / "pipeline.toml"
    path.write_text(text)
    with pytest.raises(ValidationError, match="tolerance_pp"):
        load_config(path)


def test_min_clear_pixels_default_and_repo_value() -> None:
    assert VerifyConfig().min_clear_pixels == 100
    assert load_config(REPO_CONFIG).verify.min_clear_pixels == 100


def test_min_clear_pixels_zero_rejected(tmp_path: Path) -> None:
    text = REPO_CONFIG.read_text().replace(
        "min_clear_pixels = 100", "min_clear_pixels = 0"
    )
    path = tmp_path / "pipeline.toml"
    path.write_text(text)
    with pytest.raises(ValidationError, match="min_clear_pixels"):
        load_config(path)


def test_waterbodies_has_no_history_days_field() -> None:
    assert "history_days" not in WaterbodiesVerifyConfig.model_fields
    cfg = load_config(REPO_CONFIG)
    assert not hasattr(cfg.verify.waterbodies, "history_days")


RESEARCH = REPO_CONFIG.parents[1] / "docs" / "research"
RAMSAR_12_CONFIRM_PREFIX = "2026-11-06-ramsar-12-confirm"


def _adr_0010_text() -> str:
    adrs = list(DECISIONS.glob("0010-*.md"))
    assert len(adrs) == 1, f"expected one docs/decisions/0010-*.md, found {adrs}"
    return adrs[0].read_text()


def _adr_0010_decision() -> dict[str, Any]:
    """The outcome, threshold and agreement_min lines of ADR 0010."""
    text = _adr_0010_text()
    chosen = re.search(r"^Chosen outcome: (override|keep-global)$", text, re.MULTILINE)
    assert chosen is not None, "no 'Chosen outcome: override|keep-global' line"
    decision: dict[str, Any] = {
        "outcome": chosen.group(1),
        "threshold": None,
        "agreement_min": None,
    }
    if decision["outcome"] == "override":
        threshold = re.search(r"^threshold = (-?\d+(?:\.\d+)?)$", text, re.MULTILINE)
        floor = re.search(r"^agreement_min = (\d+(?:\.\d+)?)$", text, re.MULTILINE)
        assert threshold is not None, "no 'threshold = <value>' line in ADR 0010"
        assert floor is not None, "no 'agreement_min = <value>' line in ADR 0010"
        decision["threshold"] = float(threshold.group(1))
        decision["agreement_min"] = float(floor.group(1))
    return decision


def test_adr_0010_recorded_sha256_match_committed_research_files() -> None:
    recorded = dict(re.findall(SHA_LINE, _adr_0010_text()))
    for name in (
        f"docs/research/{RAMSAR_12_CONFIRM_PREFIX}.py",
        f"docs/research/{RAMSAR_12_CONFIRM_PREFIX}.csv",
    ):
        assert name in recorded, f"ADR 0010 records no sha256 for {name}"
    for name, digest in recorded.items():
        actual = hashlib.sha256(
            (REPO_CONFIG.parents[1] / name).read_bytes()
        ).hexdigest()
        assert digest == actual, f"ADR 0010 sha256 for {name} is stale"


def _load_ramsar_12_confirm_script() -> ModuleType:
    path = RESEARCH / f"{RAMSAR_12_CONFIRM_PREFIX}.py"
    spec = importlib.util.spec_from_file_location("ramsar_12_confirm_adr_0010", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_adr_0010_outcome_matches_recomputation() -> None:
    adr = _adr_0010_decision()
    script = _load_ramsar_12_confirm_script()
    confirm_rows = script.load_rows(RESEARCH / f"{RAMSAR_12_CONFIRM_PREFIX}.csv")
    seen_rows = script.load_rows(RESEARCH / "2026-11-06-ramsar-12-gap.csv")
    decision = script.decide(confirm_rows, seen_rows)
    assert decision.outcome == adr["outcome"]
    assert decision.threshold == adr["threshold"]
    assert decision.agreement_min == adr["agreement_min"]

    learnings = (REPO_CONFIG.parents[1] / "LEARNINGS.md").read_text()
    outcome = re.search(r"^Outcome: (override|keep-global)$", learnings, re.MULTILINE)
    assert outcome is not None, (
        "no 'Outcome: override|keep-global' line in LEARNINGS.md"
    )
    assert outcome.group(1) == decision.outcome


def test_repo_config_ramsar_12_matches_adr_0010() -> None:
    adr = _adr_0010_decision()
    water = load_config(REPO_CONFIG).water
    if adr["outcome"] == "override":
        expected = WaterSetting(
            method="mndwi",
            threshold=adr["threshold"],
            agreement_min=adr["agreement_min"],
        )
        assert water.overrides["ramsar-12"] == expected
        assert water.for_polygon("ramsar-12") == expected
    else:
        assert "ramsar-12" not in water.overrides
        assert water.for_polygon("ramsar-12") == WaterSetting(
            method="mndwi", threshold=-0.1, agreement_min=0.91
        )


def test_adr_0010_states_delegation_and_review_status() -> None:
    text = _adr_0010_text()
    assert "decided under delegation" in text
    status = next(line for line in text.splitlines() if line.startswith("Status:"))
    assert re.search(
        r"pending Jarrod's review|approved by Jarrod on \d{4}-\d{2}-\d{2}",
        status,
    )


def _adr_0012_path() -> Path:
    adrs = list(DECISIONS.glob("0012-*.md"))
    assert len(adrs) == 1, f"expected one docs/decisions/0012-*.md, found {adrs}"
    return adrs[0]


def test_adr_0012_recorded_sha256_match_committed_research_files() -> None:
    recorded = dict(re.findall(SHA_LINE, _adr_0012_path().read_text()))
    for name in (
        "docs/research/2026-11-12-live-check-layers.py",
        "docs/research/2026-11-12-live-check-layers.csv",
        "docs/research/2026-11-12-live-check-layers.txt",
        "docs/research/2026-11-12-issue-2-repro-20261111.json",
        "docs/research/2026-11-12-issue-2-repro-20261029.json",
    ):
        assert name in recorded, f"ADR 0012 records no sha256 for {name}"
    for name, digest in recorded.items():
        actual = hashlib.sha256(
            (REPO_CONFIG.parents[1] / name).read_bytes()
        ).hexdigest()
        assert digest == actual, f"ADR 0012 sha256 for {name} is stale"


def _load_layers_script() -> ModuleType:
    path = (
        REPO_CONFIG.parents[1] / "docs" / "research" / "2026-11-12-live-check-layers.py"
    )
    spec = importlib.util.spec_from_file_location("live_check_layers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_adr_0012_layer_counts_match_recomputation() -> None:
    script = _load_layers_script()
    research = REPO_CONFIG.parents[1] / "docs" / "research"
    payloads = {
        label: script.load_payload(path)
        for label, path in script.DEFAULT_INPUTS.items()
    }
    rows = [
        row
        for label, payload in payloads.items()
        for row in script.summarise(label, payload)
    ]
    with (research / "2026-11-12-live-check-layers.csv").open(newline="") as handle:
        committed = list(csv.DictReader(handle))
    assert rows == committed
    assert (
        script.report_text(script.DEFAULT_INPUTS)
        == (research / "2026-11-12-live-check-layers.txt").read_text()
    )

    def pick(
        label: str, check: str, layer: str, size_bin: str = "all"
    ) -> dict[str, str]:
        (row,) = [
            r
            for r in committed
            if (r["label"], r["check"], r["layer"], r["size_bin"])
            == (label, check, layer, size_bin)
        ]
        return row

    water = "water_vs_dea_s2_wo"
    ramsar_water = pick("2026-11-11", water, "ramsar")
    assert ramsar_water["n_fail"] == "1"
    assert ramsar_water["n_warn"] == "5"
    waterbody_water = pick("2026-11-11", water, "dea_waterbody")
    assert waterbody_water["n_fail"] == "262"
    assert waterbody_water["n_pass"] == "290"
    ndvi = "ndvi_vs_dea_nbart"
    assert float(pick("2026-10-29", ndvi, "all")["pearson"]) < 0.95
    assert float(pick("2026-10-29", ndvi, "ramsar")["pearson"]) >= 0.95

    for label, payload in payloads.items():
        by_name = {c["name"]: c for c in payload["checks"]}
        pooled = by_name["water_vs_dea_s2_wo_pooled_wet_area"]["measured"]
        corr = by_name["ndvi_correlation_vs_dea_nbart"]["measured"]
        assert float(pick(label, water, "all")["pooled_wet_gap_pp"]) == pytest.approx(
            pooled, abs=1e-4
        )
        assert float(pick(label, ndvi, "all")["pearson"]) == pytest.approx(
            corr, abs=1e-4
        )


def test_adr_0012_status_and_rule_path() -> None:
    from wetland_change.verify.layers import LAYER_RULE

    path = _adr_0012_path()
    status = next(
        line for line in path.read_text().splitlines() if line.startswith("Status:")
    )
    assert "decided by the orchestrator on 2026-11-12" in status
    assert "approved by Jarrod on 2026-11-14" in status
    assert "not yet approved" not in status
    rule = REPO_CONFIG.parents[1] / LAYER_RULE
    assert rule.exists()
    assert rule.name == path.name
