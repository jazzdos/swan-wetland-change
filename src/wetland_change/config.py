"""Pipeline configuration loaded from `config/pipeline.toml`.

The collection is locked to `sentinel-2-c1-l2a`: the older `sentinel-2-l2a`
collection bakes the radiometric offset into some items while still
advertising it in `raster:bands`, so a pipeline that reads offsets from
metadata double-corrects there (design doc, verified facts).

Per-polygon water overrides live in `[water.overrides.<polygon_id>]`
(docs/decisions/0005-per-polygon-water-settings.md).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_COLLECTION = "sentinel-2-c1-l2a"
POLYGON_ID = re.compile(r"(ramsar|dea)-[A-Za-z0-9_]+")
WaterMethod = Literal["ndwi", "mndwi", "scl6"]
DEFAULT_CATALOGUE_BASE_URL = "https://example.invalid/swan-wetland-change"


class StacConfig(BaseModel):
    endpoint: str
    collection: str
    cloud_cover_max: float = Field(ge=0.0, le=100.0)
    watermark_overlap_days: int = Field(default=1, ge=0)
    # Bounds the `created` filter of a run with no daily watermark, so a first
    # run does not page through every scene Earth Search holds.
    initial_lookback_days: int = Field(default=30, ge=1)
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


class WaterSetting(BaseModel):
    """One polygon's water rule.

    Water is the setting's index (ndwi or mndwi) above its threshold, or SCL
    class 6 for method scl6. agreement_min is the pass bar of the
    water_vs_dea_s2_wo check.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: WaterMethod
    threshold: float | None = Field(default=None, ge=-1.0, le=1.0)
    agreement_min: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _threshold_matches_method(self) -> Self:
        if self.method == "scl6" and self.threshold is not None:
            raise ValueError("method 'scl6' counts SCL class 6 and takes no threshold")
        if self.method != "scl6" and self.threshold is None:
            raise ValueError(f"method {self.method!r} needs a threshold")
        return self


class WaterConfig(BaseModel):
    """Global water setting plus per-polygon overrides by polygon id (decision 0005)."""

    method: Literal["ndwi", "mndwi"] = "ndwi"
    threshold: float = Field(default=0.0, ge=-1.0, le=1.0)
    min_valid_fraction: float = Field(default=0.8, ge=0.0, le=1.0)
    agreement_min: float = Field(default=0.91, ge=0.0, le=1.0)
    overrides: dict[str, WaterSetting] = Field(default_factory=dict)

    @field_validator("overrides")
    @classmethod
    def _polygon_ids(cls, value: dict[str, WaterSetting]) -> dict[str, WaterSetting]:
        for key in value:
            if POLYGON_ID.fullmatch(key) is None:
                raise ValueError(
                    f"override key {key!r} is not a polygon id like "
                    "'ramsar-15' or 'dea-<uid>'"
                )
        return value

    def for_polygon(self, polygon_id: str | None) -> WaterSetting:
        """The polygon's override, else the global setting."""
        if polygon_id is not None and polygon_id in self.overrides:
            return self.overrides[polygon_id]
        return WaterSetting(
            method=self.method,
            threshold=self.threshold,
            agreement_min=self.agreement_min,
        )


class OutputConfig(BaseModel):
    root: str


class CatalogueConfig(BaseModel):
    base_url: str

    @field_validator("base_url")
    @classmethod
    def _https_no_trailing_slash(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError(f"base_url must start with 'https://'; got {value!r}")
        return value.rstrip("/")


class WaterbodiesVerifyConfig(BaseModel):
    """Tolerances of the DEA Waterbodies history check."""

    tolerance_pp: float = Field(default=10.0, gt=0.0, le=100.0)  # wet fraction, pp
    max_day_gap: int = Field(default=3, ge=1)  # days between the two passes
    spearman_min: float = Field(default=0.9, ge=0.0, le=1.0)
    spearman_min_pairs: int = Field(default=10, ge=3)
    # Days of stored observations the Spearman check scores over, ending at the
    # newest scene of the verified run.
    history_days: int = Field(default=365, ge=1)


class VerifyConfig(BaseModel):
    # Mutually clear pixels a polygon needs before the WO and NDVI checks score
    # it. Pixels are 10 m, so 100 is 1 ha. Below it the check is a reason skip.
    min_clear_pixels: int = Field(default=100, ge=1)
    waterbodies: WaterbodiesVerifyConfig = Field(
        default_factory=WaterbodiesVerifyConfig
    )


class PipelineConfig(BaseModel):
    stac: StacConfig
    aoi: AoiConfig
    water: WaterConfig
    output: OutputConfig
    catalogue: CatalogueConfig = Field(
        default_factory=lambda: CatalogueConfig(base_url=DEFAULT_CATALOGUE_BASE_URL)
    )
    verify: VerifyConfig = Field(default_factory=VerifyConfig)


def load_config(path: Path) -> PipelineConfig:
    """Parse and validate a pipeline TOML file."""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    return PipelineConfig.model_validate(raw)
