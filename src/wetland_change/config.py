"""Pipeline configuration loaded from `config/pipeline.toml`.

The collection is locked to `sentinel-2-c1-l2a`: the older `sentinel-2-l2a`
collection bakes the radiometric offset into some items while still
advertising it in `raster:bands`, so a pipeline that reads offsets from
metadata double-corrects there (design doc, verified facts).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ALLOWED_COLLECTION = "sentinel-2-c1-l2a"


class StacConfig(BaseModel):
    endpoint: str
    collection: str
    cloud_cover_max: float = Field(ge=0.0, le=100.0)
    watermark_overlap_days: int = Field(default=1, ge=0)
    required_assets: list[str] = Field(
        default_factory=lambda: [
            "green",
            "red",
            "nir",
            "swir16",
            "scl",
            "product_metadata",
        ]
    )

    @field_validator("collection")
    @classmethod
    def _only_c1(cls, value: str) -> str:
        if value != ALLOWED_COLLECTION:
            raise ValueError(
                f"collection must be {ALLOWED_COLLECTION!r}; got {value!r}. "
                "The older sentinel-2-l2a collection double-corrects offsets."
            )
        return value


class AoiConfig(BaseModel):
    ramsar_path: Path
    waterbodies_path: Path
    site_prefixes: list[str]
    operation_epsg: int = 32750


class WaterConfig(BaseModel):
    method: Literal["ndwi", "mndwi"] = "ndwi"
    threshold: float = 0.0
    min_valid_fraction: float = Field(default=0.8, ge=0.0, le=1.0)


class OutputConfig(BaseModel):
    root: str


class PipelineConfig(BaseModel):
    stac: StacConfig
    aoi: AoiConfig
    water: WaterConfig
    output: OutputConfig


def load_config(path: Path) -> PipelineConfig:
    """Parse and validate a pipeline TOML file."""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    return PipelineConfig.model_validate(raw)
