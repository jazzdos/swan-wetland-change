from pathlib import Path

import pytest
from pydantic import ValidationError

from wetland_change.config import (
    DEFAULT_CATALOGUE_BASE_URL,
    CatalogueConfig,
    PipelineConfig,
    load_config,
)

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config" / "pipeline.toml"


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


def test_repo_config_catalogue_placeholder() -> None:
    cfg = load_config(REPO_CONFIG)
    assert cfg.catalogue.base_url == "https://example.invalid/swan-wetland-change"


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
