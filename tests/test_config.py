import hashlib
import re
from pathlib import Path

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
    assert cfg.water.agreement_min == 0.91
    assert set(cfg.water.overrides) == {"ramsar-15", "ramsar-28", "ramsar-56"}
    scl6 = cfg.water.overrides["ramsar-15"]
    assert scl6 == WaterSetting(method="scl6", agreement_min=0.94)
    assert scl6.threshold is None
    assert cfg.water.overrides["ramsar-28"] == WaterSetting(
        method="ndwi", threshold=-0.15, agreement_min=0.92
    )
    assert cfg.water.overrides["ramsar-56"] == WaterSetting(
        method="mndwi", threshold=0.05, agreement_min=0.95
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
