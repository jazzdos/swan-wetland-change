# Swan Wetland Change Pipeline, Milestone 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use kit:build-flow to execute this plan.

**Goal:** Build the scheduled-ready core of the pipeline: discover new Sentinel-2 Collection 1 scenes over the Ramsar wetlands, read only the needed COG windows, compute NDWI, MNDWI and NDVI per wetland, write GeoParquet observations and a ledger to a configurable output root, and verify every step against its known-good reference.

**Architecture:** One `src/wetland_change` package with one module per run stage (search, windows, read, indices, mask, stats, geoparquet, ledger, pipeline, verify) and a typer CLI. Every stage is a pure function over arrays or dicts so tests run offline on a committed 64-pixel fixture; network reaches only the `scripts/` fetchers, the `live` marked tests and the spikes. Output storage is a pyarrow filesystem so the same code writes to a local directory now and S3 in Milestone 2.

**Tech Stack:** Python 3.12, uv, pydantic 2, pystac-client 0.9, rasterio 1.5, numpy 2, shapely 2.2, geopandas 1.2 (GeoParquet 1.1 with covering bbox), pyarrow 26, stac-geoparquet 0.8, duckdb 2, typer, pytest, ruff, mypy strict. Dev oracles: spyndex 0.12, geoparquet-validator 0.2, planetary-computer 1.0.

**Design:** `docs/plans/2026-10-29-swan-wetland-change-design.md`. Read its verified facts and verification matrix before starting.

**Out of scope for this milestone (Milestone 2 plan):** change detection and backfill, the pystac catalogue, S3 bucket and OIDC infrastructure, the cron and verify workflows, the Copernicus, DEA Waterbodies, NBART and STAC rows of the matrix, README for reviewers.

**Conventions for every task:**
- Run commands from the worktree root `~/Documents/swan-wetland-change/.worktrees/feature/wetland-change-pipeline`.
- Tests: `uv run pytest -q <path>::<name>`. Live tests are marked `@pytest.mark.live` and are deselected by default (`-m "not live"` in `addopts`); run them with `uv run pytest -q -m live <path>`.
- After each task: `uv run ruff check src tests scripts && uv run ruff format src tests scripts && uv run mypy src scripts`.
- No commit steps. Jarrod controls commits.
- Spike tasks (Tasks 23 to 27) are scratch work exempt from TDD per the research-code profile; their outputs are LEARNINGS.md entries and config values.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `.python-version`, `src/wetland_change/__init__.py`, `src/wetland_change/py.typed`, `tests/__init__.py`, `tests/test_smoke.py`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `LEARNINGS.md`, `data/SOURCES.md`, `config/pipeline.toml`, `docs/decisions/.gitkeep`, `docs/handoffs/.gitkeep`, `docs/research/.gitkeep`, `scripts/__init__.py`
- Modify: `.gitignore`

**Step 1: Write the failing smoke test**

`tests/test_smoke.py`:
```python
"""Package imports and exposes a version."""

import wetland_change


def test_package_has_version() -> None:
    assert wetland_change.__version__ == "0.1.0"
```

**Step 2: Run it to verify it fails**

Run: `uv run pytest -q tests/test_smoke.py`
Expected: FAIL (no pyproject yet, uv errors with "No `pyproject.toml` found" or ModuleNotFoundError).

**Step 3: Write the project files**

`pyproject.toml`:
```toml
[project]
name = "swan-wetland-change"
version = "0.1.0"
description = "Scheduled incremental NDWI and NDVI change detection for Swan Coastal Plain Ramsar wetlands from Earth Search Sentinel-2 COGs"
requires-python = ">=3.12"
dependencies = [
    "duckdb>=2.0",
    "geopandas>=1.2",
    "numpy>=2.0",
    "pyarrow>=26",
    "pydantic>=2.0,<3",
    "pyogrio>=0.10",
    "pyproj>=3.8",
    "pystac>=1.15",
    "pystac-client>=0.9",
    "rasterio>=1.5",
    "requests>=2.32",
    "shapely>=2.2",
    "stac-geoparquet>=0.8",
    "typer>=0.12",
    "urllib3>=2.0",
]

[project.scripts]
wetland-change = "wetland_change.cli:app"

[dependency-groups]
dev = [
    "geoparquet-validator>=0.2",
    "mypy>=1.10",
    "planetary-computer>=1.0",
    "pytest>=8.0",
    "ruff>=0.6",
    "spyndex>=0.12",
    "types-requests>=2.32",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/wetland_change"]

[tool.pytest.ini_options]
testpaths = ["tests"]
xfail_strict = true
addopts = "-q -m 'not live'"
markers = [
    "live: hits a network service; run with -m live",
]

[tool.ruff]
line-length = 88
src = ["src", "tests", "scripts"]
extend-exclude = ["notebooks", "scratch"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.mypy]
strict = true
files = ["src", "scripts"]
exclude = ["notebooks", "scratch"]

[[tool.mypy.overrides]]
module = [
    "affine", "affine.*",
    "duckdb", "duckdb.*",
    "geopandas", "geopandas.*",
    "pandas", "pandas.*",
    "planetary_computer", "planetary_computer.*",
    "pyarrow", "pyarrow.*",
    "pyogrio", "pyogrio.*",
    "pyproj", "pyproj.*",
    "pystac", "pystac.*",
    "pystac_client", "pystac_client.*",
    "rasterio", "rasterio.*",
    "shapely", "shapely.*",
    "spyndex", "spyndex.*",
    "stac_geoparquet", "stac_geoparquet.*",
]
ignore_missing_imports = true
```

`.python-version`:
```
3.12
```

`src/wetland_change/__init__.py`:
```python
"""Scheduled incremental wetland change detection from Sentinel-2 COGs."""

__version__ = "0.1.0"
```

`src/wetland_change/py.typed`: empty file.
`tests/__init__.py`: empty file.
`scripts/__init__.py`: empty file.

`.gitignore` (replace the `data/` line so `data/SOURCES.md` is tracked):
```
.worktrees/
.env
MACHINES.md
data/*
!data/SOURCES.md
outputs/
*.log
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
```

`CLAUDE.md`:
```markdown
profile: research-code
status: active
standards: ~/Documents/standards/STANDARDS.md

@AGENTS.md
```

`AGENTS.md`:
```markdown
# swan-wetland-change

Scheduled, incremental NDWI and NDVI change detection for the Swan Coastal
Plain Ramsar wetlands from Earth Search Sentinel-2 Collection 1 COGs, with
every output verified against an independent reference.
Design: `docs/plans/2026-10-29-swan-wetland-change-design.md`.

## Verification

Run in this order, one command per line, so a failure names its step:

```
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src scripts
uv run pytest -q
```

Live tests (`-m live`) hit Earth Search, Planetary Computer and DEA. Run them
before a handoff, never in the default suite.

A deliberately red test is marked `xfail(strict=True)`.

## Layout

```text
CLAUDE.md  AGENTS.md  README.md  LEARNINGS.md  pyproject.toml  uv.lock
config/pipeline.toml  src/wetland_change/  tests/  scripts/  scratch/
data/SOURCES.md  data/external/ (untracked)  outputs/ (untracked)
docs/{plans,decisions,handoffs,research}/
```

## Rules

- Every dataset gets a row in `data/SOURCES.md` (URL, licence, fetch date,
  checksum, CRS, redistribute_public) in the commit that first uses it.
- Reflectance is always DN times scale plus offset read from the item's
  `raster:bands`, never a hard-coded constant, and checked against the ESA
  product XML at run time.
- Only collection `sentinel-2-c1-l2a`. Never mix in `sentinel-2-l2a`.
- Record the source CRS, operation CRS (EPSG:32750) and units with every
  output.
- Pre-registered hypotheses live in `LEARNINGS.md` before a run tests them.

## Locked decisions

- Sentinel-2 Collection 1 only; Landsat is requester-pays on Earth Search.
- Ramsar sites (DBCA-010, CC BY-SA 4.0) are the reporting unit; DEA
  Waterbodies polygons (CC BY 4.0) are the verification unit.
- Water area is stored three ways: calibrated index, SCL class 6, and the
  DEA Water Observations agreement score.
```

`README.md`:
```markdown
# swan-wetland-change

Scheduled, incremental wetland change detection for the Swan Coastal Plain
Ramsar sites from Sentinel-2 Collection 1 Cloud-Optimized GeoTIFFs on
Earth Search. Outputs are GeoParquet observations per wetland per scene
and a STAC catalogue. Every stage is verified against an independent
known-good reference. Design and verification matrix:
`docs/plans/2026-10-29-swan-wetland-change-design.md`.

## Setup

```
uv sync
uv run python scripts/fetch_aoi.py
uv run wetland-change discover --config config/pipeline.toml
```
```

`LEARNINGS.md`:
```markdown
# Learnings

Pre-registered hypotheses and spike results. Append only; never rewrite a
recorded result.

## Pre-registered hypotheses (design, 2026-10-29)

1. Forrestdale shows a low-water anomaly in December 2023 or January 2024.
   Reference: DEA Waterbodies `qd63n1ww5_v3`, wet fraction 0 from December
   2023 to May 2024. Tested by the Milestone 2 backfill.
2. February to April of 2022 and 2023 at Forrestdale raise no anomaly.
3. Winter 2025 at Forrestdale and Thomsons shows water at or above the
   baseline, with no dry-down flag.
4. Spearman correlation between pipeline water hectares and DEA Waterbodies
   wet fraction on passes within three days is at least 0.9.

## Spike results

(Appended by Tasks 23 to 27.)
```

`data/SOURCES.md`:
```markdown
# Data sources

| source | url | licence | fetched | sha256 | crs | redistribute_public |
|---|---|---|---|---|---|---|
| Earth Search sentinel-2-c1-l2a | https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a | Copernicus Sentinel data terms (free, open) | per run | per item checksum in ledger | EPSG:32750 (tiles 50H, 50J) | true |
```

`config/pipeline.toml`:
```toml
[stac]
endpoint = "https://earth-search.aws.element84.com/v1"
collection = "sentinel-2-c1-l2a"
cloud_cover_max = 20.0
watermark_overlap_days = 1
required_assets = ["green", "red", "nir", "swir16", "scl", "product_metadata"]

[aoi]
ramsar_path = "data/external/dbca_010_ramsar_sites.geojson"
waterbodies_path = "data/external/dea_waterbodies_v3_swan.geojson"
site_prefixes = [
    "Forrestdale & Thomsons Lakes",
    "Peel-Yalgorup System",
    "Becher Point Wetlands",
    "Ellen Brook",
]
operation_epsg = 32750

[water]
method = "ndwi"
threshold = 0.0
min_valid_fraction = 0.8

[output]
root = "outputs"
```

Create the three `.gitkeep` files with `touch`.

**Step 4: Install and run the smoke test**

Run: `uv sync && uv run pytest -q tests/test_smoke.py`
Expected: `1 passed`.

**Step 5: Run the lint and type gates**

Run: `uv run ruff check src tests scripts && uv run ruff format --check src tests scripts && uv run mypy src scripts`
Expected: all clean. If `ruff format --check` fails, run `uv run ruff format src tests scripts` and re-check.

---

## Task 2: CI workflow

**Files:**
- Create: `.github/workflows/test.yml`

**Step 1: Write the workflow**

Copy `~/Documents/wa-mine-rehab-monitor/.github/workflows/test.yml` verbatim, then change only the two `run:` lines that name directories so they match this repo:

```yaml
      - name: ruff check
        run: uv run --no-sync ruff check src tests scripts

      - name: ruff format --check
        run: uv run --no-sync ruff format --check src tests scripts
```

The `mypy src scripts` and `pytest -q -rs` lines stay as they are. Keep the SHA-pinned actions, `ubuntu-24.04`, uv `0.9.29`, Python `3.12`, `enable-cache: false`, `permissions: contents: read`.

**Step 2: Validate the YAML parses**

Run: `uv run python -c "import yaml" 2>/dev/null || uv run --with pyyaml python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/test.yml')); print('ok')"`
Expected: `ok`.

---

## Task 3: Configuration loader

**Files:**
- Create: `src/wetland_change/config.py`
- Test: `tests/test_config.py`

**Step 1: Write the failing tests**

`tests/test_config.py`:
```python
from pathlib import Path

import pytest

from wetland_change.config import PipelineConfig, load_config

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config" / "pipeline.toml"


def test_load_repo_config() -> None:
    cfg = load_config(REPO_CONFIG)
    assert isinstance(cfg, PipelineConfig)
    assert cfg.stac.collection == "sentinel-2-c1-l2a"
    assert cfg.stac.cloud_cover_max == 20.0
    assert cfg.aoi.operation_epsg == 32750
    assert cfg.water.method == "ndwi"
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
    text = REPO_CONFIG.read_text().replace("cloud_cover_max = 20.0", "cloud_cover_max = 120")
    bad = tmp_path / "pipeline.toml"
    bad.write_text(text)
    with pytest.raises(ValueError):
        load_config(bad)
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_config.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'wetland_change.config'`.

**Step 3: Write the implementation**

`src/wetland_change/config.py`:
```python
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
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_config.py`
Expected: `3 passed`.

---

## Task 4: AOI fetch script and data sources

The fetchers hit the network once and write to `data/external/` (untracked). They are scripts, not pipeline code, so no TDD; they are typed and linted.

**Files:**
- Create: `scripts/fetch_aoi.py`
- Modify: `data/SOURCES.md`

**Step 1: Write the script**

`scripts/fetch_aoi.py`:
```python
"""Download the AOI layers into data/external and print SOURCES.md rows.

Ramsar sites: DBCA-010 via the open SLIP ArcGIS REST service, layer 9.
DEA Waterbodies v3: WFS bbox query over the Swan Coastal Plain.
Both fetch without a login. Re-running overwrites the files.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

OUT = Path("data/external")
RAMSAR_URL = (
    "https://public-services.slip.wa.gov.au/public/rest/services/"
    "SLIP_Public_Services/Environment/MapServer/9/query"
)
RAMSAR_PARAMS = {
    "where": "1=1",
    "outFields": "*",
    "returnGeometry": "true",
    "outSR": "4326",
    "f": "geojson",
}
WATERBODIES_URL = "https://geoserver.dea.ga.gov.au/geoserver/wfs"
WATERBODIES_PARAMS = {
    "service": "WFS",
    "version": "1.0.0",
    "request": "GetFeature",
    "typeName": "dea:DigitalEarthAustraliaWaterbodies_v3",
    "outputFormat": "application/json",
    "srsName": "EPSG:4326",
    "bbox": "115.4,-33.2,116.2,-31.5,EPSG:4326",
}


def fetch(url: str, params: dict[str, str], dest: Path) -> str:
    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return hashlib.sha256(response.content).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).date().isoformat()
    ramsar = OUT / "dbca_010_ramsar_sites.geojson"
    waterbodies = OUT / "dea_waterbodies_v3_swan.geojson"
    ramsar_sha = fetch(RAMSAR_URL, RAMSAR_PARAMS, ramsar)
    wb_sha = fetch(WATERBODIES_URL, WATERBODIES_PARAMS, waterbodies)
    print("Add or update these rows in data/SOURCES.md:")
    print(
        f"| DBCA-010 Ramsar Sites | {RAMSAR_URL} | CC BY-SA 4.0 (data.gov.au) | "
        f"{today} | {ramsar_sha} | EPSG:4326 (native GDA2020) | true |"
    )
    print(
        f"| DEA Waterbodies v3 (Swan subset) | {WATERBODIES_URL} | CC BY 4.0 | "
        f"{today} | {wb_sha} | EPSG:4326 | true |"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Run it**

Run: `uv run python scripts/fetch_aoi.py`
Expected: two files under `data/external/`, and two table rows printed. The Ramsar file holds 65 features; the waterbodies file holds a few hundred.

Check: `uv run python -c "import json; d=json.load(open('data/external/dbca_010_ramsar_sites.geojson')); print(len(d['features']))"` prints `65`.

**Step 3: Record the rows**

Append the two printed rows to the table in `data/SOURCES.md`.

**Step 4: Lint and type the script**

Run: `uv run ruff check scripts && uv run mypy scripts`
Expected: clean.

---

## Task 5: AOI loading

**Files:**
- Create: `src/wetland_change/aoi.py`
- Create: `tests/fixtures/aoi/ramsar_mini.geojson`, `tests/fixtures/aoi/waterbodies_mini.geojson`
- Test: `tests/test_aoi.py`

**Step 1: Write the fixtures**

`tests/fixtures/aoi/ramsar_mini.geojson` (a Thomsons Lake box with the real DBCA-010 objectid 52, a Forrestdale Lake box with objectid 56, and one out-of-scope site):
```json
{"type":"FeatureCollection","crs":{"type":"name","properties":{"name":"EPSG:4326"}},"features":[
{"type":"Feature","properties":{"objectid":52,"ram_ramsarname":"Forrestdale & Thomsons Lakes"},"geometry":{"type":"Polygon","coordinates":[[[115.817,-32.162],[115.842,-32.162],[115.842,-32.138],[115.817,-32.138],[115.817,-32.162]]]}},
{"type":"Feature","properties":{"objectid":56,"ram_ramsarname":"Forrestdale & Thomsons Lakes"},"geometry":{"type":"Polygon","coordinates":[[[115.928,-32.168],[115.946,-32.168],[115.946,-32.150],[115.928,-32.150],[115.928,-32.168]]]}},
{"type":"Feature","properties":{"objectid":5,"ram_ramsarname":"Lake Warden System"},"geometry":{"type":"Polygon","coordinates":[[[121.98,-33.80],[122.00,-33.80],[122.00,-33.79],[121.98,-33.79],[121.98,-33.80]]]}}
]}
```

`tests/fixtures/aoi/waterbodies_mini.geojson`:
```json
{"type":"FeatureCollection","crs":{"type":"name","properties":{"name":"EPSG:4326"}},"features":[
{"type":"Feature","properties":{"uid":"qd635epws_v3","area_m2":1932000,"timeseries":"https://data.dea.ga.gov.au/derivative/dea_waterbodies/3-0-0/timeseries/qd63/qd635epws_v3.csv"},"geometry":{"type":"Polygon","coordinates":[[[115.820,-32.158],[115.838,-32.158],[115.838,-32.142],[115.820,-32.142],[115.820,-32.158]]]}}
]}
```

**Step 2: Write the failing tests**

`tests/test_aoi.py`:
```python
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from wetland_change.aoi import (
    AoiPolygon,
    load_ramsar,
    load_waterbodies,
    union_bbox_4326,
)

FIX = Path(__file__).parent / "fixtures" / "aoi"


def test_load_ramsar_filters_by_prefix_and_reprojects() -> None:
    polys = load_ramsar(
        FIX / "ramsar_mini.geojson",
        site_prefixes=["Forrestdale & Thomsons Lakes"],
        operation_epsg=32750,
    )
    assert [p.polygon_id for p in polys] == ["ramsar-52", "ramsar-56"]
    assert all(p.layer == "ramsar" for p in polys)
    assert all(p.site == "Forrestdale & Thomsons Lakes" for p in polys)
    # EPSG:32750 metres: Thomsons box is about 2.4 km by 2.7 km
    minx, miny, maxx, maxy = polys[0].geometry.bounds
    assert 2000 < maxx - minx < 3000
    assert 2000 < maxy - miny < 3000
    assert isinstance(polys[0].geometry_4326, Polygon)


def test_load_waterbodies_uses_uid() -> None:
    polys = load_waterbodies(FIX / "waterbodies_mini.geojson", operation_epsg=32750)
    assert polys[0].polygon_id == "dea-qd635epws_v3"
    assert polys[0].layer == "dea_waterbody"
    assert polys[0].site == "qd635epws_v3"


def test_union_bbox_4326() -> None:
    polys = load_ramsar(
        FIX / "ramsar_mini.geojson",
        site_prefixes=["Forrestdale"],
        operation_epsg=32750,
    )
    bbox = union_bbox_4326(polys)
    assert bbox == pytest.approx((115.817, -32.168, 115.946, -32.138), abs=1e-6)


def test_missing_crs_is_rejected(tmp_path: Path) -> None:
    nocrs = tmp_path / "nocrs.geojson"
    nocrs.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"properties":{"objectid":1,"ram_ramsarname":"X"},"geometry":'
        '{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}]}'
    )
    with pytest.raises(ValueError, match="CRS"):
        load_ramsar(nocrs, site_prefixes=["X"], operation_epsg=32750, assume_crs=None)


def test_aoi_polygon_is_frozen() -> None:
    polys = load_waterbodies(FIX / "waterbodies_mini.geojson", operation_epsg=32750)
    with pytest.raises(AttributeError):
        polys[0].site = "other"  # type: ignore[misc]
    assert isinstance(polys[0], AoiPolygon)
```

**Step 3: Run to verify they fail**

Run: `uv run pytest -q tests/test_aoi.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 4: Write the implementation**

`src/wetland_change/aoi.py`:
```python
"""Area-of-interest polygons: Ramsar sites (reporting) and DEA Waterbodies
(verification), reprojected to the operation CRS behind a CRS guard.

GeoJSON is EPSG:4326 by specification, so a file without a `crs` member is
accepted as 4326 only when the caller says so (`assume_crs`); the guard
refuses to infer anything else (crs-guard skill).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class AoiPolygon:
    polygon_id: str
    site: str
    layer: str
    geometry: BaseGeometry
    geometry_4326: BaseGeometry


def _read(path: Path, assume_crs: str | None) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        if assume_crs is None:
            raise ValueError(f"{path} has no CRS and none was assumed")
        gdf = gdf.set_crs(assume_crs)
    return gdf


def _to_polygons(
    gdf: gpd.GeoDataFrame,
    *,
    id_prefix: str,
    id_column: str,
    site_column: str,
    layer: str,
    operation_epsg: int,
) -> list[AoiPolygon]:
    in_4326 = gdf.to_crs(4326)
    in_op = gdf.to_crs(operation_epsg)
    out: list[AoiPolygon] = []
    for (_, row4326), (_, row_op) in zip(
        in_4326.iterrows(), in_op.iterrows(), strict=True
    ):
        out.append(
            AoiPolygon(
                polygon_id=f"{id_prefix}-{row4326[id_column]}",
                site=str(row4326[site_column]),
                layer=layer,
                geometry=row_op.geometry,
                geometry_4326=row4326.geometry,
            )
        )
    return out


def load_ramsar(
    path: Path,
    *,
    site_prefixes: list[str],
    operation_epsg: int,
    assume_crs: str | None = "EPSG:4326",
) -> list[AoiPolygon]:
    """Ramsar polygons whose `ram_ramsarname` starts with one of the prefixes."""
    gdf = _read(path, assume_crs)
    names = gdf["ram_ramsarname"].astype(str)
    keep = names.map(lambda n: any(n.startswith(p) for p in site_prefixes))
    selected = gdf[keep].sort_values("objectid")
    return _to_polygons(
        selected,
        id_prefix="ramsar",
        id_column="objectid",
        site_column="ram_ramsarname",
        layer="ramsar",
        operation_epsg=operation_epsg,
    )


def load_waterbodies(
    path: Path,
    *,
    operation_epsg: int,
    assume_crs: str | None = "EPSG:4326",
) -> list[AoiPolygon]:
    """DEA Waterbodies polygons keyed by `uid`."""
    gdf = _read(path, assume_crs).sort_values("uid")
    return _to_polygons(
        gdf,
        id_prefix="dea",
        id_column="uid",
        site_column="uid",
        layer="dea_waterbody",
        operation_epsg=operation_epsg,
    )


def union_bbox_4326(polys: list[AoiPolygon]) -> tuple[float, float, float, float]:
    """(minx, miny, maxx, maxy) in EPSG:4326 over every polygon."""
    bounds = [p.geometry_4326.bounds for p in polys]
    return (
        min(b[0] for b in bounds),
        min(b[1] for b in bounds),
        max(b[2] for b in bounds),
        max(b[3] for b in bounds),
    )
```

**Step 5: Run to verify they pass**

Run: `uv run pytest -q tests/test_aoi.py`
Expected: `5 passed`.

---

## Task 6: Offline raster fixture from one real window

A single network fetch that writes a tiny real window of the 27 October 2026 Thomsons Lake scene to `tests/fixtures/thomsons_20261027/` so every later test runs offline. The files are committed (under 40 KB total).

**Files:**
- Create: `scripts/make_fixture.py`
- Create (by running it): `tests/fixtures/thomsons_20261027/{B03,B04,B08,B11,SCL}.tif`, `item.json`, `product_metadata.xml`

**Step 1: Write the script**

`scripts/make_fixture.py`:
```python
"""Write a 64 by 64 pixel (10 m) window of one real scene as test fixtures.

Window: a 640 m square centred on the Thomsons Lake centroid (389620 E,
6442400 N in EPSG:32750) on tile 50HLK, scene
S2C_T50HLK_20261027T022351_L2A. Bands at 10 m are 64 by 64; SCL and B11 at
20 m are 32 by 32. Offsets are even so the window sits on the 20 m lattice.
The STAC item JSON and the ESA product XML are saved alongside so scaling
and SCL tests have their references.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import rasterio
import requests
from rasterio.windows import Window

ITEM_URL = (
    "https://earth-search.aws.element84.com/v1/collections/"
    "sentinel-2-c1-l2a/items/S2C_T50HLK_20261027T022351_L2A"
)
OUT = Path("tests/fixtures/thomsons_20261027")
# Pixel offsets on the 10 m grid: tile origin (300000, 6500020), so column
# 8930 is 389300 E and row 5730 is 6442720 N. Both even (20 m lattice).
COL10, ROW10, SIZE10 = 8930, 5730, 64
ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "AWS_NO_SIGN_REQUEST": "YES",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
}


def save_window(href: str, dest: Path, window: Window) -> None:
    with rasterio.Env(**ENV), rasterio.open(href) as src:
        data = src.read(1, window=window)
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            transform=src.window_transform(window),
            compress="deflate",
            tiled=False,
        )
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
    with rasterio.open(dest, "w", **profile) as dst:
        dst.write(data, 1)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    item = requests.get(ITEM_URL, timeout=60).json()
    (OUT / "item.json").write_text(json.dumps(item, indent=1))
    xml = requests.get(item["assets"]["product_metadata"]["href"], timeout=60).text
    (OUT / "product_metadata.xml").write_text(xml)
    w10 = Window(COL10, ROW10, SIZE10, SIZE10)
    w20 = Window(COL10 // 2, ROW10 // 2, SIZE10 // 2, SIZE10 // 2)
    for key, name, window in (
        ("green", "B03", w10),
        ("red", "B04", w10),
        ("nir", "B08", w10),
        ("swir16", "B11", w20),
        ("scl", "SCL", w20),
    ):
        save_window(item["assets"][key]["href"], OUT / f"{name}.tif", window)
        print("wrote", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Run it**

Run: `uv run python scripts/make_fixture.py && ls -la tests/fixtures/thomsons_20261027 && du -sh tests/fixtures/thomsons_20261027`
Expected: seven files, total under 60 KB.

**Step 3: Sanity-check the fixture**

Run: `uv run python -c "import rasterio,numpy as np; s=rasterio.open('tests/fixtures/thomsons_20261027/SCL.tif'); a=s.read(1); print(s.crs, s.res, a.shape, np.unique(a))"`
Expected: `EPSG:32750 (20.0, 20.0) (32, 32)` and a class list that includes 6 (water). Most of the window should be class 6 since it sits on the lake centroid. If it is not, the lake spans roughly columns 8840 to 9080 and rows 5630 to 5900 on the 10 m grid of tile 50HLK; pick even offsets inside that range and rerun. Also confirm the 10 m origin: `uv run python -c "import rasterio; print(rasterio.open('tests/fixtures/thomsons_20261027/B03.tif').transform)"` prints `| 10.00, 0.00, 389300.00| | 0.00,-10.00, 6442720.00| ...`.

**Step 4: Lint**

Run: `uv run ruff check scripts && uv run mypy scripts`
Expected: clean.

---

## Task 7: Item guard and scene model

Every item is parsed once into a frozen `SceneItem` behind a guard that refuses the offset trap, a wrong collection, a missing asset or a reflectance band without `raster:bands`.

**Files:**
- Create: `src/wetland_change/catalogue/__init__.py` (empty), `src/wetland_change/catalogue/item.py`
- Create: `tests/conftest.py`
- Test: `tests/test_item.py`

**Step 1: Write the shared fixture loader**

`tests/conftest.py`:
```python
"""Shared fixtures. The Thomsons fixture item points at the local GeoTIFFs."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "thomsons_20261027"
LOCAL_ASSETS = {
    "green": "B03.tif",
    "red": "B04.tif",
    "nir": "B08.tif",
    "swir16": "B11.tif",
    "scl": "SCL.tif",
    "product_metadata": "product_metadata.xml",
}
REQUIRED_ASSETS = ["green", "red", "nir", "swir16", "scl", "product_metadata"]


def load_fixture_item(*, local: bool = True) -> dict[str, Any]:
    """The saved Earth Search item; with `local`, asset hrefs are local paths."""
    item: dict[str, Any] = json.loads((FIXTURE_DIR / "item.json").read_text())
    if local:
        for key, name in LOCAL_ASSETS.items():
            item["assets"][key]["href"] = str(FIXTURE_DIR / name)
    return item


@pytest.fixture
def fixture_item() -> dict[str, Any]:
    return copy.deepcopy(load_fixture_item())
```

**Step 2: Write the failing tests**

`tests/test_item.py`:
```python
import copy
from typing import Any

import pytest

from tests.conftest import REQUIRED_ASSETS
from wetland_change.catalogue.item import ItemGuardError, SceneItem, parse_item

ARGS: dict[str, Any] = {
    "collection": "sentinel-2-c1-l2a",
    "required_assets": REQUIRED_ASSETS,
}


def test_parse_fixture_item(fixture_item: dict[str, Any]) -> None:
    scene = parse_item(fixture_item, **ARGS)
    assert isinstance(scene, SceneItem)
    assert scene.item_id == "S2C_T50HLK_20261027T022351_L2A"
    assert scene.tile == "50HLK"
    assert scene.epsg == 32750
    assert scene.processing_baseline == "05.13"
    assert scene.datetime.tzinfo is not None
    assert scene.created <= scene.updated
    assert scene.bands["green"].scale == pytest.approx(1e-4)
    assert scene.bands["green"].offset == pytest.approx(-0.1)
    assert scene.bands["green"].nodata == 0
    assert scene.bands["swir16"].resolution == 20
    assert scene.product_uri.endswith(".SAFE")
    minx, _, maxx, _ = scene.geometry_4326.bounds
    assert minx < 115.83 < maxx
    assert scene.year == 2026


def test_rejects_other_collection(fixture_item: dict[str, Any]) -> None:
    item = copy.deepcopy(fixture_item)
    item["collection"] = "sentinel-2-l2a"
    with pytest.raises(ItemGuardError, match="collection"):
        parse_item(item, **ARGS)


def test_rejects_offset_applied_flag(fixture_item: dict[str, Any]) -> None:
    item = copy.deepcopy(fixture_item)
    item["properties"]["earthsearch:boa_offset_applied"] = True
    with pytest.raises(ItemGuardError, match="boa_offset_applied"):
        parse_item(item, **ARGS)


def test_rejects_missing_asset(fixture_item: dict[str, Any]) -> None:
    item = copy.deepcopy(fixture_item)
    del item["assets"]["scl"]
    with pytest.raises(ItemGuardError, match="scl"):
        parse_item(item, **ARGS)


def test_rejects_band_without_scale(fixture_item: dict[str, Any]) -> None:
    item = copy.deepcopy(fixture_item)
    del item["assets"]["nir"]["raster:bands"][0]["scale"]
    with pytest.raises(ItemGuardError, match="raster:bands"):
        parse_item(item, **ARGS)


def test_accepts_proj_code_form(fixture_item: dict[str, Any]) -> None:
    item = copy.deepcopy(fixture_item)
    item["properties"].pop("proj:epsg", None)
    item["properties"]["proj:code"] = "EPSG:32750"
    assert parse_item(item, **ARGS).epsg == 32750
```

**Step 3: Run to verify they fail**

Run: `uv run pytest -q tests/test_item.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'wetland_change.catalogue'`.

**Step 4: Write the implementation**

`src/wetland_change/catalogue/item.py`:
```python
"""Parse and guard one Earth Search item before any byte is read.

The guard refuses anything that would silently corrupt reflectance: a
different collection, an `earthsearch:boa_offset_applied` flag (offset
already baked in), a missing asset, or a reflectance band without
`raster:bands` scale and offset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

REFLECTANCE_BANDS: tuple[str, ...] = ("green", "red", "nir", "swir16")
OFFSET_APPLIED_KEY = "earthsearch:boa_offset_applied"


class ItemGuardError(ValueError):
    """The item must not be processed; the message says why."""


@dataclass(frozen=True)
class BandSpec:
    key: str
    href: str
    nodata: int
    scale: float
    offset: float
    resolution: int


@dataclass(frozen=True)
class SceneItem:
    item_id: str
    collection: str
    product_uri: str
    datetime: datetime
    created: datetime
    updated: datetime
    tile: str
    processing_baseline: str
    epsg: int
    cloud_cover: float
    geometry_4326: BaseGeometry
    bands: dict[str, BandSpec]
    scl_href: str
    product_metadata_href: str
    raw: dict[str, Any]

    @property
    def year(self) -> int:
        return self.datetime.year


def parse_timestamp(value: str) -> datetime:
    """RFC 3339 with a trailing Z to an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _epsg(props: dict[str, Any]) -> int:
    if props.get("proj:epsg") is not None:
        return int(props["proj:epsg"])
    code = props.get("proj:code")
    if isinstance(code, str) and code.upper().startswith("EPSG:"):
        return int(code.split(":")[1])
    raise ItemGuardError("item has neither proj:epsg nor an EPSG proj:code")


def _band(key: str, asset: dict[str, Any]) -> BandSpec:
    bands = asset.get("raster:bands") or []
    if not bands or "scale" not in bands[0] or "offset" not in bands[0]:
        raise ItemGuardError(f"asset {key!r} has no raster:bands scale and offset")
    spec = bands[0]
    return BandSpec(
        key=key,
        href=str(asset["href"]),
        nodata=int(spec.get("nodata", 0)),
        scale=float(spec["scale"]),
        offset=float(spec["offset"]),
        resolution=int(spec["spatial_resolution"]),
    )


def parse_item(
    item: dict[str, Any], *, collection: str, required_assets: list[str]
) -> SceneItem:
    """Validate an item dict and extract what the pipeline needs."""
    item_id = str(item.get("id", "<no id>"))
    if item.get("collection") != collection:
        raise ItemGuardError(
            f"{item_id}: collection {item.get('collection')!r} is not {collection!r}"
        )
    props: dict[str, Any] = item["properties"]
    if OFFSET_APPLIED_KEY in props:
        raise ItemGuardError(f"{item_id}: {OFFSET_APPLIED_KEY} present; offset trap")
    assets: dict[str, Any] = item.get("assets", {})
    needed = set(required_assets) | set(REFLECTANCE_BANDS) | {"scl", "product_metadata"}
    missing = sorted(key for key in needed if key not in assets)
    if missing:
        raise ItemGuardError(f"{item_id}: missing assets {missing}")
    bands = {key: _band(key, assets[key]) for key in REFLECTANCE_BANDS}
    return SceneItem(
        item_id=item_id,
        collection=str(item["collection"]),
        product_uri=str(props["s2:product_uri"]),
        datetime=parse_timestamp(props["datetime"]),
        created=parse_timestamp(props["created"]),
        updated=parse_timestamp(props["updated"]),
        tile=str(props["grid:code"]).removeprefix("MGRS-"),
        processing_baseline=str(props["s2:processing_baseline"]),
        epsg=_epsg(props),
        cloud_cover=float(props["eo:cloud_cover"]),
        geometry_4326=shape(item["geometry"]),
        bands=bands,
        scl_href=str(assets["scl"]["href"]),
        product_metadata_href=str(assets["product_metadata"]["href"]),
        raw=item,
    )
```

**Step 5: Run to verify they pass**

Run: `uv run pytest -q tests/test_item.py`
Expected: `6 passed`.

---

## Task 8: Discovery with retry and client-side re-checks

**Files:**
- Create: `src/wetland_change/catalogue/search.py`
- Test: `tests/test_search.py`

**Step 1: Write the failing tests**

`tests/test_search.py`:
```python
from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from shapely.geometry import box

from tests.conftest import REQUIRED_ASSETS
from wetland_change.catalogue.item import parse_timestamp
from wetland_change.catalogue.search import (
    STAC_RETRY_STATUSES,
    Discovery,
    build_search_kwargs,
    discover,
    make_stac_retry,
)
from wetland_change.config import StacConfig

CFG = StacConfig(
    endpoint="https://earth-search.aws.element84.com/v1",
    collection="sentinel-2-c1-l2a",
    cloud_cover_max=20.0,
    required_assets=REQUIRED_ASSETS,
)
THOMSONS_4326 = box(115.8168, -32.1615, 115.8421, -32.1378)
BBOX = THOMSONS_4326.bounds


class FakeSearch:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    def items_as_dicts(self) -> Iterator[dict[str, Any]]:
        yield from self._items


class FakeClient:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> FakeSearch:
        self.calls.append(kwargs)
        if "ids" in kwargs:
            return FakeSearch([i for i in self.items if i["id"] in kwargs["ids"]])
        return FakeSearch([i for i in self.items if not i.get("_retry_only")])


def _variant(item: dict[str, Any], suffix: str, **props: Any) -> dict[str, Any]:
    out = copy.deepcopy(item)
    out["id"] = f"{item['id']}_{suffix}"
    out["properties"].update(props)
    return out


def test_build_search_kwargs_uses_query_and_sort() -> None:
    since = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    kwargs = build_search_kwargs(CFG, bbox=BBOX, created_from=since)
    assert kwargs["collections"] == ["sentinel-2-c1-l2a"]
    assert kwargs["bbox"] == list(BBOX)
    assert kwargs["query"] == {
        "eo:cloud_cover": {"lt": 20.0},
        "created": {"gte": "2026-10-28T00:00:00Z"},
    }
    assert kwargs["sortby"] == [{"field": "properties.created", "direction": "asc"}]
    assert "ids" not in kwargs


def test_build_search_kwargs_without_watermark_or_with_ids() -> None:
    kwargs = build_search_kwargs(CFG, bbox=BBOX, created_from=None, ids=["a", "b"])
    assert "created" not in kwargs["query"]
    assert kwargs["ids"] == ["a", "b"]


def test_make_stac_retry_policy() -> None:
    retry = make_stac_retry()
    assert retry.total == 5
    assert set(STAC_RETRY_STATUSES) <= set(retry.status_forcelist)
    assert retry.allowed_methods is None
    assert retry.raise_on_status is False


def test_discover_rechecks_and_dedupes(fixture_item: dict[str, Any]) -> None:
    good = fixture_item
    cloudy = _variant(good, "cloudy", **{"eo:cloud_cover": 55.0})
    far = _variant(good, "far")
    far["geometry"] = {
        "type": "Polygon",
        "coordinates": [[[150, -30], [151, -30], [151, -29], [150, -29], [150, -30]]],
    }
    seen_copy = _variant(good, "seen")
    wrong = _variant(good, "wrong")
    wrong["collection"] = "sentinel-2-l2a"
    client = FakeClient([good, cloudy, far, seen_copy, wrong, copy.deepcopy(good)])
    result = discover(
        client,
        CFG,
        bbox=BBOX,
        polygons_4326=[THOMSONS_4326],
        created_from=None,
        seen={(seen_copy["id"], parse_timestamp(seen_copy["properties"]["updated"]))},
    )
    assert isinstance(result, Discovery)
    assert [s.item_id for s in result.scenes] == [good["id"]]
    assert result.skipped_seen == 1
    assert result.skipped_filter == 2
    assert result.rejected == [(wrong["id"], result.rejected[0][1])]
    assert "collection" in result.rejected[0][1]


def test_discover_fetches_retry_ids_by_id(fixture_item: dict[str, Any]) -> None:
    retry_item = _variant(fixture_item, "retry")
    retry_item["_retry_only"] = True
    client = FakeClient([fixture_item, retry_item])
    result = discover(
        client,
        CFG,
        bbox=BBOX,
        polygons_4326=[THOMSONS_4326],
        created_from=datetime(2026, 10, 28, tzinfo=UTC),
        seen=set(),
        retry_ids=[retry_item["id"]],
    )
    assert len(client.calls) == 2
    assert client.calls[1]["ids"] == [retry_item["id"]]
    assert "created" not in client.calls[1]["query"]
    assert {s.item_id for s in result.scenes} == {fixture_item["id"], retry_item["id"]}
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_search.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/catalogue/search.py`:
```python
"""Earth Search discovery with bounded retries and client-side re-checks.

Earth Search v1 supports the query and sort extensions and silently ignores
CQL2, so the cloud-cover and `created` filters go in `query`, and every
result is re-checked here before it is trusted.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, Self, cast

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from urllib3.util.retry import Retry

from wetland_change.catalogue.item import (
    ItemGuardError,
    SceneItem,
    parse_item,
    parse_timestamp,
)
from wetland_change.config import StacConfig

logger = logging.getLogger(__name__)

STAC_RETRY_STATUSES: tuple[int, ...] = (429, 502, 503, 504)
STAC_RETRY_TOTAL = 5
STAC_RETRY_BACKOFF = 1.0


class StacSearch(Protocol):
    def items_as_dicts(self) -> Iterator[dict[str, Any]]: ...


class StacClient(Protocol):
    """The slice of `pystac_client.Client` used here; tests inject a fake."""

    def search(self, **kwargs: Any) -> StacSearch: ...


class _LoggingRetry(Retry):
    """A `Retry` that logs each retried status with its attempt number."""

    #: urllib3 retries these when a Retry-After header is present regardless
    #: of status_forcelist; restrict it to the same set.
    RETRY_AFTER_STATUS_CODES = frozenset(STAC_RETRY_STATUSES)

    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: Any = None,
        error: Exception | None = None,
        _pool: Any = None,
        _stacktrace: Any = None,
    ) -> Self:
        new_retry = super().increment(method, url, response, error, _pool, _stacktrace)
        if response is not None and response.status in STAC_RETRY_STATUSES:
            logger.warning(
                "STAC %s %s returned %s; retry attempt %d of %s",
                method,
                url,
                response.status,
                len(new_retry.history),
                len(new_retry.history) + int(new_retry.total or 0),
            )
        return new_retry


def make_stac_retry(
    *, total: int = STAC_RETRY_TOTAL, backoff_factor: float = STAC_RETRY_BACKOFF
) -> Retry:
    """Bounded retry for transient STAC gateway errors; POST search included."""
    return _LoggingRetry(
        total=total,
        status=total,
        status_forcelist=STAC_RETRY_STATUSES,
        allowed_methods=None,
        backoff_factor=backoff_factor,
        raise_on_status=False,
    )


def open_client(endpoint: str) -> StacClient:
    """Open the live client. Imported lazily so unit tests never need it."""
    from pystac_client import Client
    from pystac_client.stac_api_io import StacApiIO

    stac_io = StacApiIO(max_retries=make_stac_retry())
    return cast(StacClient, Client.open(endpoint, stac_io=stac_io))


def _rfc3339(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def build_search_kwargs(
    cfg: StacConfig,
    *,
    bbox: tuple[float, float, float, float],
    created_from: datetime | None,
    ids: list[str] | None = None,
) -> dict[str, Any]:
    """Keyword arguments for `Client.search`, using only query and sort."""
    query: dict[str, Any] = {"eo:cloud_cover": {"lt": cfg.cloud_cover_max}}
    if created_from is not None:
        query["created"] = {"gte": _rfc3339(created_from)}
    kwargs: dict[str, Any] = {
        "collections": [cfg.collection],
        "bbox": list(bbox),
        "query": query,
        "sortby": [{"field": "properties.created", "direction": "asc"}],
    }
    if ids:
        kwargs["ids"] = ids
    return kwargs


@dataclass
class Discovery:
    scenes: list[SceneItem] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    skipped_seen: int = 0
    skipped_filter: int = 0


def discover(
    client: StacClient,
    cfg: StacConfig,
    *,
    bbox: tuple[float, float, float, float],
    polygons_4326: list[BaseGeometry],
    created_from: datetime | None,
    seen: set[tuple[str, datetime]],
    retry_ids: Iterable[str] = (),
) -> Discovery:
    """New scenes since the watermark plus explicit retries, re-checked locally.

    `seen` holds (item id, parsed `updated`) pairs already processed
    successfully; an item republished with a new `updated` is processed again.
    """
    kwargs = build_search_kwargs(cfg, bbox=bbox, created_from=created_from)
    candidates = list(client.search(**kwargs).items_as_dicts())
    retry_list = list(retry_ids)
    if retry_list:
        retry_kwargs = build_search_kwargs(cfg, bbox=bbox, created_from=None, ids=retry_list)
        candidates.extend(client.search(**retry_kwargs).items_as_dicts())

    result = Discovery()
    done: set[str] = set()
    for item in candidates:
        item_id = str(item.get("id"))
        if item_id in done:
            continue
        done.add(item_id)
        props: dict[str, Any] = item.get("properties", {})
        updated_raw = props.get("updated")
        if updated_raw and (item_id, parse_timestamp(str(updated_raw))) in seen:
            result.skipped_seen += 1
            continue
        cloud = props.get("eo:cloud_cover")
        if cloud is None or float(cloud) >= cfg.cloud_cover_max:
            result.skipped_filter += 1
            continue
        footprint = shape(item["geometry"])
        if not any(footprint.intersects(poly) for poly in polygons_4326):
            result.skipped_filter += 1
            continue
        try:
            scene = parse_item(
                item, collection=cfg.collection, required_assets=cfg.required_assets
            )
        except ItemGuardError as exc:
            logger.warning("rejected %s: %s", item_id, exc)
            result.rejected.append((item_id, str(exc)))
            continue
        result.scenes.append(scene)
    result.scenes.sort(key=lambda s: (s.created, s.item_id))
    return result
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_search.py`
Expected: `5 passed`.

---

## Task 9: GDAL environment and transient retry

Lifted from mine-footprint-seg `imagery/composites.py` (the HTTP timeout env that stopped a seven-hour hang, and the duck-typed transient classifier).

**Files:**
- Create: `src/wetland_change/raster/__init__.py` (empty), `src/wetland_change/raster/env.py`, `src/wetland_change/raster/retry.py`
- Test: `tests/test_raster_env.py`, `tests/test_retry.py`

**Step 1: Write the failing tests**

`tests/test_raster_env.py`:
```python
import pytest

from wetland_change.raster.env import COG_ENV, cog_env, gdal_http_env


def test_gdal_http_env_values() -> None:
    env = gdal_http_env(timeout=30.0, connect_timeout=10.0, max_retry=3, retry_delay=2.0)
    assert env == {
        "GDAL_HTTP_TIMEOUT": "30",
        "GDAL_HTTP_CONNECTTIMEOUT": "10",
        "GDAL_HTTP_MAX_RETRY": "3",
        "GDAL_HTTP_RETRY_DELAY": "2",
    }


@pytest.mark.parametrize("kwargs", [{"timeout": 0.5}, {"connect_timeout": 0.9}, {"retry_delay": 0}])
def test_gdal_http_env_rejects_sub_second(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        gdal_http_env(**kwargs)


def test_cog_env_merges_overrides() -> None:
    env = cog_env(AWS_REGION="ap-southeast-2")
    assert env["AWS_NO_SIGN_REQUEST"] == "YES"
    assert env["GDAL_DISABLE_READDIR_ON_OPEN"] == "EMPTY_DIR"
    assert env["GDAL_HTTP_TIMEOUT"] == "30"
    assert env["AWS_REGION"] == "ap-southeast-2"
    assert set(COG_ENV) <= set(env)
```

`tests/test_retry.py`:
```python
from __future__ import annotations

import pytest
import requests
from rasterio.errors import RasterioIOError

from wetland_change.raster.retry import is_transient_error, retry_transient


class _Status(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RasterioIOError("CURL error: Operation timed out"), True),
        (RasterioIOError("No such file or directory"), False),
        (_Status(503), True),
        (_Status(429), True),
        (_Status(404), False),
        (requests.ConnectionError("dns"), True),
        (requests.Timeout("slow"), True),
        (ValueError("no items"), False),
    ],
)
def test_is_transient_error(exc: BaseException, expected: bool) -> None:
    assert is_transient_error(exc) is expected


def test_retry_transient_retries_with_backoff() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise _Status(503)
        return "ok"

    assert retry_transient(flaky, attempts=3, sleep=sleeps.append) == "ok"
    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]


def test_retry_transient_does_not_retry_non_transient() -> None:
    calls: list[int] = []

    def broken() -> None:
        calls.append(1)
        raise ValueError("bad")

    with pytest.raises(ValueError):
        retry_transient(broken, attempts=3, sleep=lambda _: None)
    assert len(calls) == 1


def test_retry_transient_exhausts_attempts() -> None:
    def always() -> None:
        raise _Status(502)

    with pytest.raises(_Status):
        retry_transient(always, attempts=2, sleep=lambda _: None)


def test_retry_transient_rejects_zero_attempts() -> None:
    with pytest.raises(ValueError):
        retry_transient(lambda: 1, attempts=0)
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_raster_env.py tests/test_retry.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementations**

`src/wetland_change/raster/env.py`:
```python
"""GDAL environment for anonymous, windowed COG reads over HTTPS."""

from __future__ import annotations

#: Static settings: no directory listing on open, anonymous S3, only .tif
#: through the curl handler, merged ranges, and a bounded RAM block cache
#: (the curl cache is RAM; a 50 GB setting once OOM-killed a DEA run).
COG_ENV: dict[str, str] = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "AWS_NO_SIGN_REQUEST": "YES",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIRANGE": "YES",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": str(64 * 1024 * 1024),
    "CPL_VSIL_CURL_CACHE_SIZE": str(256 * 1024 * 1024),
}


def gdal_http_env(
    *,
    timeout: float = 30.0,
    connect_timeout: float = 10.0,
    max_retry: int = 3,
    retry_delay: float = 2.0,
) -> dict[str, str]:
    """GDAL HTTP settings that bound a stalled or flaky S3 COG read.

    Values are truncated to whole seconds for GDAL, so anything below one
    second would become "0", which curl treats as no timeout at all. That is
    refused here rather than silently reinstating an unbounded hang.
    """
    if timeout < 1:
        raise ValueError(f"timeout must be >= 1, got {timeout}")
    if connect_timeout < 1:
        raise ValueError(f"connect_timeout must be >= 1, got {connect_timeout}")
    if retry_delay < 1:
        raise ValueError(f"retry_delay must be >= 1, got {retry_delay}")
    return {
        "GDAL_HTTP_TIMEOUT": str(int(timeout)),
        "GDAL_HTTP_CONNECTTIMEOUT": str(int(connect_timeout)),
        "GDAL_HTTP_MAX_RETRY": str(int(max_retry)),
        "GDAL_HTTP_RETRY_DELAY": str(int(retry_delay)),
    }


def cog_env(**overrides: str) -> dict[str, str]:
    """The full environment for `rasterio.Env`: static settings, HTTP bounds,
    then caller overrides (for example `AWS_REGION` for the DEA bucket)."""
    return {**COG_ENV, **gdal_http_env(), **overrides}
```

`src/wetland_change/raster/retry.py`:
```python
"""Bounded retry on transient network errors.

GDAL and rasterio give no structured error type for a flaky S3 read: a 404
and a 503 both surface as a `RasterioIOError` with a free-text message, so
classification is a documented heuristic over message markers plus a
duck-typed `status_code` for HTTP client errors.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from rasterio.errors import RasterioIOError, WarpOperationError

_RASTERIO_TRANSIENT_MARKERS: tuple[str, ...] = (
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
    "could not resolve host",
    "network is unreachable",
    "temporary failure",
    "curl error",
    "recv failure",
    "send failure",
    "empty reply",
    "unexpected eof",
    "connection was closed",
    "slowdown",
    "slow down",
    "429",
    "500",
    "502",
    "503",
    "504",
)

#: Cycle detection, not this cap, guarantees termination of the cause walk.
_MAX_CAUSE_HOPS = 32


def _transient_exception_types() -> tuple[type[BaseException], ...]:
    try:
        import requests.exceptions as req_exc
    except ImportError:  # pragma: no cover
        return ()
    return (req_exc.ConnectionError, req_exc.Timeout)


def is_transient_error(exc: BaseException) -> bool:
    """True for a connection failure, a timeout, or an HTTP 429 or 5xx."""
    transient_types = _transient_exception_types()
    if transient_types and isinstance(exc, transient_types):
        return True

    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return bool(status_code == 429 or status_code >= 500)

    if isinstance(exc, RasterioIOError):
        message = str(exc).lower()
        return any(marker in message for marker in _RASTERIO_TRANSIENT_MARKERS)

    if isinstance(exc, WarpOperationError):
        seen: set[int] = {id(exc)}
        link = exc.__cause__
        for _ in range(_MAX_CAUSE_HOPS):
            if link is None or id(link) in seen:
                break
            seen.add(id(link))
            message = str(link).lower()
            if any(marker in message for marker in _RASTERIO_TRANSIENT_MARKERS):
                return True
            link = link.__cause__
        return False

    cause = exc.__context__
    return bool(transient_types) and isinstance(cause, transient_types)


def retry_transient[T](
    func: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    is_transient: Callable[[BaseException], bool] = is_transient_error,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `func()` up to `attempts` times on transient errors with
    exponential backoff capped at `max_delay`. Non-transient errors re-raise
    at once; the last transient error re-raises when attempts run out."""
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1, got {attempts}")
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:
            if not is_transient(exc) or attempt == attempts:
                raise
            sleep(min(base_delay * (2 ** (attempt - 1)), max_delay))
    raise AssertionError("unreachable")  # pragma: no cover
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_raster_env.py tests/test_retry.py`
Expected: `14 passed`.

---

## Task 10: Reflectance scaling checked against the ESA XML

Verification matrix row "Reflectance scaling". The `raster:bands` scale and offset must equal 1/BOA_QUANTIFICATION_VALUE and BOA_ADD_OFFSET/BOA_QUANTIFICATION_VALUE from the product XML, for every item, before any DN is converted.

**Files:**
- Create: `src/wetland_change/raster/scaling.py`
- Test: `tests/test_scaling.py`

**Step 1: Write the failing tests**

`tests/test_scaling.py`:
```python
from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pytest

from tests.conftest import FIXTURE_DIR, REQUIRED_ASSETS
from wetland_change.catalogue.item import BandSpec, parse_item
from wetland_change.raster.scaling import (
    EsaScaling,
    ScalingMismatch,
    check_band_scaling,
    parse_product_metadata,
    to_reflectance,
)

XML = (FIXTURE_DIR / "product_metadata.xml").read_text()


def test_parse_fixture_xml() -> None:
    esa = parse_product_metadata(XML)
    assert esa == EsaScaling(quantification=10000.0, add_offset=-1000.0)
    assert esa.scale == pytest.approx(1e-4)
    assert esa.offset == pytest.approx(-0.1)


def test_fixture_item_bands_match_xml(fixture_item: dict[str, Any]) -> None:
    scene = parse_item(
        fixture_item, collection="sentinel-2-c1-l2a", required_assets=REQUIRED_ASSETS
    )
    esa = parse_product_metadata(XML)
    for band in scene.bands.values():
        check_band_scaling(band, esa)


def test_tampered_offset_is_refused(fixture_item: dict[str, Any]) -> None:
    scene = parse_item(
        fixture_item, collection="sentinel-2-c1-l2a", required_assets=REQUIRED_ASSETS
    )
    bad = dataclasses.replace(scene.bands["green"], offset=0.0)
    with pytest.raises(ScalingMismatch, match="offset"):
        check_band_scaling(bad, parse_product_metadata(XML))


def test_xml_without_quantification_is_refused() -> None:
    with pytest.raises(ScalingMismatch, match="BOA_QUANTIFICATION_VALUE"):
        parse_product_metadata("<root><BOA_ADD_OFFSET>-1000</BOA_ADD_OFFSET></root>")


def test_xml_with_mixed_offsets_is_refused() -> None:
    xml = (
        "<root><BOA_QUANTIFICATION_VALUE>10000</BOA_QUANTIFICATION_VALUE>"
        "<BOA_ADD_OFFSET>-1000</BOA_ADD_OFFSET><BOA_ADD_OFFSET>0</BOA_ADD_OFFSET></root>"
    )
    with pytest.raises(ScalingMismatch, match="BOA_ADD_OFFSET"):
        parse_product_metadata(xml)


def test_to_reflectance_scales_and_masks_nodata() -> None:
    band = BandSpec("green", "x", nodata=0, scale=1e-4, offset=-0.1, resolution=10)
    dn = np.array([[0, 1000], [11000, 6000]], dtype=np.uint16)
    out = to_reflectance(dn, band)
    assert out.dtype == np.float32
    assert np.isnan(out[0, 0])
    np.testing.assert_allclose(out[0, 1], 0.0, atol=1e-6)
    np.testing.assert_allclose(out[1, 0], 1.0, atol=1e-6)
    np.testing.assert_allclose(out[1, 1], 0.5, atol=1e-6)


def test_to_reflectance_rejects_float_input() -> None:
    band = BandSpec("green", "x", nodata=0, scale=1e-4, offset=-0.1, resolution=10)
    with pytest.raises(TypeError):
        to_reflectance(np.zeros((2, 2), dtype=np.float32), band)
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_scaling.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/raster/scaling.py`:
```python
"""Reflectance scaling checked against the ESA product metadata.

`raster:bands` on the item says reflectance = DN * scale + offset. The ESA
MTD_MSIL2A.xml states BOA_QUANTIFICATION_VALUE (Q) and BOA_ADD_OFFSET (A).
They must agree (scale = 1/Q, offset = A/Q) or the item is refused.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np

from wetland_change.catalogue.item import BandSpec


class ScalingMismatch(ValueError):
    """Item metadata and ESA metadata disagree on how to scale DN."""


@dataclass(frozen=True)
class EsaScaling:
    quantification: float
    add_offset: float

    @property
    def scale(self) -> float:
        return 1.0 / self.quantification

    @property
    def offset(self) -> float:
        return self.add_offset / self.quantification


def parse_product_metadata(xml_text: str) -> EsaScaling:
    """Read Q and A from MTD_MSIL2A.xml, namespace-agnostic."""
    root = ET.fromstring(xml_text)
    quantification: float | None = None
    offsets: set[float] = set()
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "BOA_QUANTIFICATION_VALUE" and element.text:
            quantification = float(element.text)
        elif tag == "BOA_ADD_OFFSET" and element.text:
            offsets.add(float(element.text))
    if quantification is None:
        raise ScalingMismatch("BOA_QUANTIFICATION_VALUE not found in product metadata")
    if len(offsets) != 1:
        raise ScalingMismatch(f"expected one BOA_ADD_OFFSET value, found {sorted(offsets)}")
    return EsaScaling(quantification=quantification, add_offset=offsets.pop())


def check_band_scaling(band: BandSpec, esa: EsaScaling, *, rel_tol: float = 1e-9) -> None:
    """Raise ScalingMismatch unless the band's scale and offset match the XML."""
    if not math.isclose(band.scale, esa.scale, rel_tol=rel_tol):
        raise ScalingMismatch(
            f"{band.key}: raster:bands scale {band.scale} != 1/{esa.quantification}"
        )
    if not math.isclose(band.offset, esa.offset, rel_tol=rel_tol, abs_tol=1e-12):
        raise ScalingMismatch(
            f"{band.key}: raster:bands offset {band.offset} != "
            f"{esa.add_offset}/{esa.quantification}"
        )


def to_reflectance(dn: np.ndarray, band: BandSpec) -> np.ndarray:
    """DN to float32 reflectance with the nodata DN as NaN.

    Computed in float64 then cast, so 1000 * 1e-4 - 0.1 is exactly 0.0.
    """
    if not np.issubdtype(dn.dtype, np.integer):
        raise TypeError(f"{band.key}: expected integer DN, got {dn.dtype}")
    out = (dn.astype(np.float64) * band.scale + band.offset).astype(np.float32)
    out[dn == band.nodata] = np.nan
    return out
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_scaling.py`
Expected: `7 passed`.

---

## Task 11: Window planning on the 20 m lattice

**Files:**
- Create: `src/wetland_change/windows.py`
- Test: `tests/test_windows.py`

**Step 1: Write the failing tests**

`tests/test_windows.py`:
```python
from __future__ import annotations

import pytest
from affine import Affine
from shapely.geometry import box

from wetland_change.windows import Grid, PlannedWindow, plan_window

TILE = Grid(Affine(10, 0, 300000, 0, -10, 6500020), width=10980, height=10980, epsg=32750)


def test_grid_bounds() -> None:
    assert TILE.bounds == (300000, 6390220, 409800, 6500020)


def test_window_snaps_to_20m_lattice() -> None:
    planned = plan_window(box(389400, 6442180, 389840, 6442620), TILE)
    assert isinstance(planned, PlannedWindow)
    w10 = planned.window10
    assert (w10.col_off, w10.row_off, w10.width, w10.height) == (8938, 5738, 48, 48)
    w20 = planned.window20
    assert (w20.col_off, w20.row_off, w20.width, w20.height) == (4469, 2869, 24, 24)
    assert planned.transform10.c == 389380
    assert planned.transform10.f == 6442640
    assert planned.scene_coverage == pytest.approx(1.0)
    assert planned.shape10 == (48, 48)


def test_odd_pixel_bounds_round_outwards_to_even() -> None:
    planned = plan_window(box(389415, 6442185, 389835, 6442615), TILE)
    assert planned is not None
    assert planned.window10.col_off % 2 == 0
    assert planned.window10.row_off % 2 == 0
    assert planned.window10.width % 2 == 0
    assert planned.window10.height % 2 == 0
    assert planned.window10.col_off <= 8939 < planned.window10.col_off + planned.window10.width


def test_window_clips_at_scene_edge_and_reports_coverage() -> None:
    planned = plan_window(box(409700, 6442000, 410000, 6442300), TILE)
    assert planned is not None
    assert planned.window10.col_off + planned.window10.width == 10980
    assert planned.scene_coverage == pytest.approx(1 / 3, abs=1e-9)


def test_outside_scene_returns_none() -> None:
    assert plan_window(box(500000, 6442000, 500300, 6442300), TILE) is None


def test_rejects_grid_off_lattice() -> None:
    off = Grid(Affine(10, 0, 300010, 0, -10, 6500020), width=10, height=10, epsg=32750)
    with pytest.raises(ValueError, match="lattice"):
        plan_window(box(300020, 6499900, 300060, 6499960), off)


def test_rejects_non_10m_grid() -> None:
    coarse = Grid(Affine(20, 0, 300000, 0, -20, 6500020), width=10, height=10, epsg=32750)
    with pytest.raises(ValueError, match="10 m"):
        plan_window(box(300020, 6499900, 300060, 6499960), coarse)
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_windows.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/windows.py`:
```python
"""Pixel windows on the scene grid, snapped to the 20 m SCL lattice.

Sentinel-2 tiles put the 10 m and 20 m grids on the same origin, so a 10 m
window with even offsets and even lengths maps exactly 2:1 onto a 20 m
window. That is what lets SCL and swir16 be upsampled by repetition with
no resampling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from affine import Affine
from rasterio.windows import Window
from rasterio.windows import transform as window_transform
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class Grid:
    transform: Affine
    width: int
    height: int
    epsg: int

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        t = self.transform
        return (t.c, t.f + t.e * self.height, t.c + t.a * self.width, t.f)


@dataclass(frozen=True)
class PlannedWindow:
    window10: Window
    window20: Window
    transform10: Affine
    scene_coverage: float

    @property
    def shape10(self) -> tuple[int, int]:
        return (int(self.window10.height), int(self.window10.width))


def _require_10m_on_20m_lattice(grid: Grid) -> None:
    t = grid.transform
    if t.a != 10 or t.e != -10 or t.b or t.d:
        raise ValueError(f"expected an axis-aligned 10 m grid, got {t!r}")
    if t.c % 20 or t.f % 20:
        raise ValueError(f"grid origin ({t.c}, {t.f}) is not on the 20 m lattice")


def plan_window(
    polygon: BaseGeometry, grid: Grid, *, pad_px: int = 2
) -> PlannedWindow | None:
    """Smallest even-aligned 10 m window around `polygon`, clipped to the
    scene, or None when the polygon misses the scene entirely.

    `polygon` must already be in the grid's CRS. `scene_coverage` is the
    share of the polygon's area inside the scene extent; a polygon on a
    tile seam gets one row per scene with coverage below 1.
    """
    _require_10m_on_20m_lattice(grid)
    overlap = polygon.intersection(box(*grid.bounds))
    if overlap.is_empty or polygon.area == 0:
        return None
    t = grid.transform
    minx, miny, maxx, maxy = polygon.bounds
    col0 = math.floor((minx - t.c) / t.a) - pad_px
    col1 = math.ceil((maxx - t.c) / t.a) + pad_px
    row0 = math.floor((t.f - maxy) / -t.e) - pad_px
    row1 = math.ceil((t.f - miny) / -t.e) + pad_px
    col0 = max(0, col0 - col0 % 2)
    row0 = max(0, row0 - row0 % 2)
    col1 = min(grid.width, col1 + col1 % 2)
    row1 = min(grid.height, row1 + row1 % 2)
    if col1 <= col0 or row1 <= row0:
        return None
    window10 = Window(col0, row0, col1 - col0, row1 - row0)
    window20 = Window(col0 // 2, row0 // 2, (col1 - col0) // 2, (row1 - row0) // 2)
    return PlannedWindow(
        window10=window10,
        window20=window20,
        transform10=window_transform(window10, t),
        scene_coverage=overlap.area / polygon.area,
    )
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_windows.py`
Expected: `7 passed`.

---

## Task 12: SCL masks

**Files:**
- Create: `src/wetland_change/mask.py`
- Test: `tests/test_mask.py`

**Step 1: Write the failing tests**

`tests/test_mask.py`:
```python
import numpy as np

from wetland_change.mask import (
    CLEAR_CLASSES,
    CLOUD_CLASSES,
    EXCLUDED_CLASSES,
    clear_mask,
    cloud_mask,
    upsample_2x,
    water_mask_scl,
)


def test_class_sets_partition_all_twelve_classes() -> None:
    assert set(CLEAR_CLASSES) | set(EXCLUDED_CLASSES) == set(range(12))
    assert not set(CLEAR_CLASSES) & set(EXCLUDED_CLASSES)
    assert set(CLOUD_CLASSES) <= set(EXCLUDED_CLASSES)


def test_upsample_2x_repeats_each_pixel() -> None:
    a = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)
    up = upsample_2x(a)
    assert up.shape == (4, 6)
    assert up[0, 0] == up[1, 1] == 1
    assert up[3, 5] == up[2, 4] == 6
    assert up.dtype == np.uint8


def test_clear_mask_requires_clear_class_and_finite_bands() -> None:
    scl = np.array([[4, 6], [9, 0]], dtype=np.uint8)
    band = np.array([[0.1, np.nan], [0.2, 0.3]], dtype=np.float32)
    out = clear_mask(scl, band)
    assert out.tolist() == [[True, False], [False, False]]


def test_cloud_and_water_masks() -> None:
    scl = np.array([[8, 9, 10, 6, 4]], dtype=np.uint8)
    assert cloud_mask(scl).tolist() == [[True, True, True, False, False]]
    assert water_mask_scl(scl).tolist() == [[False, False, False, True, False]]
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_mask.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/mask.py`:
```python
"""Scene Classification Layer handling.

ESA SCL classes: 0 no data, 1 saturated or defective, 2 dark area (cast
shadow), 3 cloud shadow, 4 vegetation, 5 not vegetated, 6 water, 7
unclassified, 8 cloud medium probability, 9 cloud high probability, 10 thin
cirrus, 11 snow or ice. Clear means 4, 5, 6, 7 and 11. Cloud means 8, 9 and
10, which is the ESA definition behind `eo:cloud_cover`.
"""

from __future__ import annotations

import numpy as np

SCL_NODATA = 0
SCL_WATER = 6
CLEAR_CLASSES: tuple[int, ...] = (4, 5, 6, 7, 11)
CLOUD_CLASSES: tuple[int, ...] = (8, 9, 10)
EXCLUDED_CLASSES: tuple[int, ...] = (0, 1, 2, 3, 8, 9, 10)


def upsample_2x(array: np.ndarray) -> np.ndarray:
    """Nearest-neighbour 2:1 upsampling of a 20 m array onto the 10 m grid."""
    return np.repeat(np.repeat(array, 2, axis=0), 2, axis=1)


def clear_mask(scl: np.ndarray, *bands: np.ndarray) -> np.ndarray:
    """True where SCL is a clear class and every given band is finite."""
    clear = np.isin(scl, CLEAR_CLASSES)
    for band in bands:
        clear &= np.isfinite(band)
    return clear


def cloud_mask(scl: np.ndarray) -> np.ndarray:
    return np.isin(scl, CLOUD_CLASSES)


def water_mask_scl(scl: np.ndarray) -> np.ndarray:
    return scl == SCL_WATER
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_mask.py`
Expected: `4 passed`.

---

## Task 13: Indices with a spyndex cross-check

Verification matrix row "Index arithmetic". Lifted from land-clearing-detection `imagery/metrics.py` (numpy path only).

**Files:**
- Create: `src/wetland_change/indices.py`
- Test: `tests/test_indices.py`

**Step 1: Write the failing tests**

`tests/test_indices.py`:
```python
from __future__ import annotations

import numpy as np
import pytest

from wetland_change.indices import mndwi, ndvi, ndwi, normalised_difference


def test_known_values() -> None:
    green = np.array([0.3, 0.1], dtype=np.float32)
    nir = np.array([0.1, 0.3], dtype=np.float32)
    np.testing.assert_allclose(ndwi(green, nir), [0.5, -0.5], atol=1e-6)
    np.testing.assert_allclose(ndvi(nir, green), [-0.5, 0.5], atol=1e-6)
    np.testing.assert_allclose(mndwi(green, nir), [0.5, -0.5], atol=1e-6)
    assert ndwi(green, nir).dtype == np.float32


def test_zero_denominator_is_nan_not_warning() -> None:
    with np.errstate(all="raise"):
        out = normalised_difference(np.array([0.0, 0.2]), np.array([0.0, 0.2]))
    assert np.isnan(out[0])
    assert out[1] == 0.0


def test_nan_propagates() -> None:
    out = ndwi(np.array([np.nan, 0.2]), np.array([0.1, 0.1]))
    assert np.isnan(out[0]) and np.isfinite(out[1])


def test_integer_input_is_refused() -> None:
    with pytest.raises(TypeError, match="integer"):
        ndwi(np.array([3000], dtype=np.uint16), np.array([1000], dtype=np.uint16))


def test_matches_spyndex_on_random_reflectance() -> None:
    spyndex = pytest.importorskip("spyndex")
    rng = np.random.default_rng(42)
    g, n, r, s = (rng.uniform(0.0, 0.6, size=(32, 32)) for _ in range(4))
    np.testing.assert_allclose(
        ndwi(g, n), spyndex.computeIndex("NDWI", params={"G": g, "N": n}), atol=1e-6
    )
    np.testing.assert_allclose(
        mndwi(g, s), spyndex.computeIndex("MNDWI", params={"G": g, "S1": s}), atol=1e-6
    )
    np.testing.assert_allclose(
        ndvi(n, r), spyndex.computeIndex("NDVI", params={"N": n, "R": r}), atol=1e-6
    )
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_indices.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/indices.py`:
```python
"""Normalised-difference indices on float reflectance.

NDWI (McFeeters 1996) = (green - nir) / (green + nir)
MNDWI (Xu 2006)       = (green - swir16) / (green + swir16)
NDVI                  = (nir - red) / (nir + red)

A zero denominator gives NaN. Integer input is refused: it would overflow
the sum (uint16 wraps) and treat the nodata DN as a value.
"""

from __future__ import annotations

import numpy as np


def reject_integer_bands(*, context: str, **bands: np.ndarray) -> None:
    for name, value in bands.items():
        if np.issubdtype(value.dtype, np.integer):
            raise TypeError(
                f"{context} received integer-typed {name!r} (dtype {value.dtype}); "
                "convert DN with to_reflectance() first"
            )


def normalised_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b) as float32, NaN where a + b is zero."""
    denominator = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(denominator != 0, (a - b) / denominator, np.nan)
    return np.asarray(result, dtype=np.float32)


def ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    reject_integer_bands(context="ndwi", green=green, nir=nir)
    return normalised_difference(green, nir)


def mndwi(green: np.ndarray, swir16: np.ndarray) -> np.ndarray:
    reject_integer_bands(context="mndwi", green=green, swir16=swir16)
    return normalised_difference(green, swir16)


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    reject_integer_bands(context="ndvi", nir=nir, red=red)
    return normalised_difference(nir, red)
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_indices.py`
Expected: `5 passed`.

---

## Task 14: Windowed reader and band stack

**Files:**
- Create: `src/wetland_change/raster/read.py`
- Modify: `tests/conftest.py` (add `fixture_scene`, `fixture_grid`, `fixture_polygon` fixtures)
- Test: `tests/test_read.py`

**Step 1: Extend conftest**

Replace `tests/conftest.py` with:
```python
"""Shared fixtures. The Thomsons fixture item points at the local GeoTIFFs."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from wetland_change.catalogue.item import SceneItem, parse_item
from wetland_change.raster.read import RasterioReader
from wetland_change.windows import Grid

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "thomsons_20261027"
LOCAL_ASSETS = {
    "green": "B03.tif",
    "red": "B04.tif",
    "nir": "B08.tif",
    "swir16": "B11.tif",
    "scl": "SCL.tif",
    "product_metadata": "product_metadata.xml",
}
REQUIRED_ASSETS = ["green", "red", "nir", "swir16", "scl", "product_metadata"]


def load_fixture_item(*, local: bool = True) -> dict[str, Any]:
    """The saved Earth Search item; with `local`, asset hrefs are local paths."""
    item: dict[str, Any] = json.loads((FIXTURE_DIR / "item.json").read_text())
    if local:
        for key, name in LOCAL_ASSETS.items():
            item["assets"][key]["href"] = str(FIXTURE_DIR / name)
    return item


@pytest.fixture
def fixture_item() -> dict[str, Any]:
    return copy.deepcopy(load_fixture_item())


@pytest.fixture
def fixture_scene(fixture_item: dict[str, Any]) -> SceneItem:
    return parse_item(
        fixture_item, collection="sentinel-2-c1-l2a", required_assets=REQUIRED_ASSETS
    )


@pytest.fixture
def fixture_grid(fixture_scene: SceneItem) -> Grid:
    return RasterioReader().open_grid(fixture_scene.bands["green"].href)


@pytest.fixture
def fixture_polygon(fixture_grid: Grid) -> BaseGeometry:
    """A box 100 m inside the fixture extent, in EPSG:32750."""
    minx, miny, maxx, maxy = fixture_grid.bounds
    return box(minx + 100, miny + 100, maxx - 100, maxy - 100)
```

**Step 2: Write the failing tests**

`tests/test_read.py`:
```python
from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from rasterio.windows import Window

from tests.conftest import FIXTURE_DIR
from wetland_change.catalogue.item import SceneItem
from wetland_change.indices import ndwi
from wetland_change.raster.read import (
    BandStack,
    HttpStatusError,
    RasterioReader,
    read_stack,
)
from wetland_change.raster.retry import is_transient_error
from wetland_change.windows import Grid, plan_window


def test_open_grid_reads_fixture_header(fixture_grid: Grid) -> None:
    assert fixture_grid.epsg == 32750
    assert (fixture_grid.width, fixture_grid.height) == (64, 64)
    assert fixture_grid.transform.a == 10
    assert fixture_grid.transform.c % 20 == 0


def test_read_window_returns_uint16(fixture_scene: SceneItem) -> None:
    arr = RasterioReader().read(fixture_scene.bands["green"].href, Window(0, 0, 4, 4))
    assert arr.shape == (4, 4)
    assert arr.dtype == np.uint16


def test_read_overview(fixture_scene: SceneItem) -> None:
    arr = RasterioReader().read_overview(fixture_scene.scl_href, 4)
    assert arr.shape == (8, 8)


def test_read_text_local(fixture_scene: SceneItem) -> None:
    text = RasterioReader().read_text(fixture_scene.product_metadata_href)
    assert "BOA_QUANTIFICATION_VALUE" in text


def test_http_status_error_is_transient_for_5xx_only() -> None:
    assert is_transient_error(HttpStatusError("u", 503))
    assert not is_transient_error(HttpStatusError("u", 404))


def test_read_stack_from_fixture(
    fixture_scene: SceneItem, fixture_grid: Grid, fixture_polygon: Any
) -> None:
    planned = plan_window(fixture_polygon, fixture_grid)
    assert planned is not None
    stack = read_stack(fixture_scene, planned, RasterioReader())
    assert isinstance(stack, BandStack)
    assert stack.shape == (48, 48)
    for band in (stack.green, stack.red, stack.nir, stack.swir16):
        assert band.shape == (48, 48) and band.dtype == np.float32
        finite = band[np.isfinite(band)]
        assert finite.size > 0.99 * band.size
        assert finite.min() >= -0.1 and finite.max() <= 1.5
    assert stack.scl.shape == (48, 48) and stack.scl.dtype == np.uint8
    assert 6 in np.unique(stack.scl)
    assert stack.epsg == 32750
    assert stack.transform == planned.transform10
    water = stack.scl == 6
    assert np.nanmedian(ndwi(stack.green, stack.nir)[water]) > -0.2


class _WrongShapeReader:
    """Returns the SCL window one row short so the stack check must fire."""

    def __init__(self, real: RasterioReader) -> None:
        self._real = real

    def open_grid(self, href: str) -> Grid:
        return self._real.open_grid(href)

    def read(self, href: str, window: Window) -> np.ndarray:
        data = self._real.read(href, window)
        return data[:-1, :] if href.endswith("SCL.tif") else data

    def read_overview(self, href: str, factor: int) -> np.ndarray:
        return self._real.read_overview(href, factor)

    def read_text(self, href: str) -> str:
        return self._real.read_text(href)


def test_read_stack_rejects_shape_mismatch(
    fixture_scene: SceneItem, fixture_grid: Grid, fixture_polygon: Any
) -> None:
    planned = plan_window(fixture_polygon, fixture_grid)
    assert planned is not None
    with pytest.raises(ValueError, match="shape"):
        read_stack(fixture_scene, planned, _WrongShapeReader(RasterioReader()))


def test_fixture_files_present() -> None:
    for name in ("B03.tif", "B04.tif", "B08.tif", "B11.tif", "SCL.tif", "item.json"):
        assert (FIXTURE_DIR / name).exists()
```

**Step 3: Run to verify they fail**

Run: `uv run pytest -q tests/test_read.py`
Expected: FAIL with `ModuleNotFoundError` (conftest import of `wetland_change.raster.read`).

**Step 4: Write the implementation**

`src/wetland_change/raster/read.py`:
```python
"""Windowed reads of one scene's bands into a float32 reflectance stack.

`RasterReader` is a Protocol so the pipeline is tested on local GeoTIFFs
with the same `RasterioReader` that reads S3 COGs; only the href differs.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import rasterio
import requests
from affine import Affine
from rasterio.windows import Window

from wetland_change.catalogue.item import SceneItem
from wetland_change.mask import upsample_2x
from wetland_change.raster.env import cog_env
from wetland_change.raster.retry import retry_transient
from wetland_change.raster.scaling import to_reflectance
from wetland_change.windows import Grid, PlannedWindow


class HttpStatusError(RuntimeError):
    """A non-2xx response; `status_code` lets the retry classifier see it."""

    def __init__(self, href: str, status_code: int) -> None:
        super().__init__(f"{href} returned HTTP {status_code}")
        self.status_code = status_code


class RasterReader(Protocol):
    def open_grid(self, href: str) -> Grid: ...
    def read(self, href: str, window: Window) -> np.ndarray: ...
    def read_overview(self, href: str, factor: int) -> np.ndarray: ...
    def read_text(self, href: str) -> str: ...


class RasterioReader:
    """rasterio-backed reader with the COG env and transient retry."""

    def __init__(
        self,
        *,
        env: dict[str, str] | None = None,
        attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._env = cog_env() if env is None else env
        self._attempts = attempts
        self._sleep = sleep

    def _retry[T](self, func: Callable[[], T]) -> T:
        return retry_transient(func, attempts=self._attempts, sleep=self._sleep)

    def open_grid(self, href: str) -> Grid:
        def _open() -> Grid:
            with rasterio.Env(**self._env), rasterio.open(href) as src:
                epsg = src.crs.to_epsg() if src.crs is not None else None
                if epsg is None:
                    raise ValueError(f"{href} has no EPSG CRS")
                return Grid(
                    transform=src.transform,
                    width=int(src.width),
                    height=int(src.height),
                    epsg=int(epsg),
                )

        return self._retry(_open)

    def read(self, href: str, window: Window) -> np.ndarray:
        def _read() -> np.ndarray:
            with rasterio.Env(**self._env), rasterio.open(href) as src:
                data: np.ndarray = src.read(1, window=window)
                return data

        return self._retry(_read)

    def read_overview(self, href: str, factor: int) -> np.ndarray:
        def _read() -> np.ndarray:
            with rasterio.Env(**self._env), rasterio.open(href) as src:
                shape = (src.height // factor, src.width // factor)
                data: np.ndarray = src.read(1, out_shape=shape)
                return data

        return self._retry(_read)

    def read_text(self, href: str) -> str:
        if href.startswith(("http://", "https://")):

            def _get() -> str:
                response = requests.get(href, timeout=60)
                if response.status_code >= 400:
                    raise HttpStatusError(href, response.status_code)
                return response.text

            return self._retry(_get)
        return Path(href).read_text()


@dataclass(frozen=True)
class BandStack:
    """10 m float32 reflectance plus SCL on the same window."""

    green: np.ndarray
    red: np.ndarray
    nir: np.ndarray
    swir16: np.ndarray
    scl: np.ndarray
    transform: Affine
    epsg: int

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.green.shape[0]), int(self.green.shape[1]))


def read_stack(scene: SceneItem, planned: PlannedWindow, reader: RasterReader) -> BandStack:
    """Read the five assets for one planned window; swir16 and SCL are
    upsampled 2:1 onto the 10 m grid."""
    arrays: dict[str, np.ndarray] = {}
    for key in ("green", "red", "nir"):
        spec = scene.bands[key]
        arrays[key] = to_reflectance(reader.read(spec.href, planned.window10), spec)
    swir_spec = scene.bands["swir16"]
    arrays["swir16"] = upsample_2x(
        to_reflectance(reader.read(swir_spec.href, planned.window20), swir_spec)
    )
    arrays["scl"] = upsample_2x(reader.read(scene.scl_href, planned.window20))
    expected = planned.shape10
    for name, array in arrays.items():
        if array.shape != expected:
            raise ValueError(f"{name} window shape {array.shape} != planned {expected}")
    return BandStack(
        green=arrays["green"],
        red=arrays["red"],
        nir=arrays["nir"],
        swir16=arrays["swir16"],
        scl=arrays["scl"].astype(np.uint8),
        transform=planned.transform10,
        epsg=scene.epsg,
    )
```

**Step 5: Run to verify they pass**

Run: `uv run pytest -q tests/test_read.py`
Expected: `8 passed`. If `test_read_stack_from_fixture` fails on the water assertion, the fixture window is not on the lake; revisit Task 6 Step 3.

---

## Task 15: Zonal summary row

**Files:**
- Create: `src/wetland_change/stats.py`
- Test: `tests/test_stats.py`

**Step 1: Write the failing tests**

`tests/test_stats.py`:
```python
from __future__ import annotations

import numpy as np
import pytest
from affine import Affine
from rasterio.windows import Window
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from wetland_change.aoi import AoiPolygon
from wetland_change.catalogue.item import SceneItem
from wetland_change.config import WaterConfig
from wetland_change.raster.read import BandStack, RasterioReader, read_stack
from wetland_change.stats import PIXEL_AREA_HA, ObservationRow, rasterise, summarise
from wetland_change.windows import Grid, PlannedWindow, plan_window

T = Affine(10, 0, 0, 0, -10, 40)


def _stack() -> BandStack:
    scl = np.array(
        [[6, 6, 6, 6], [6, 6, 6, 6], [4, 4, 4, 4], [9, 9, 0, 0]], dtype=np.uint8
    )
    green = np.where(scl == 6, 0.3, np.where(scl == 4, 0.1, 0.2)).astype(np.float32)
    nir = np.where(scl == 6, 0.1, np.where(scl == 4, 0.5, 0.2)).astype(np.float32)
    red = np.full((4, 4), 0.1, dtype=np.float32)
    swir16 = np.full((4, 4), 0.05, dtype=np.float32)
    return BandStack(green=green, red=red, nir=nir, swir16=swir16, scl=scl, transform=T, epsg=32750)


def _polygon(geom: BaseGeometry) -> AoiPolygon:
    return AoiPolygon("ramsar-52", "Forrestdale & Thomsons Lakes", "ramsar", geom, box(0, 0, 1, 1))


def _planned() -> PlannedWindow:
    return PlannedWindow(Window(0, 0, 4, 4), Window(0, 0, 2, 2), T, scene_coverage=1.0)


def test_rasterise_uses_pixel_centres() -> None:
    assert rasterise(box(0, 0, 40, 40), T, (4, 4)).sum() == 16
    assert rasterise(box(0, 0, 20, 40), T, (4, 4)).sum() == 8
    assert rasterise(box(0, 0, 4, 4), T, (4, 4)).sum() == 0


def test_summarise_synthetic_ndwi(fixture_scene: SceneItem) -> None:
    row = summarise(
        _polygon(box(0, 0, 40, 40)),
        fixture_scene,
        _stack(),
        _planned(),
        water=WaterConfig(method="ndwi", threshold=0.0),
        run_id="run-1",
    )
    assert isinstance(row, ObservationRow)
    assert row.polygon_id == "ramsar-52"
    assert row.item_id == fixture_scene.item_id
    assert row.tile == "50HLK"
    assert (row.n_pixels, row.n_clear) == (16, 12)
    assert row.valid_fraction == pytest.approx(0.75)
    assert row.cloud_fraction == pytest.approx(0.125)
    assert row.water_ha_scl == pytest.approx(8 * PIXEL_AREA_HA)
    assert row.water_ha_index == pytest.approx(8 * PIXEL_AREA_HA)
    assert row.ndwi_median == pytest.approx(0.5, abs=1e-6)
    assert row.mndwi_median == pytest.approx(0.25 / 0.35, abs=1e-6)
    assert row.ndvi_median == pytest.approx(0.0, abs=1e-6)
    assert row.dea_wo_agreement is None
    assert row.run_id == "run-1"
    assert row.scene_coverage == 1.0


def test_summarise_mndwi_threshold(fixture_scene: SceneItem) -> None:
    row = summarise(
        _polygon(box(0, 0, 40, 40)),
        fixture_scene,
        _stack(),
        _planned(),
        water=WaterConfig(method="mndwi", threshold=0.5),
        run_id="run-1",
    )
    assert row.water_ha_index == pytest.approx(8 * PIXEL_AREA_HA)


def test_summarise_half_polygon(fixture_scene: SceneItem) -> None:
    row = summarise(
        _polygon(box(0, 0, 20, 40)),
        fixture_scene,
        _stack(),
        _planned(),
        water=WaterConfig(),
        run_id="run-1",
    )
    assert row.n_pixels == 8
    assert row.water_ha_scl == pytest.approx(4 * PIXEL_AREA_HA)


def test_summarise_no_clear_pixels_gives_nan_medians(fixture_scene: SceneItem) -> None:
    stack = _stack()
    cloudy = BandStack(
        green=stack.green,
        red=stack.red,
        nir=stack.nir,
        swir16=stack.swir16,
        scl=np.full((4, 4), 9, dtype=np.uint8),
        transform=T,
        epsg=32750,
    )
    row = summarise(
        _polygon(box(0, 0, 40, 40)), fixture_scene, cloudy, _planned(), water=WaterConfig(), run_id="r"
    )
    assert row.valid_fraction == 0.0
    assert row.cloud_fraction == 1.0
    assert np.isnan(row.ndwi_median)
    assert row.water_ha_index == 0.0


def test_summarise_fixture_lake(
    fixture_scene: SceneItem, fixture_grid: Grid, fixture_polygon: BaseGeometry
) -> None:
    planned = plan_window(fixture_polygon, fixture_grid)
    assert planned is not None
    stack = read_stack(fixture_scene, planned, RasterioReader())
    row = summarise(
        _polygon(fixture_polygon), fixture_scene, stack, planned, water=WaterConfig(), run_id="r"
    )
    assert row.n_pixels == 44 * 44
    assert row.valid_fraction > 0.9
    assert row.water_ha_scl > 5.0
    assert row.water_ha_scl <= row.n_pixels * PIXEL_AREA_HA
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_stats.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/stats.py`:
```python
"""Polygon rasterisation and the per-polygon, per-scene summary row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from affine import Affine
from rasterio.features import geometry_mask
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from wetland_change.aoi import AoiPolygon
from wetland_change.catalogue.item import SceneItem
from wetland_change.config import WaterConfig
from wetland_change.indices import mndwi, ndvi, ndwi
from wetland_change.mask import clear_mask, cloud_mask, water_mask_scl
from wetland_change.raster.read import BandStack
from wetland_change.windows import PlannedWindow

PIXEL_AREA_HA = 0.01  # 10 m by 10 m


@dataclass(frozen=True)
class ObservationRow:
    polygon_id: str
    site: str
    aoi_layer: str
    item_id: str
    product_uri: str
    datetime: datetime
    tile: str
    processing_baseline: str
    scene_coverage: float
    n_pixels: int
    n_clear: int
    valid_fraction: float
    cloud_fraction: float
    water_ha_index: float
    water_ha_scl: float
    ndwi_median: float
    mndwi_median: float
    ndvi_median: float
    dea_wo_agreement: float | None
    geometry_4326: BaseGeometry
    run_id: str


def rasterise(
    geometry: BaseGeometry, transform: Affine, shape: tuple[int, int]
) -> np.ndarray:
    """True for pixels whose centre falls inside `geometry`."""
    mask: np.ndarray = geometry_mask(
        [mapping(geometry)], out_shape=shape, transform=transform, invert=True
    )
    return mask


def _median(values: np.ndarray, mask: np.ndarray) -> float:
    selected = values[mask]
    selected = selected[np.isfinite(selected)]
    return float(np.median(selected)) if selected.size else float("nan")


def summarise(
    polygon: AoiPolygon,
    scene: SceneItem,
    stack: BandStack,
    planned: PlannedWindow,
    *,
    water: WaterConfig,
    run_id: str,
) -> ObservationRow:
    """One observation row: areas in hectares, medians over clear pixels."""
    inside = rasterise(polygon.geometry, stack.transform, stack.shape)
    n_pixels = int(inside.sum())
    clear = clear_mask(stack.scl, stack.green, stack.red, stack.nir, stack.swir16) & inside
    n_clear = int(clear.sum())
    cloudy = cloud_mask(stack.scl) & inside
    ndwi_arr = ndwi(stack.green, stack.nir)
    mndwi_arr = mndwi(stack.green, stack.swir16)
    ndvi_arr = ndvi(stack.nir, stack.red)
    index_arr = ndwi_arr if water.method == "ndwi" else mndwi_arr
    with np.errstate(invalid="ignore"):
        water_index = clear & (index_arr > water.threshold)
    water_scl = clear & water_mask_scl(stack.scl)
    return ObservationRow(
        polygon_id=polygon.polygon_id,
        site=polygon.site,
        aoi_layer=polygon.layer,
        item_id=scene.item_id,
        product_uri=scene.product_uri,
        datetime=scene.datetime,
        tile=scene.tile,
        processing_baseline=scene.processing_baseline,
        scene_coverage=planned.scene_coverage,
        n_pixels=n_pixels,
        n_clear=n_clear,
        valid_fraction=n_clear / n_pixels if n_pixels else 0.0,
        cloud_fraction=int(cloudy.sum()) / n_pixels if n_pixels else 0.0,
        water_ha_index=float(water_index.sum()) * PIXEL_AREA_HA,
        water_ha_scl=float(water_scl.sum()) * PIXEL_AREA_HA,
        ndwi_median=_median(ndwi_arr, clear),
        mndwi_median=_median(mndwi_arr, clear),
        ndvi_median=_median(ndvi_arr, clear),
        dea_wo_agreement=None,
        geometry_4326=polygon.geometry_4326,
        run_id=run_id,
    )
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_stats.py`
Expected: `6 passed`.

---

## Task 16: Output store

A pyarrow filesystem wrapper so a local directory now and `s3://bucket/prefix` in Milestone 2 share one code path.

**Files:**
- Create: `src/wetland_change/store.py`
- Test: `tests/test_store.py`

**Step 1: Write the failing tests**

`tests/test_store.py`:
```python
from pathlib import Path

from wetland_change.store import OutputStore


def test_write_read_exists_list(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "out"))
    assert not store.exists("a/b.txt")
    assert store.write_bytes("a/b.txt", b"hello") == "a/b.txt"
    store.write_bytes("a/c/d.txt", b"x")
    store.write_bytes("z.txt", b"y")
    assert store.exists("a/b.txt")
    assert store.read_bytes("a/b.txt") == b"hello"
    assert store.list_files("a") == ["a/b.txt", "a/c/d.txt"]
    assert store.list_files("") == ["a/b.txt", "a/c/d.txt", "z.txt"]
    assert store.list_files("missing") == []
    assert (tmp_path / "out" / "a" / "b.txt").read_bytes() == b"hello"


def test_accepts_file_uri(tmp_path: Path) -> None:
    store = OutputStore((tmp_path / "out").as_uri())
    store.write_bytes("k.txt", b"v")
    assert (tmp_path / "out" / "k.txt").exists()
    assert store.uri.startswith("file://")
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_store.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/store.py`:
```python
"""Output storage behind a pyarrow filesystem.

A plain path becomes a `file://` URI; `s3://bucket/prefix` resolves to
`S3FileSystem` with the same interface, so Milestone 2 changes only config.
"""

from __future__ import annotations

from pathlib import Path

from pyarrow import fs as pafs


class OutputStore:
    def __init__(self, root: str) -> None:
        if "://" not in root:
            root = Path(root).resolve().as_uri()
        self.uri = root
        self.fs, self.root = pafs.FileSystem.from_uri(root)

    def _full(self, relpath: str) -> str:
        if not relpath:
            return self.root.rstrip("/")
        return f"{self.root.rstrip('/')}/{relpath.lstrip('/')}"

    def write_bytes(self, relpath: str, data: bytes) -> str:
        full = self._full(relpath)
        self.fs.create_dir(full.rsplit("/", 1)[0], recursive=True)
        with self.fs.open_output_stream(full) as stream:
            stream.write(data)
        return relpath

    def read_bytes(self, relpath: str) -> bytes:
        with self.fs.open_input_stream(self._full(relpath)) as stream:
            data: bytes = stream.read()
            return data

    def exists(self, relpath: str) -> bool:
        info = self.fs.get_file_info(self._full(relpath))
        return bool(info.type != pafs.FileType.NotFound)

    def list_files(self, prefix: str) -> list[str]:
        """Relative paths of every file under `prefix`, sorted."""
        selector = pafs.FileSelector(self._full(prefix), recursive=True, allow_not_found=True)
        base = self.root.rstrip("/") + "/"
        return sorted(
            info.path[len(base):]
            for info in self.fs.get_file_info(selector)
            if info.type == pafs.FileType.File
        )
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_store.py`
Expected: `2 passed`.

---

## Task 17: GeoParquet observation files

Verification matrix row "GeoParquet output": geoparquet-validator, DuckDB and GDAL (pyogrio) as independent readers; byte-identical rewrite.

**Files:**
- Create: `src/wetland_change/outputs/__init__.py` (empty), `src/wetland_change/outputs/geoparquet.py`
- Test: `tests/test_geoparquet.py`

**Step 1: Write the failing tests**

`tests/test_geoparquet.py`:
```python
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import geopandas as gpd
import pyarrow.parquet as pq
import pytest
from shapely.geometry import box

from wetland_change.outputs.geoparquet import (
    OBSERVATION_COLUMNS,
    observation_path,
    rows_to_frame,
    to_geoparquet_bytes,
    write_observations,
)
from wetland_change.stats import ObservationRow
from wetland_change.store import OutputStore

WHEN = datetime(2026, 10, 27, 2, 26, 46, tzinfo=UTC)


def _row(polygon_id: str, minx: float, item_id: str = "S2C_T50HLK_20261027T022351_L2A") -> ObservationRow:
    return ObservationRow(
        polygon_id=polygon_id,
        site="Forrestdale & Thomsons Lakes",
        aoi_layer="ramsar",
        item_id=item_id,
        product_uri="S2C_MSIL2A_x.SAFE",
        datetime=WHEN,
        tile="50HLK",
        processing_baseline="05.13",
        scene_coverage=1.0,
        n_pixels=100,
        n_clear=90,
        valid_fraction=0.9,
        cloud_fraction=0.05,
        water_ha_index=0.5,
        water_ha_scl=0.6,
        ndwi_median=0.2,
        mndwi_median=0.3,
        ndvi_median=-0.1,
        dea_wo_agreement=None,
        geometry_4326=box(minx, -32.16, minx + 0.01, -32.15),
        run_id="run-1",
    )


ROWS = [_row("ramsar-56", 115.93), _row("ramsar-52", 115.82)]


def test_observation_path() -> None:
    assert (
        observation_path(2026, "50HLK", "S2C_T50HLK_20261027T022351_L2A")
        == "observations/year=2026/tile=50HLK/obs_S2C_T50HLK_20261027T022351_L2A.parquet"
    )


def test_frame_is_sorted_and_typed() -> None:
    frame = rows_to_frame(ROWS)
    assert list(frame["polygon_id"]) == ["ramsar-52", "ramsar-56"]
    assert list(frame.columns) == [*OBSERVATION_COLUMNS, "geometry"]
    dtype = str(frame["datetime"].dtype)
    assert dtype.startswith("datetime64[") and dtype.endswith("UTC]")
    assert frame["dea_wo_agreement"].dtype == "float64"
    assert frame.crs.to_epsg() == 4326


def test_write_and_read_back(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_observations(ROWS, store)
    assert relpath == observation_path(2026, "50HLK", ROWS[0].item_id)
    back = gpd.read_parquet(tmp_path / relpath)
    assert len(back) == 2
    assert back.crs.to_epsg() == 4326
    assert back["water_ha_scl"].tolist() == [0.6, 0.6]


def test_geo_metadata_declares_covering_bbox(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_observations(ROWS, store)
    meta = json.loads(pq.read_schema(tmp_path / relpath).metadata[b"geo"])
    assert meta["version"] == "1.1.0"
    assert meta["columns"]["geometry"]["covering"]["bbox"]["xmin"] == ["bbox", "xmin"]
    assert meta["columns"]["geometry"]["crs"] is not None


def test_geoparquet_validator_accepts_file(tmp_path: Path) -> None:
    exe = shutil.which("geoparquet-validator")
    if exe is None:
        pytest.skip("geoparquet-validator not on PATH; run under uv")
    store = OutputStore(str(tmp_path))
    relpath = write_observations(ROWS, store)
    result = subprocess.run(
        [exe, "check", str(tmp_path / relpath), "--json"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_duckdb_reads_bbox_column(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    relpath = write_observations(ROWS, store)
    rows = duckdb.connect().execute(
        "SELECT polygon_id, bbox.xmin FROM read_parquet(?) ORDER BY polygon_id",
        [str(tmp_path / relpath)],
    ).fetchall()
    assert rows[0][0] == "ramsar-52"
    assert rows[0][1] == pytest.approx(115.82)


def test_gdal_reads_file_when_parquet_driver_present(tmp_path: Path) -> None:
    pyogrio = pytest.importorskip("pyogrio")
    if "Parquet" not in pyogrio.list_drivers():
        pytest.skip("GDAL build without the Parquet driver")
    store = OutputStore(str(tmp_path))
    relpath = write_observations(ROWS, store)
    assert len(gpd.read_file(tmp_path / relpath)) == 2


def test_rewrite_is_byte_identical() -> None:
    frame = rows_to_frame(ROWS)
    assert to_geoparquet_bytes(frame) == to_geoparquet_bytes(rows_to_frame(list(reversed(ROWS))))


def test_mixed_items_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="one file per item"):
        write_observations([ROWS[0], _row("x", 115.0, item_id="other")], OutputStore(str(tmp_path)))
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_geoparquet.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/outputs/geoparquet.py`:
```python
"""GeoParquet 1.1 observation files with the bbox covering column.

One file per source item under `observations/year=YYYY/tile=<MGRS>/`, so a
rerun overwrites rather than appends. Rows are sorted and written through a
buffer, which makes a rewrite byte-identical.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

import geopandas as gpd
import pandas as pd

from wetland_change.stats import ObservationRow
from wetland_change.store import OutputStore

OBSERVATION_COLUMNS: tuple[str, ...] = (
    "polygon_id",
    "site",
    "aoi_layer",
    "item_id",
    "product_uri",
    "datetime",
    "tile",
    "processing_baseline",
    "scene_coverage",
    "n_pixels",
    "n_clear",
    "valid_fraction",
    "cloud_fraction",
    "water_ha_index",
    "water_ha_scl",
    "ndwi_median",
    "mndwi_median",
    "ndvi_median",
    "dea_wo_agreement",
    "run_id",
)


def observation_path(year: int, tile: str, item_id: str) -> str:
    return f"observations/year={year}/tile={tile}/obs_{item_id}.parquet"


def rows_to_frame(rows: Sequence[ObservationRow]) -> gpd.GeoDataFrame:
    ordered = sorted(rows, key=lambda r: (r.item_id, r.polygon_id))
    records = [{col: getattr(r, col) for col in OBSERVATION_COLUMNS} for r in ordered]
    frame = pd.DataFrame.from_records(records, columns=list(OBSERVATION_COLUMNS))
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    frame["dea_wo_agreement"] = frame["dea_wo_agreement"].astype("float64")
    return gpd.GeoDataFrame(
        frame, geometry=[r.geometry_4326 for r in ordered], crs="EPSG:4326"
    )


def to_geoparquet_bytes(frame: gpd.GeoDataFrame) -> bytes:
    buffer = BytesIO()
    frame.to_parquet(buffer, index=False, schema_version="1.1.0", write_covering_bbox=True)
    return buffer.getvalue()


def write_observations(rows: Sequence[ObservationRow], store: OutputStore) -> str:
    """Write one item's rows; returns the relative path."""
    if not rows:
        raise ValueError("no rows to write")
    items = {r.item_id for r in rows}
    if len(items) != 1:
        raise ValueError(f"one file per item; got {sorted(items)}")
    first = rows[0]
    relpath = observation_path(first.datetime.year, first.tile, first.item_id)
    store.write_bytes(relpath, to_geoparquet_bytes(rows_to_frame(rows)))
    return relpath
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_geoparquet.py`
Expected: `9 passed` (or `8 passed, 1 skipped` when the GDAL build lacks the Parquet driver; record which in the handoff).

---

## Task 18: Ledger of processed items

Deviation from the design, recorded here: the ledger is a fixed-schema parquet file per run rather than stac-geoparquet, because stac-geoparquet infers its schema from each item batch and files with differing nullable property sets do not union cleanly. The full source item is kept as a JSON column so the Milestone 2 catalogue can rebuild items from the ledger, and stac-geoparquet is used there for the catalogue's `items.parquet` asset where it belongs.

**Files:**
- Create: `src/wetland_change/ledger.py`
- Test: `tests/test_ledger.py`

**Step 1: Write the failing tests**

`tests/test_ledger.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from wetland_change.catalogue.item import SceneItem
from wetland_change.ledger import (
    LEDGER_SCHEMA,
    MAX_ATTEMPTS,
    attempts_so_far,
    entry_for,
    exhausted_keys,
    ledger_path,
    read_ledger,
    rejected_entry,
    retry_ids,
    seen_keys,
    watermark,
    write_ledger,
)
from wetland_change.store import OutputStore

T0 = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)


def test_empty_ledger(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    ledger = read_ledger(store)
    assert ledger.num_rows == 0
    assert ledger.schema.equals(LEDGER_SCHEMA)
    assert watermark(ledger) is None
    assert seen_keys(ledger) == set()
    assert retry_ids(ledger) == []
    assert exhausted_keys(ledger) == set()
    assert attempts_so_far(ledger, "x") == 0


def test_ledger_path_partitions_by_run_year() -> None:
    assert ledger_path("20261028T100000Z", 2026) == "ledger/year=2026/ledger_20261028T100000Z.parquet"


def test_roundtrip_watermark_seen_and_retries(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    ok = entry_for(
        fixture_scene,
        status="succeeded",
        attempts=1,
        run_id="r1",
        processed_at=T0,
        n_rows=3,
        observation_path="observations/x.parquet",
    )
    bad = rejected_entry("bad-id", "collection mismatch", run_id="r1", processed_at=T0)
    files = write_ledger([ok, bad], store, run_id="r1")
    assert files == [ledger_path("r1", 2026)]

    ledger = read_ledger(store)
    assert ledger.num_rows == 2
    assert watermark(ledger) == fixture_scene.created
    assert seen_keys(ledger) == {(fixture_scene.item_id, fixture_scene.updated)}
    assert retry_ids(ledger) == []
    assert attempts_so_far(ledger, fixture_scene.item_id) == 1


def test_failed_entries_retry_until_max_attempts(
    fixture_scene: SceneItem, tmp_path: Path
) -> None:
    store = OutputStore(str(tmp_path))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        entry = entry_for(
            fixture_scene,
            status="failed",
            attempts=attempt,
            run_id=f"r{attempt}",
            processed_at=T0 + timedelta(days=attempt),
            error="boom",
        )
        write_ledger([entry], store, run_id=f"r{attempt}")
        ledger = read_ledger(store)
        assert attempts_so_far(ledger, fixture_scene.item_id) == attempt
        expected = [fixture_scene.item_id] if attempt < MAX_ATTEMPTS else []
        assert retry_ids(ledger) == expected
        assert seen_keys(ledger) == set()
        key = (fixture_scene.item_id, fixture_scene.updated)
        assert exhausted_keys(ledger) == ({key} if attempt == MAX_ATTEMPTS else set())


def test_later_success_supersedes_failure(fixture_scene: SceneItem, tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    failed = entry_for(
        fixture_scene, status="failed", attempts=1, run_id="r1", processed_at=T0, error="x"
    )
    ok = entry_for(
        fixture_scene,
        status="succeeded",
        attempts=2,
        run_id="r2",
        processed_at=T0 + timedelta(hours=1),
        n_rows=1,
    )
    write_ledger([failed], store, run_id="r1")
    write_ledger([ok], store, run_id="r2")
    ledger = read_ledger(store)
    assert retry_ids(ledger) == []
    assert exhausted_keys(ledger) == set()
    assert seen_keys(ledger) == {(fixture_scene.item_id, fixture_scene.updated)}
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_ledger.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/ledger.py`:
```python
"""Ledger of processed source items: one parquet file per run.

Fixed schema so files union cleanly, plus the full source item as JSON so
the catalogue can be rebuilt from the ledger alone. The latest entry per
item wins; a failed item is retried on the next runs until MAX_ATTEMPTS.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from wetland_change.catalogue.item import SceneItem
from wetland_change.store import OutputStore

MAX_ATTEMPTS = 3
_TS = pa.timestamp("us", tz="UTC")
LEDGER_SCHEMA = pa.schema(
    [
        ("item_id", pa.string()),
        ("collection", pa.string()),
        ("datetime", _TS),
        ("created", _TS),
        ("updated", _TS),
        ("tile", pa.string()),
        ("cloud_cover", pa.float64()),
        ("product_uri", pa.string()),
        ("status", pa.string()),
        ("attempts", pa.int32()),
        ("error", pa.string()),
        ("run_id", pa.string()),
        ("processed_at", _TS),
        ("n_rows", pa.int32()),
        ("observation_path", pa.string()),
        ("source_item", pa.string()),
    ]
)


@dataclass(frozen=True)
class LedgerEntry:
    item_id: str
    collection: str | None
    datetime: datetime | None
    created: datetime | None
    updated: datetime | None
    tile: str | None
    cloud_cover: float | None
    product_uri: str | None
    status: str
    attempts: int
    error: str | None
    run_id: str
    processed_at: datetime
    n_rows: int
    observation_path: str | None
    source_item: str | None


def entry_for(
    scene: SceneItem,
    *,
    status: str,
    attempts: int,
    run_id: str,
    processed_at: datetime,
    n_rows: int = 0,
    observation_path: str | None = None,
    error: str | None = None,
) -> LedgerEntry:
    return LedgerEntry(
        item_id=scene.item_id,
        collection=scene.collection,
        datetime=scene.datetime,
        created=scene.created,
        updated=scene.updated,
        tile=scene.tile,
        cloud_cover=scene.cloud_cover,
        product_uri=scene.product_uri,
        status=status,
        attempts=attempts,
        error=error,
        run_id=run_id,
        processed_at=processed_at,
        n_rows=n_rows,
        observation_path=observation_path,
        source_item=json.dumps(scene.raw, sort_keys=True),
    )


def rejected_entry(
    item_id: str, reason: str, *, run_id: str, processed_at: datetime
) -> LedgerEntry:
    """An item the guard refused; never retried, re-logged while it is in range."""
    return LedgerEntry(
        item_id=item_id,
        collection=None,
        datetime=None,
        created=None,
        updated=None,
        tile=None,
        cloud_cover=None,
        product_uri=None,
        status="rejected",
        attempts=0,
        error=reason,
        run_id=run_id,
        processed_at=processed_at,
        n_rows=0,
        observation_path=None,
        source_item=None,
    )


def ledger_path(run_id: str, year: int) -> str:
    return f"ledger/year={year}/ledger_{run_id}.parquet"


def entries_to_table(entries: Sequence[LedgerEntry]) -> pa.Table:
    columns: dict[str, list[Any]] = {
        name: [getattr(entry, name) for entry in entries] for name in LEDGER_SCHEMA.names
    }
    return pa.table(columns, schema=LEDGER_SCHEMA)


def write_ledger(
    entries: Sequence[LedgerEntry], store: OutputStore, *, run_id: str
) -> list[str]:
    """One file per run (partitioned by the run's year)."""
    if not entries:
        return []
    year = entries[0].processed_at.year
    buffer = BytesIO()
    pq.write_table(entries_to_table(entries), buffer)
    return [store.write_bytes(ledger_path(run_id, year), buffer.getvalue())]


def read_ledger(store: OutputStore) -> pa.Table:
    paths = [p for p in store.list_files("ledger") if p.endswith(".parquet")]
    if not paths:
        return LEDGER_SCHEMA.empty_table()
    tables = [
        pq.read_table(BytesIO(store.read_bytes(path))).cast(LEDGER_SCHEMA) for path in paths
    ]
    return pa.concat_tables(tables)


def watermark(ledger: pa.Table) -> datetime | None:
    """Latest `created` seen, succeeded or failed."""
    if ledger.num_rows == 0:
        return None
    value = pc.max(ledger["created"]).as_py()
    return value if isinstance(value, datetime) else None


def _latest(ledger: pa.Table) -> pd.DataFrame:
    frame = ledger.to_pandas()
    if frame.empty:
        return frame
    ordered = frame.sort_values(["processed_at", "run_id"], kind="stable")
    return ordered.groupby("item_id", sort=False).tail(1)


def seen_keys(ledger: pa.Table) -> set[tuple[str, datetime]]:
    latest = _latest(ledger)
    if latest.empty:
        return set()
    ok = latest[latest["status"] == "succeeded"]
    return {
        (str(row.item_id), row.updated.to_pydatetime()) for row in ok.itertuples(index=False)
    }


def retry_ids(ledger: pa.Table, *, max_attempts: int = MAX_ATTEMPTS) -> list[str]:
    latest = _latest(ledger)
    if latest.empty:
        return []
    failed = latest[(latest["status"] == "failed") & (latest["attempts"] < max_attempts)]
    return sorted(str(item_id) for item_id in failed["item_id"])


def exhausted_keys(
    ledger: pa.Table, *, max_attempts: int = MAX_ATTEMPTS
) -> set[tuple[str, datetime]]:
    """Items that failed `max_attempts` times; skipped until republished."""
    latest = _latest(ledger)
    if latest.empty:
        return set()
    done = latest[(latest["status"] == "failed") & (latest["attempts"] >= max_attempts)]
    return {
        (str(row.item_id), row.updated.to_pydatetime())
        for row in done.itertuples(index=False)
    }


def attempts_so_far(ledger: pa.Table, item_id: str) -> int:
    latest = _latest(ledger)
    if latest.empty:
        return 0
    match = latest[latest["item_id"] == item_id]
    return int(match["attempts"].iloc[0]) if not match.empty else 0
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_ledger.py`
Expected: `5 passed`. Note the retry test now also checks that the third failure moves the item from `retry_ids` to `exhausted_keys`.

---

## Task 19: Run manifest

**Files:**
- Create: `src/wetland_change/manifest.py`
- Test: `tests/test_manifest.py`

**Step 1: Write the failing tests**

`tests/test_manifest.py`:
```python
import json
from datetime import UTC, datetime
from pathlib import Path

from wetland_change.manifest import (
    RunManifest,
    config_sha256,
    manifest_path,
    new_run_id,
    write_manifest,
)
from wetland_change.store import OutputStore

NOW = datetime(2026, 10, 29, 10, 5, 7, tzinfo=UTC)


def test_new_run_id_is_sortable_utc_stamp() -> None:
    assert new_run_id(NOW) == "20261029T100507Z"


def test_config_sha256(tmp_path: Path) -> None:
    path = tmp_path / "p.toml"
    path.write_text("a = 1\n")
    assert config_sha256(path) == config_sha256(path)
    assert len(config_sha256(path)) == 64


def test_write_manifest_round_trips(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    manifest = RunManifest(
        run_id="r1",
        started_at=NOW,
        finished_at=NOW,
        package_version="0.1.0",
        config_sha256="abc",
        endpoint="https://example",
        collection="sentinel-2-c1-l2a",
        watermark_before=None,
        watermark_after=NOW,
        discovered=2,
        processed=1,
        failed=1,
        rejected=0,
        skipped_seen=0,
        skipped_filter=3,
        observation_files=["observations/a.parquet"],
        ledger_files=["ledger/year=2026/ledger_r1.parquet"],
    )
    relpath = write_manifest(manifest, store)
    assert relpath == manifest_path("r1") == "runs/r1.json"
    payload = json.loads(store.read_bytes(relpath))
    assert payload["run_id"] == "r1"
    assert payload["watermark_before"] is None
    assert payload["watermark_after"] == "2026-10-29T10:05:07+00:00"
    assert payload["observation_files"] == ["observations/a.parquet"]
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_manifest.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/manifest.py`:
```python
"""Run manifest: what one run saw, did and wrote."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from wetland_change.store import OutputStore


def new_run_id(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def config_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_path(run_id: str) -> str:
    return f"runs/{run_id}.json"


@dataclass
class RunManifest:
    run_id: str
    started_at: datetime
    finished_at: datetime | None
    package_version: str
    config_sha256: str
    endpoint: str
    collection: str
    watermark_before: datetime | None
    watermark_after: datetime | None
    discovered: int = 0
    processed: int = 0
    failed: int = 0
    rejected: int = 0
    skipped_seen: int = 0
    skipped_filter: int = 0
    observation_files: list[str] = field(default_factory=list)
    ledger_files: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        def _default(value: Any) -> str:
            if isinstance(value, datetime):
                return value.isoformat()
            raise TypeError(f"not serialisable: {type(value).__name__}")

        return json.dumps(asdict(self), indent=2, sort_keys=True, default=_default)


def write_manifest(manifest: RunManifest, store: OutputStore) -> str:
    return store.write_bytes(manifest_path(manifest.run_id), manifest.to_json().encode())
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_manifest.py`
Expected: `3 passed`.

---

## Task 20: Pipeline orchestration

**Files:**
- Create: `src/wetland_change/pipeline.py`
- Test: `tests/test_pipeline.py`

**Step 1: Write the failing tests**

`tests/test_pipeline.py`:
```python
from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyproj
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from tests.conftest import REQUIRED_ASSETS
from wetland_change.aoi import AoiPolygon
from wetland_change.config import AoiConfig, OutputConfig, PipelineConfig, StacConfig, WaterConfig
from wetland_change.ledger import read_ledger, retry_ids
from wetland_change.manifest import RunManifest
from wetland_change.pipeline import run_once
from wetland_change.raster.read import RasterioReader
from wetland_change.store import OutputStore

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
TO_4326 = pyproj.Transformer.from_crs(32750, 4326, always_xy=True).transform


class FakeSearch:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    def items_as_dicts(self) -> Iterator[dict[str, Any]]:
        yield from copy.deepcopy(self._items)


class FakeClient:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items

    def search(self, **kwargs: Any) -> FakeSearch:
        if "ids" in kwargs:
            return FakeSearch([i for i in self.items if i["id"] in kwargs["ids"]])
        return FakeSearch(self.items)


def _config(tmp_path: Path) -> PipelineConfig:
    return PipelineConfig(
        stac=StacConfig(
            endpoint="https://example.invalid",
            collection="sentinel-2-c1-l2a",
            cloud_cover_max=20.0,
            required_assets=REQUIRED_ASSETS,
        ),
        aoi=AoiConfig(
            ramsar_path=Path("unused"), waterbodies_path=Path("unused"), site_prefixes=[]
        ),
        water=WaterConfig(),
        output=OutputConfig(root=str(tmp_path / "out")),
    )


def _polygons(fixture_polygon: BaseGeometry) -> list[AoiPolygon]:
    lake = AoiPolygon(
        "ramsar-52",
        "Forrestdale & Thomsons Lakes",
        "ramsar",
        fixture_polygon,
        shapely_transform(TO_4326, fixture_polygon),
    )
    off_scene = box(500000, 6442000, 500300, 6442300)
    far = AoiPolygon("ramsar-99", "Elsewhere", "ramsar", off_scene, shapely_transform(TO_4326, off_scene))
    return [lake, far]


def _run(
    tmp_path: Path, client: FakeClient, polygons: list[AoiPolygon], now: datetime
) -> RunManifest:
    cfg = _config(tmp_path)
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text("# test\n")
    return run_once(
        cfg,
        client=client,
        reader=RasterioReader(),
        store=OutputStore(cfg.output.root),
        polygons=polygons,
        now=now,
        config_path=config_path,
    )


def test_run_once_end_to_end_offline(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    manifest = _run(tmp_path, FakeClient([fixture_item]), _polygons(fixture_polygon), NOW)
    assert manifest.run_id == "20261029T100000Z"
    assert (manifest.discovered, manifest.processed, manifest.failed) == (1, 1, 0)
    assert manifest.watermark_before is None
    assert manifest.watermark_after is not None
    assert len(manifest.observation_files) == 1
    assert len(manifest.ledger_files) == 1
    out = tmp_path / "out"
    assert (out / "runs" / "20261029T100000Z.json").exists()
    frame = gpd.read_parquet(out / manifest.observation_files[0])
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["polygon_id"] == "ramsar-52"
    assert row["run_id"] == manifest.run_id
    assert row["valid_fraction"] > 0.9
    assert row["water_ha_scl"] > 5.0
    assert frame.crs.to_epsg() == 4326


def test_rerun_is_incremental(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    client = FakeClient([fixture_item])
    first = _run(tmp_path, client, _polygons(fixture_polygon), NOW)
    second = _run(tmp_path, client, _polygons(fixture_polygon), NOW + timedelta(days=1))
    assert second.watermark_before == first.watermark_after
    assert (second.discovered, second.processed, second.skipped_seen) == (0, 0, 1)
    assert second.observation_files == []
    assert sorted((tmp_path / "out" / "observations").rglob("*.parquet")) == [
        tmp_path / "out" / first.observation_files[0]
    ]


def test_failed_scene_is_recorded_and_retried_three_times(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    broken = copy.deepcopy(fixture_item)
    broken["assets"]["green"]["href"] = str(tmp_path / "missing.tif")
    client = FakeClient([broken])
    store = OutputStore(str(tmp_path / "out"))
    for attempt in range(1, 5):
        manifest = _run(tmp_path, client, _polygons(fixture_polygon), NOW + timedelta(days=attempt))
        ledger = read_ledger(store)
        if attempt <= 3:
            assert manifest.failed == 1
            assert retry_ids(ledger) == ([broken["id"]] if attempt < 3 else [])
        else:
            assert manifest.failed == 0
            assert manifest.discovered == 0
    assert manifest.observation_files == []


def test_scaling_mismatch_fails_the_scene(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    tampered = copy.deepcopy(fixture_item)
    tampered["assets"]["green"]["raster:bands"][0]["offset"] = 0.0
    manifest = _run(tmp_path, FakeClient([tampered]), _polygons(fixture_polygon), NOW)
    assert manifest.failed == 1
    ledger = read_ledger(OutputStore(str(tmp_path / "out"))).to_pandas()
    assert "offset" in ledger["error"].iloc[0]


def test_rejected_items_are_ledgered(
    fixture_item: dict[str, Any], fixture_polygon: BaseGeometry, tmp_path: Path
) -> None:
    wrong = copy.deepcopy(fixture_item)
    wrong["collection"] = "sentinel-2-l2a"
    manifest = _run(tmp_path, FakeClient([wrong]), _polygons(fixture_polygon), NOW)
    assert (manifest.rejected, manifest.processed) == (1, 0)
    ledger = read_ledger(OutputStore(str(tmp_path / "out"))).to_pandas()
    assert ledger["status"].tolist() == ["rejected"]
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_pipeline.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/pipeline.py`:
```python
"""One incremental run: discover, guard, read, summarise, write, ledger."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from wetland_change import __version__
from wetland_change.aoi import AoiPolygon, union_bbox_4326
from wetland_change.catalogue.item import SceneItem
from wetland_change.catalogue.search import StacClient, discover
from wetland_change.config import PipelineConfig, WaterConfig
from wetland_change.ledger import (
    LedgerEntry,
    attempts_so_far,
    entry_for,
    exhausted_keys,
    read_ledger,
    rejected_entry,
    retry_ids,
    seen_keys,
    watermark,
    write_ledger,
)
from wetland_change.manifest import RunManifest, config_sha256, new_run_id, write_manifest
from wetland_change.outputs.geoparquet import write_observations
from wetland_change.raster.read import RasterReader, read_stack
from wetland_change.raster.scaling import check_band_scaling, parse_product_metadata
from wetland_change.stats import ObservationRow, summarise
from wetland_change.store import OutputStore
from wetland_change.windows import plan_window

logger = logging.getLogger(__name__)


class SceneGridError(ValueError):
    """The scene is not on the operation grid."""


def process_scene(
    scene: SceneItem,
    polygons: list[AoiPolygon],
    *,
    reader: RasterReader,
    water: WaterConfig,
    operation_epsg: int,
    run_id: str,
) -> list[ObservationRow]:
    """Rows for every polygon the scene covers. Raises on any guard failure."""
    grid = reader.open_grid(scene.bands["green"].href)
    if grid.epsg != operation_epsg or scene.epsg != operation_epsg:
        raise SceneGridError(
            f"{scene.item_id}: grid EPSG {grid.epsg}, item EPSG {scene.epsg}, "
            f"operation EPSG {operation_epsg}"
        )
    esa = parse_product_metadata(reader.read_text(scene.product_metadata_href))
    for band in scene.bands.values():
        check_band_scaling(band, esa)
    rows: list[ObservationRow] = []
    for polygon in polygons:
        planned = plan_window(polygon.geometry, grid)
        if planned is None:
            continue
        stack = read_stack(scene, planned, reader)
        rows.append(summarise(polygon, scene, stack, planned, water=water, run_id=run_id))
    return rows


def run_once(
    cfg: PipelineConfig,
    *,
    client: StacClient,
    reader: RasterReader,
    store: OutputStore,
    polygons: list[AoiPolygon],
    now: datetime,
    config_path: Path,
) -> RunManifest:
    """Process everything new since the ledger watermark. Never aborts on a
    single scene; failures go to the ledger and are retried next run."""
    run_id = new_run_id(now)
    ledger = read_ledger(store)
    before = watermark(ledger)
    created_from = (
        before - timedelta(days=cfg.stac.watermark_overlap_days) if before else None
    )
    discovery = discover(
        client,
        cfg.stac,
        bbox=union_bbox_4326(polygons),
        polygons_4326=[p.geometry_4326 for p in polygons],
        created_from=created_from,
        seen=seen_keys(ledger) | exhausted_keys(ledger),
        retry_ids=retry_ids(ledger),
    )
    manifest = RunManifest(
        run_id=run_id,
        started_at=now,
        finished_at=None,
        package_version=__version__,
        config_sha256=config_sha256(config_path),
        endpoint=cfg.stac.endpoint,
        collection=cfg.stac.collection,
        watermark_before=before,
        watermark_after=before,
        discovered=len(discovery.scenes),
        rejected=len(discovery.rejected),
        skipped_seen=discovery.skipped_seen,
        skipped_filter=discovery.skipped_filter,
    )
    entries: list[LedgerEntry] = []
    for scene in discovery.scenes:
        attempts = attempts_so_far(ledger, scene.item_id) + 1
        try:
            rows = process_scene(
                scene,
                polygons,
                reader=reader,
                water=cfg.water,
                operation_epsg=cfg.aoi.operation_epsg,
                run_id=run_id,
            )
            path = write_observations(rows, store) if rows else None
        except Exception as exc:
            logger.exception("scene %s failed (attempt %d)", scene.item_id, attempts)
            entries.append(
                entry_for(
                    scene,
                    status="failed",
                    attempts=attempts,
                    run_id=run_id,
                    processed_at=now,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            manifest.failed += 1
            continue
        entries.append(
            entry_for(
                scene,
                status="succeeded",
                attempts=attempts,
                run_id=run_id,
                processed_at=now,
                n_rows=len(rows),
                observation_path=path,
            )
        )
        manifest.processed += 1
        if path:
            manifest.observation_files.append(path)
    for item_id, reason in discovery.rejected:
        entries.append(rejected_entry(item_id, reason, run_id=run_id, processed_at=now))
    manifest.ledger_files = write_ledger(entries, store, run_id=run_id)
    manifest.watermark_after = watermark(read_ledger(store))
    manifest.finished_at = now
    write_manifest(manifest, store)
    return manifest
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_pipeline.py`
Expected: `5 passed`. The retry test logs one traceback per failed attempt; that is expected output, not a failure.

---

## Task 21: Command line

**Files:**
- Create: `src/wetland_change/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing tests**

`tests/test_cli.py`:
```python
from typer.testing import CliRunner

from wetland_change.cli import app

runner = CliRunner()


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("discover", "run", "verify"):
        assert command in result.output


def test_run_help_mentions_config() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.output
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_cli.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

`src/wetland_change/cli.py` (the `verify` command body is completed in Task 22; write it with the stub shown here first):
```python
"""Command line: discover, run, verify."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from wetland_change.aoi import AoiPolygon, load_ramsar, union_bbox_4326
from wetland_change.catalogue.search import discover as discover_items
from wetland_change.catalogue.search import open_client
from wetland_change.config import PipelineConfig, load_config
from wetland_change.ledger import (
    exhausted_keys,
    read_ledger,
    retry_ids,
    seen_keys,
    watermark,
)
from wetland_change.pipeline import run_once
from wetland_change.raster.read import RasterioReader
from wetland_change.store import OutputStore

app = typer.Typer(add_completion=False, no_args_is_help=True)

ConfigOption = Annotated[Path, typer.Option("--config", help="Pipeline TOML")]


def _load(config: Path) -> tuple[PipelineConfig, list[AoiPolygon]]:
    cfg = load_config(config)
    polygons = load_ramsar(
        cfg.aoi.ramsar_path,
        site_prefixes=cfg.aoi.site_prefixes,
        operation_epsg=cfg.aoi.operation_epsg,
    )
    if not polygons:
        raise typer.BadParameter("no AOI polygons matched; run scripts/fetch_aoi.py")
    return cfg, polygons


@app.callback()
def _main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)


@app.command()
def discover(config: ConfigOption = Path("config/pipeline.toml")) -> None:
    """List scenes the next run would process, without reading any raster."""
    cfg, polygons = _load(config)
    ledger = read_ledger(OutputStore(cfg.output.root))
    before = watermark(ledger)
    result = discover_items(
        open_client(cfg.stac.endpoint),
        cfg.stac,
        bbox=union_bbox_4326(polygons),
        polygons_4326=[p.geometry_4326 for p in polygons],
        created_from=(
            before - timedelta(days=cfg.stac.watermark_overlap_days) if before else None
        ),
        seen=seen_keys(ledger) | exhausted_keys(ledger),
        retry_ids=retry_ids(ledger),
    )
    for scene in result.scenes:
        typer.echo(f"{scene.item_id}\t{scene.tile}\t{scene.cloud_cover:.2f}\t{scene.created.isoformat()}")
    typer.echo(
        f"{len(result.scenes)} to process, {result.skipped_seen} seen, "
        f"{result.skipped_filter} filtered, {len(result.rejected)} rejected"
    )


@app.command()
def run(
    config: ConfigOption = Path("config/pipeline.toml"),
    now: Annotated[datetime | None, typer.Option(help="Run time, UTC")] = None,
) -> None:
    """One incremental run against the configured output root."""
    cfg, polygons = _load(config)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    manifest = run_once(
        cfg,
        client=open_client(cfg.stac.endpoint),
        reader=RasterioReader(),
        store=OutputStore(cfg.output.root),
        polygons=polygons,
        now=when,
        config_path=config,
    )
    typer.echo(manifest.to_json())
    if manifest.failed:
        raise typer.Exit(code=2)


@app.command()
def verify(
    config: ConfigOption = Path("config/pipeline.toml"),
    run_id: Annotated[str | None, typer.Option(help="Defaults to the latest run")] = None,
) -> None:
    """Score the known-good checks for one run and write the report."""
    raise typer.Exit(code=1)  # replaced in Task 22
```

**Step 4: Run to verify they pass**

Run: `uv run pytest -q tests/test_cli.py`
Expected: `2 passed`.

---

## Task 22: Verification checks and report

Milestone 1 rows of the matrix: reflectance scaling (offline), SCL read and alignment (live), reads the right bytes (live, Planetary Computer), water extent against DEA S2 Water Observations (live), plus the report writer the `verify` command and Milestone 2 build on.

**Files:**
- Create: `src/wetland_change/verify/__init__.py` (empty), `src/wetland_change/verify/checks.py`, `src/wetland_change/verify/scaling.py`, `src/wetland_change/verify/scl.py`, `src/wetland_change/verify/pixels.py`, `src/wetland_change/verify/wo.py`, `src/wetland_change/verify/run.py`
- Modify: `src/wetland_change/cli.py` (`verify` body)
- Test: `tests/test_verify.py`, `tests/test_live_verify.py`

**Step 1: Write the failing offline tests**

`tests/test_verify.py`:
```python
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from tests.conftest import FIXTURE_DIR
from wetland_change.catalogue.item import SceneItem
from wetland_change.store import OutputStore
from wetland_change.verify.checks import Check, write_report
from wetland_change.verify.pixels import pc_item_id
from wetland_change.verify.scaling import scaling_check
from wetland_change.verify.scl import scl_shares
from wetland_change.verify.wo import WO_EXCLUDE, WO_WET, wo_agreement


def test_scaling_check_passes_on_fixture(fixture_scene: SceneItem) -> None:
    check = scaling_check(fixture_scene, (FIXTURE_DIR / "product_metadata.xml").read_text())
    assert check.passed is True
    assert check.name == "reflectance_scaling"
    assert "ESA" in check.reference


def test_scaling_check_fails_on_tampered_xml(fixture_scene: SceneItem) -> None:
    xml = (FIXTURE_DIR / "product_metadata.xml").read_text().replace(
        "BOA_ADD_OFFSET", "BOA_ADD_OFFSET_X"
    )
    check = scaling_check(fixture_scene, xml)
    assert check.passed is False
    assert "BOA_ADD_OFFSET" in check.detail["error"]


def test_scl_shares_ignore_nodata() -> None:
    scl = np.array([[0, 0, 6, 6], [4, 5, 8, 9]], dtype=np.uint8)
    shares = scl_shares(scl)
    assert shares["water"] == 100 * 2 / 6
    assert shares["vegetation"] == 100 * 1 / 6
    assert shares["cloud"] == 100 * 2 / 6


def test_pc_item_id_drops_baseline_token() -> None:
    uri = "S2C_MSIL2A_20261027T021211_N0513_R060_T50HLK_20261027T071801.SAFE"
    assert pc_item_id(uri) == "S2C_MSIL2A_20261027T021211_R060_T50HLK_20261027T071801"


def test_wo_agreement_on_mutually_clear_pixels() -> None:
    water = np.array([[True, True], [False, False]])
    clear = np.array([[True, True], [True, False]])
    wo = np.array([[WO_WET, 0], [0, WO_WET]], dtype=np.uint8)
    agreement, n = wo_agreement(water, clear, wo)
    assert n == 3
    assert agreement == 2 / 3
    wo[0, 1] |= WO_EXCLUDE & 64
    agreement, n = wo_agreement(water, clear, wo)
    assert (agreement, n) == (1.0, 2)


def test_wo_agreement_with_nothing_clear_is_nan() -> None:
    agreement, n = wo_agreement(np.zeros((1, 1), bool), np.zeros((1, 1), bool), np.zeros((1, 1), np.uint8))
    assert n == 0 and np.isnan(agreement)


def test_write_report(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "out"))
    checks = [
        Check("a", passed=True, measured=0.99, threshold=0.95, reference="x"),
        Check("b", passed=None, measured=None, threshold=None, reference="y", detail={"reason": "skipped"}),
    ]
    json_path, md_path = write_report(
        checks,
        store=store,
        run_id="r1",
        docs_dir=tmp_path / "docs",
        generated_at=datetime(2026, 10, 29, tzinfo=UTC),
    )
    payload = json.loads(store.read_bytes(json_path))
    assert payload["run_id"] == "r1"
    assert payload["all_passed"] is True
    assert payload["checks"][1]["passed"] is None
    assert md_path is not None and md_path.exists()
    assert "| a |" in md_path.read_text()
```

**Step 2: Run to verify they fail**

Run: `uv run pytest -q tests/test_verify.py`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementations**

`src/wetland_change/verify/checks.py`:
```python
"""Check results and the verification report."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wetland_change.store import OutputStore


@dataclass
class Check:
    name: str
    passed: bool | None
    measured: float | None
    threshold: float | None
    reference: str
    detail: dict[str, Any] = field(default_factory=dict)


def report_path(run_id: str) -> str:
    return f"verification/{run_id}.json"


def _markdown(run_id: str, checks: list[Check], generated_at: datetime) -> str:
    lines = [
        f"# Verification report {run_id}",
        "",
        f"Generated {generated_at.isoformat()}.",
        "",
        "| check | passed | measured | threshold | reference |",
        "|---|---|---|---|---|",
    ]
    for c in checks:
        status = "skipped" if c.passed is None else ("yes" if c.passed else "no")
        measured = "" if c.measured is None else f"{c.measured:.4f}"
        threshold = "" if c.threshold is None else f"{c.threshold}"
        lines.append(f"| {c.name} | {status} | {measured} | {threshold} | {c.reference} |")
    return "\n".join(lines) + "\n"


def write_report(
    checks: list[Check],
    *,
    store: OutputStore,
    run_id: str,
    docs_dir: Path | None,
    generated_at: datetime | None = None,
) -> tuple[str, Path | None]:
    """JSON beside the outputs; Markdown under docs/research when given."""
    when = generated_at or datetime.now(UTC)
    payload = {
        "run_id": run_id,
        "generated_at": when.isoformat(),
        "all_passed": all(c.passed for c in checks if c.passed is not None),
        "checks": [asdict(c) for c in checks],
    }
    json_path = store.write_bytes(
        report_path(run_id), json.dumps(payload, indent=2, default=str).encode()
    )
    md_path: Path | None = None
    if docs_dir is not None:
        docs_dir.mkdir(parents=True, exist_ok=True)
        md_path = docs_dir / f"verification-{run_id}.md"
        md_path.write_text(_markdown(run_id, checks, when))
    return json_path, md_path
```

`src/wetland_change/verify/scaling.py`:
```python
"""Matrix row: reflectance scaling against the ESA product XML."""

from __future__ import annotations

from wetland_change.catalogue.item import SceneItem
from wetland_change.raster.scaling import (
    ScalingMismatch,
    check_band_scaling,
    parse_product_metadata,
)
from wetland_change.verify.checks import Check


def scaling_check(scene: SceneItem, xml_text: str) -> Check:
    reference = "ESA MTD_MSIL2A.xml BOA_QUANTIFICATION_VALUE and BOA_ADD_OFFSET"
    try:
        esa = parse_product_metadata(xml_text)
        for band in scene.bands.values():
            check_band_scaling(band, esa)
    except ScalingMismatch as exc:
        return Check(
            "reflectance_scaling", passed=False, measured=None, threshold=None,
            reference=reference, detail={"item": scene.item_id, "error": str(exc)},
        )
    return Check(
        "reflectance_scaling", passed=True, measured=None, threshold=None,
        reference=reference,
        detail={"item": scene.item_id, "scale": esa.scale, "offset": esa.offset},
    )
```

`src/wetland_change/verify/scl.py`:
```python
"""Matrix row: SCL read and alignment against the ESA class percentages.

The item carries ESA's own class shares (`s2:water_percentage` and so on,
computed over SCL != 0). Recomputing them from the 1/16 overview must land
within one percentage point, which proves the right SCL file was read and
the class codes are interpreted correctly.
"""

from __future__ import annotations

import numpy as np

from wetland_change.catalogue.item import SceneItem
from wetland_change.raster.read import RasterReader
from wetland_change.verify.checks import Check

_CLASSES: dict[str, tuple[int, ...]] = {
    "water": (6,),
    "vegetation": (4,),
    "not_vegetated": (5,),
    "cloud": (8, 9, 10),
}
_PROPERTIES = {
    "water": "s2:water_percentage",
    "vegetation": "s2:vegetation_percentage",
    "not_vegetated": "s2:not_vegetated_percentage",
    "cloud": "eo:cloud_cover",
}


def scl_shares(scl: np.ndarray) -> dict[str, float]:
    valid = scl[scl != 0]
    n = valid.size
    return {
        name: (100.0 * float(np.isin(valid, classes).sum()) / n) if n else float("nan")
        for name, classes in _CLASSES.items()
    }


def scl_checks(
    scene: SceneItem, reader: RasterReader, *, factor: int = 16, tolerance_pp: float = 1.0
) -> list[Check]:
    shares = scl_shares(reader.read_overview(scene.scl_href, factor))
    checks: list[Check] = []
    for name, prop in _PROPERTIES.items():
        reference = scene.raw["properties"].get(prop)
        if reference is None:
            checks.append(Check(f"scl_share_{name}", None, shares[name], tolerance_pp, prop))
            continue
        diff = abs(shares[name] - float(reference))
        checks.append(
            Check(
                f"scl_share_{name}",
                passed=diff <= tolerance_pp,
                measured=shares[name],
                threshold=tolerance_pp,
                reference=f"{prop} = {reference}",
                detail={"item": scene.item_id, "overview_factor": factor, "diff_pp": diff},
            )
        )
    return checks
```

`src/wetland_change/verify/pixels.py`:
```python
"""Matrix row: reads the right bytes, against Planetary Computer.

Planetary Computer hosts the same ESA product under an id without the
`N0513` baseline token and signs asset hrefs with a SAS token. The same
window must give the same transform and bit-identical DN.
"""

from __future__ import annotations

import numpy as np
from rasterio.windows import Window

from wetland_change.catalogue.item import SceneItem
from wetland_change.raster.env import cog_env
from wetland_change.raster.read import RasterioReader, RasterReader
from wetland_change.verify.checks import Check

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_COLLECTION = "sentinel-2-l2a"


def pc_item_id(product_uri: str) -> str:
    stem = product_uri.removesuffix(".SAFE")
    return "_".join(token for token in stem.split("_") if not token.startswith("N0"))


def pixel_check(scene: SceneItem, reader: RasterReader, window: Window) -> Check:
    import planetary_computer
    import pystac_client

    name = "pixels_vs_planetary_computer"
    reference = f"{PC_STAC} {PC_COLLECTION} {pc_item_id(scene.product_uri)} B03"
    catalog = pystac_client.Client.open(PC_STAC, modifier=planetary_computer.sign_inplace)
    items = list(
        catalog.search(collections=[PC_COLLECTION], ids=[pc_item_id(scene.product_uri)]).items()
    )
    if not items:
        return Check(name, None, None, None, reference, {"reason": "not on Planetary Computer yet"})
    pc_href = str(items[0].assets["B03"].href)
    env = {k: v for k, v in cog_env().items() if k != "CPL_VSIL_CURL_ALLOWED_EXTENSIONS"}
    pc_reader = RasterioReader(env={**env, "AWS_NO_SIGN_REQUEST": "NO"})
    es_grid = reader.open_grid(scene.bands["green"].href)
    pc_grid = pc_reader.open_grid(pc_href)
    es_dn = reader.read(scene.bands["green"].href, window)
    pc_dn = pc_reader.read(pc_href, window)
    same_transform = es_grid.transform == pc_grid.transform
    identical = bool(np.array_equal(es_dn, pc_dn))
    return Check(
        name,
        passed=same_transform and identical,
        measured=float(np.mean(es_dn == pc_dn)),
        threshold=1.0,
        reference=reference,
        detail={
            "item": scene.item_id,
            "same_transform": same_transform,
            "window": [window.col_off, window.row_off, window.width, window.height],
        },
    )
```

`src/wetland_change/verify/wo.py`:
```python
"""Matrix row: water extent against DEA Sentinel-2 Water Observations.

`ga_s2_wo_provisional_3` is on the same 10 m grid (EPSG:32750) for the same
pass. Bit 128 is wet; bits 1 (nodata), 2 (non-contiguous), 32 (cloud
shadow) and 64 (cloud) exclude a pixel. Agreement is scored on pixels both
products call clear.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import requests

from wetland_change.catalogue.item import SceneItem
from wetland_change.config import WaterConfig
from wetland_change.indices import mndwi, ndwi
from wetland_change.mask import clear_mask
from wetland_change.raster.env import cog_env
from wetland_change.raster.read import BandStack, RasterioReader
from wetland_change.verify.checks import Check
from wetland_change.windows import PlannedWindow

DEA_STAC = "https://explorer.dea.ga.gov.au/stac"
WO_COLLECTION = "ga_s2_wo_provisional_3"
WO_WET = 128
WO_EXCLUDE = 1 | 2 | 32 | 64
_S3 = "s3://dea-public-data/"
_HTTPS = "https://dea-public-data.s3.ap-southeast-2.amazonaws.com/"


def wo_agreement(
    pipeline_water: np.ndarray, pipeline_clear: np.ndarray, wo: np.ndarray
) -> tuple[float, int]:
    """(share of mutually clear pixels where the two agree, count)."""
    wo_clear = (wo & WO_EXCLUDE) == 0
    both = pipeline_clear & wo_clear
    n = int(both.sum())
    if n == 0:
        return float("nan"), 0
    wo_water = (wo & WO_WET) > 0
    return float(np.mean(pipeline_water[both] == wo_water[both])), n


def find_wo_href(scene: SceneItem, bbox_4326: tuple[float, float, float, float]) -> str | None:
    """The WO `water` asset for the same date and MGRS tile, as https."""
    day = scene.datetime.date().isoformat()
    body: dict[str, Any] = {
        "collections": [WO_COLLECTION],
        "bbox": list(bbox_4326),
        "datetime": f"{day}T00:00:00Z/{day}T23:59:59Z",
        "limit": 50,
    }
    response = requests.post(f"{DEA_STAC}/search", json=body, timeout=60)
    response.raise_for_status()
    tile_token = f"/{scene.tile[2:]}/"
    for feature in response.json().get("features", []):
        href = str(feature["assets"]["water"]["href"])
        if tile_token in href:
            return href.replace(_S3, _HTTPS)
    return None


def dea_reader() -> RasterioReader:
    return RasterioReader(env=cog_env(AWS_REGION="ap-southeast-2"))


def wo_check(
    scene: SceneItem,
    stack: BandStack,
    planned: PlannedWindow,
    inside: np.ndarray,
    *,
    water: WaterConfig,
    wo_href: str,
    reader: RasterioReader,
    agreement_min: float = 0.95,
) -> Check:
    name = "water_vs_dea_s2_wo"
    wo_grid = reader.open_grid(wo_href)
    if wo_grid.transform != reader.open_grid(scene.bands["green"].href).transform:
        return Check(name, False, None, agreement_min, wo_href, {"reason": "grid differs"})
    wo = reader.read(wo_href, planned.window10)
    clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
    index = ndwi(stack.green, stack.nir) if water.method == "ndwi" else mndwi(stack.green, stack.swir16)
    with np.errstate(invalid="ignore"):
        pipeline_water = clear & (index > water.threshold)
    agreement, n = wo_agreement(pipeline_water, clear, wo)
    scl_agreement, _ = wo_agreement(clear & (stack.scl == 6), clear, wo)
    return Check(
        name,
        passed=bool(agreement >= agreement_min) if n else None,
        measured=agreement,
        threshold=agreement_min,
        reference=wo_href,
        detail={
            "item": scene.item_id,
            "n_mutually_clear": n,
            "method": water.method,
            "threshold": water.threshold,
            "scl_agreement": scl_agreement,
        },
    )
```

`src/wetland_change/verify/run.py`:
```python
"""Run every Milestone 1 check over the scenes of one run."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from wetland_change.aoi import AoiPolygon, union_bbox_4326
from wetland_change.catalogue.item import SceneItem, parse_item
from wetland_change.config import PipelineConfig
from wetland_change.ledger import read_ledger
from wetland_change.raster.read import RasterioReader, read_stack
from wetland_change.stats import rasterise
from wetland_change.store import OutputStore
from wetland_change.verify.checks import Check, write_report
from wetland_change.verify.pixels import pixel_check
from wetland_change.verify.scaling import scaling_check
from wetland_change.verify.scl import scl_checks
from wetland_change.verify.wo import dea_reader, find_wo_href, wo_check
from wetland_change.windows import plan_window

logger = logging.getLogger(__name__)


def scenes_for_run(cfg: PipelineConfig, store: OutputStore, run_id: str) -> list[SceneItem]:
    frame = read_ledger(store).to_pandas()
    rows = frame[(frame["run_id"] == run_id) & (frame["status"] == "succeeded")]
    return [
        parse_item(
            json.loads(source), collection=cfg.stac.collection, required_assets=cfg.stac.required_assets
        )
        for source in rows["source_item"]
    ]


def latest_run_id(store: OutputStore) -> str | None:
    runs = [p for p in store.list_files("runs") if p.endswith(".json")]
    return runs[-1].rsplit("/", 1)[-1].removesuffix(".json") if runs else None


def verify_run(
    cfg: PipelineConfig,
    store: OutputStore,
    run_id: str,
    *,
    polygons: list[AoiPolygon],
    reader: RasterioReader | None = None,
    docs_dir: Path | None = Path("docs/research"),
) -> list[Check]:
    reader = reader or RasterioReader()
    checks: list[Check] = []
    for scene in scenes_for_run(cfg, store, run_id):
        checks.append(scaling_check(scene, reader.read_text(scene.product_metadata_href)))
        checks.extend(scl_checks(scene, reader))
        grid = reader.open_grid(scene.bands["green"].href)
        planned_first = None
        wo_href = find_wo_href(scene, union_bbox_4326(polygons))
        for polygon in polygons:
            planned = plan_window(polygon.geometry, grid)
            if planned is None:
                continue
            planned_first = planned_first or planned
            if wo_href is None:
                continue
            stack = read_stack(scene, planned, reader)
            inside = rasterise(polygon.geometry, stack.transform, stack.shape)
            check = wo_check(
                scene, stack, planned, inside, water=cfg.water, wo_href=wo_href, reader=dea_reader()
            )
            check.detail["polygon_id"] = polygon.polygon_id
            checks.append(check)
        if planned_first is not None:
            try:
                checks.append(pixel_check(scene, reader, planned_first.window10))
            except Exception as exc:
                logger.warning("pixel check failed for %s: %s", scene.item_id, exc)
                checks.append(
                    Check("pixels_vs_planetary_computer", None, None, None, "PC", {"error": str(exc)})
                )
    write_report(checks, store=store, run_id=run_id, docs_dir=docs_dir, generated_at=datetime.now(UTC))
    return checks
```

Then replace the `verify` body in `src/wetland_change/cli.py`:
```python
@app.command()
def verify(
    config: ConfigOption = Path("config/pipeline.toml"),
    run_id: Annotated[str | None, typer.Option(help="Defaults to the latest run")] = None,
) -> None:
    """Score the known-good checks for one run and write the report."""
    from wetland_change.verify.run import latest_run_id, verify_run

    cfg, polygons = _load(config)
    store = OutputStore(cfg.output.root)
    target = run_id or latest_run_id(store)
    if target is None:
        raise typer.BadParameter("no runs found in the output root")
    checks = verify_run(cfg, store, target, polygons=polygons)
    for check in checks:
        status = "skip" if check.passed is None else ("pass" if check.passed else "FAIL")
        typer.echo(f"{status}\t{check.name}\t{check.measured}\t{check.reference}")
    if any(check.passed is False for check in checks):
        raise typer.Exit(code=3)
```

**Step 4: Run the offline tests**

Run: `uv run pytest -q tests/test_verify.py tests/test_cli.py`
Expected: `9 passed`.

**Step 5: Write the live tests**

`tests/test_live_verify.py`:
```python
"""Live contract tests against Earth Search, Planetary Computer and DEA.

Run with: uv run pytest -q -m live tests/test_live_verify.py
"""

from __future__ import annotations

import pytest
from shapely.geometry import box

from tests.conftest import REQUIRED_ASSETS, load_fixture_item
from wetland_change.catalogue.item import parse_item
from wetland_change.config import WaterConfig
from wetland_change.raster.read import RasterioReader, read_stack
from wetland_change.stats import rasterise
from wetland_change.verify.pixels import pixel_check
from wetland_change.verify.scl import scl_checks
from wetland_change.verify.wo import dea_reader, find_wo_href, wo_check
from wetland_change.windows import plan_window

pytestmark = pytest.mark.live

THOMSONS_32750 = box(388400, 6441050, 390800, 6443700)
THOMSONS_4326 = (115.8168, -32.1615, 115.8421, -32.1378)


@pytest.fixture(scope="module")
def remote_scene():  # type: ignore[no-untyped-def]
    return parse_item(
        load_fixture_item(local=False),
        collection="sentinel-2-c1-l2a",
        required_assets=REQUIRED_ASSETS,
    )


def test_scl_shares_match_esa_percentages(remote_scene) -> None:  # type: ignore[no-untyped-def]
    checks = scl_checks(remote_scene, RasterioReader())
    assert all(c.passed for c in checks), [(c.name, c.measured, c.reference) for c in checks]


def test_pixels_match_planetary_computer(remote_scene) -> None:  # type: ignore[no-untyped-def]
    reader = RasterioReader()
    planned = plan_window(THOMSONS_32750, reader.open_grid(remote_scene.bands["green"].href))
    assert planned is not None
    check = pixel_check(remote_scene, reader, planned.window10)
    if check.passed is None:
        pytest.skip(check.detail["reason"])
    assert check.passed, check.detail


@pytest.mark.xfail(strict=True, reason="water method uncalibrated until spike S2 lands in config")
def test_water_agrees_with_dea_wo(remote_scene) -> None:  # type: ignore[no-untyped-def]
    reader = RasterioReader()
    grid = reader.open_grid(remote_scene.bands["green"].href)
    planned = plan_window(THOMSONS_32750, grid)
    assert planned is not None
    wo_href = find_wo_href(remote_scene, THOMSONS_4326)
    assert wo_href is not None
    stack = read_stack(remote_scene, planned, reader)
    inside = rasterise(THOMSONS_32750, stack.transform, stack.shape)
    check = wo_check(
        remote_scene, stack, planned, inside, water=WaterConfig(), wo_href=wo_href, reader=dea_reader()
    )
    assert check.detail["n_mutually_clear"] > 10000
    assert check.passed, check.detail
```

**Step 6: Run the live tests**

Run: `uv run pytest -q -m live tests/test_live_verify.py`
Expected: `2 passed, 1 xfailed` (the DEA agreement is 0.80 with the uncalibrated NDWI threshold, as measured on 2026-10-29; the strict xfail flips to a failure once spike S2 puts a calibrated method in config, which is the signal to drop the marker). If `test_pixels_match_planetary_computer` skips, Planetary Computer has not ingested the scene yet; rerun later.

**Step 7: Run the whole offline suite and the gates**

Run: `uv run ruff check src tests scripts && uv run ruff format --check src tests scripts && uv run mypy src scripts && uv run pytest -q`
Expected: all clean; `pytest` reports every offline test passing with the live tests deselected.

---

## Part 4: Pre-start spikes, decisions, final gate

Spikes 1, 2, 3, 4 and 8 from the design's pre-start list run here because they feed Milestone 1 config and assumptions. Spikes 5, 6, 7 and 9 (runner dry run, static catalogue, DuckDB over S3, historical tolerance) move to the Milestone 2 plan with the infrastructure they test. Spike scripts live under `scratch/spikes/` (gitignored, ruff-excluded); their outputs are LEARNINGS.md entries, config values and CSVs under `docs/research/`.

Every spike script imports the package, so each one is also a live integration run of the modules built in Parts 1 to 3.

---

## Task 23: Spike S1, Forrestdale seam between 50HLK and 50HMK

Hypothesis: the two tiles of one pass share the 10 m lattice (tile origins 300000 and 399960 differ by 9996 pixels, which is even), and the Forrestdale window reads the same DN from either tile in the overlap. SCL is produced per tile by Sen2Cor and may differ; record it either way.

**Files:**
- Create: `scratch/spikes/s1_seam.py`
- Modify: `LEARNINGS.md` (append under "Spike results")

**Step 1: Write the script**

`scratch/spikes/s1_seam.py`:
```python
"""Spike S1: Forrestdale window from both tiles of one pass."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pystac_client

from wetland_change.aoi import load_ramsar
from wetland_change.catalogue.item import parse_item
from wetland_change.config import load_config
from wetland_change.raster.read import RasterioReader, read_stack
from wetland_change.windows import plan_window

cfg = load_config(Path("config/pipeline.toml"))
forrestdale = [
    p for p in load_ramsar(cfg.aoi.ramsar_path, site_prefixes=cfg.aoi.site_prefixes,
                           operation_epsg=cfg.aoi.operation_epsg)
    if p.polygon_id == "ramsar-56"
][0]
client = pystac_client.Client.open(cfg.stac.endpoint)
items = list(
    client.search(
        collections=[cfg.stac.collection],
        intersects=forrestdale.geometry_4326,
        datetime="2026-09-01/2026-10-29",
        query={"eo:cloud_cover": {"lt": 5}},
        sortby=[{"field": "properties.datetime", "direction": "desc"}],
    ).items_as_dicts()
)
by_pass: dict[str, dict[str, dict]] = {}
for item in items:
    by_pass.setdefault(item["properties"]["datetime"][:16], {})[item["properties"]["grid:code"]] = item
pairs = [(k, v) for k, v in by_pass.items() if {"MGRS-50HLK", "MGRS-50HMK"} <= v.keys()]
if not pairs:
    sys.exit("no pass with both tiles under 5 % cloud in the window; widen the dates")
when, tiles = pairs[0]
print("pass", when, {k: v["id"] for k, v in tiles.items()})

reader = RasterioReader()
stacks = {}
for code, item in tiles.items():
    scene = parse_item(item, collection=cfg.stac.collection, required_assets=cfg.stac.required_assets)
    grid = reader.open_grid(scene.bands["green"].href)
    planned = plan_window(forrestdale.geometry, grid)
    assert planned is not None, code
    stack = read_stack(scene, planned, reader)
    minx, maxy = planned.transform10 * (0, 0)
    print(f"{code}: window {planned.window10} coverage {planned.scene_coverage:.3f} origin ({minx:.0f}, {maxy:.0f})")
    stacks[code] = (planned, stack)

(p_a, s_a), (p_b, s_b) = stacks["MGRS-50HLK"], stacks["MGRS-50HMK"]
ax0, ay0 = p_a.transform10 * (0, 0)
bx0, by0 = p_b.transform10 * (0, 0)
assert (ax0 - bx0) % 10 == 0 and (ay0 - by0) % 10 == 0, "lattices differ"
x0, y1 = max(ax0, bx0), min(ay0, by0)
x1 = min(ax0 + 10 * s_a.shape[1], bx0 + 10 * s_b.shape[1])
y0 = max(ay0 - 10 * s_a.shape[0], by0 - 10 * s_b.shape[0])
cols, rows = int((x1 - x0) / 10), int((y1 - y0) / 10)
print(f"overlap {cols} x {rows} px")


def crop(stack, x_origin, y_origin):
    c, r = int((x0 - x_origin) / 10), int((y_origin - y1) / 10)
    return {
        name: getattr(stack, name)[r : r + rows, c : c + cols]
        for name in ("green", "red", "nir", "swir16", "scl")
    }


a, b = crop(s_a, ax0, ay0), crop(s_b, bx0, by0)
for name in ("green", "red", "nir", "swir16"):
    both = np.isfinite(a[name]) & np.isfinite(b[name])
    diff = np.abs(a[name][both] - b[name][both])
    print(f"{name}: identical={bool(np.array_equal(a[name], b[name], equal_nan=True))} "
          f"max|diff|={diff.max():.5f} share_equal={np.mean(diff == 0):.4f} n={both.sum()}")
scl_same = np.mean(a["scl"] == b["scl"])
print(f"scl: share_equal={scl_same:.4f}; class 6 agreement="
      f"{np.mean((a['scl'] == 6) == (b['scl'] == 6)):.4f}")
```

**Step 2: Run it**

Run: `uv run python scratch/spikes/s1_seam.py`
Expected: prints one pass with both tile ids, two windows with the same 10 m origin modulo 10, an overlap of a few hundred pixels across, and per-band identity results. Reads take under 30 s total.

**Step 3: Record the result**

Append to `LEARNINGS.md` under "Spike results", filling in the measured values:
```markdown
### S1 Forrestdale seam (2026-10-29)

Pass <datetime>, items <50HLK id> and <50HMK id>. Lattices align (origins
differ by a multiple of 10 m). Overlap <cols> x <rows> px. Reflectance
bands identical: <yes/no; if no, max |diff| and share equal per band>.
SCL agreement <share>, water class agreement <share>.
Consequence: <per-scene rows with coverage fraction are sufficient / rows
from the two tiles must be reconciled downstream by ...>.
```

If the reflectance bands are not identical, also add a row to the design doc's verified facts table so Milestone 2 aggregation knows the seam is not exact.

---

## Task 24: Spike S2, water method calibration against DEA S2 Water Observations

The textbook NDWI threshold undercounts Thomsons water by two thirds (design, verified facts). This spike chooses the method and threshold for `water_ha_index` and writes them into `config/pipeline.toml`. Budget: about two hours including reads.

**Files:**
- Create: `scratch/spikes/s2_calibrate.py`
- Create: `docs/research/2026-10-29-water-calibration.csv` (script output)
- Modify: `config/pipeline.toml` (`[water]` method and threshold), `LEARNINGS.md`, `tests/test_live_verify.py` (drop the `xfail` marker)

**Step 1: Write the script**

`scratch/spikes/s2_calibrate.py`:
```python
"""Spike S2: threshold sweep for NDWI, MNDWI and SCL water against DEA WO.

Lakes: the four largest DEA Waterbodies polygons inside the Ramsar sites.
Passes: every c1 item under the configured cloud limit in the last 90 days,
which is what the provisional WO product retains.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pystac_client
from shapely.ops import unary_union

from wetland_change.aoi import load_ramsar, load_waterbodies, union_bbox_4326
from wetland_change.catalogue.item import parse_item
from wetland_change.config import load_config
from wetland_change.indices import mndwi, ndwi
from wetland_change.mask import clear_mask
from wetland_change.raster.read import RasterioReader, read_stack
from wetland_change.stats import rasterise
from wetland_change.verify.wo import WO_EXCLUDE, WO_WET, dea_reader, find_wo_href
from wetland_change.windows import plan_window

THRESHOLDS = np.round(np.arange(-0.30, 0.31, 0.05), 2)
OUT = Path("docs/research/2026-10-29-water-calibration.csv")

cfg = load_config(Path("config/pipeline.toml"))
ramsar = load_ramsar(cfg.aoi.ramsar_path, site_prefixes=cfg.aoi.site_prefixes,
                     operation_epsg=cfg.aoi.operation_epsg)
ramsar_union = unary_union([p.geometry for p in ramsar])
lakes = sorted(
    (p for p in load_waterbodies(cfg.aoi.waterbodies_path, operation_epsg=cfg.aoi.operation_epsg)
     if p.geometry.within(ramsar_union)),
    key=lambda p: p.geometry.area, reverse=True,
)[:4]
print("lakes:", [(p.polygon_id, round(p.geometry.area / 1e4)) for p in lakes])

since = datetime.now(UTC) - timedelta(days=90)
client = pystac_client.Client.open(cfg.stac.endpoint)
items = list(client.search(
    collections=[cfg.stac.collection], bbox=list(union_bbox_4326(lakes)),
    datetime=f"{since:%Y-%m-%d}/{datetime.now(UTC):%Y-%m-%d}",
    query={"eo:cloud_cover": {"lt": cfg.stac.cloud_cover_max}},
).items_as_dicts())
print(len(items), "items")

reader, wo_rd = RasterioReader(), dea_reader()
# key -> [agree, n]; key = (lake, method, threshold)
tally: dict[tuple[str, str, float], list[int]] = defaultdict(lambda: [0, 0])
passes = 0
for item in items:
    scene = parse_item(item, collection=cfg.stac.collection, required_assets=cfg.stac.required_assets)
    grid = reader.open_grid(scene.bands["green"].href)
    wo_href = find_wo_href(scene, union_bbox_4326(lakes))
    if wo_href is None:
        print("no WO for", scene.item_id); continue
    if wo_rd.open_grid(wo_href).transform != grid.transform:
        print("WO grid differs for", scene.item_id); continue
    for lake in lakes:
        planned = plan_window(lake.geometry, grid)
        if planned is None or planned.scene_coverage < 0.99:
            continue
        stack = read_stack(scene, planned, reader)
        inside = rasterise(lake.geometry, stack.transform, stack.shape)
        clear = clear_mask(stack.scl, stack.green, stack.nir, stack.swir16) & inside
        wo = wo_rd.read(wo_href, planned.window10)
        both = clear & ((wo & WO_EXCLUDE) == 0)
        if both.sum() < 100:
            continue
        wo_wet = (wo & WO_WET) > 0
        passes += 1
        nd, mn = ndwi(stack.green, stack.nir), mndwi(stack.green, stack.swir16)
        with np.errstate(invalid="ignore"):
            for t in THRESHOLDS:
                for method, arr in (("ndwi", nd), ("mndwi", mn)):
                    agree = int(((arr > t) == wo_wet)[both].sum())
                    tally[(lake.polygon_id, method, float(t))][0] += agree
                    tally[(lake.polygon_id, method, float(t))][1] += int(both.sum())
        agree = int(((stack.scl == 6) == wo_wet)[both].sum())
        tally[(lake.polygon_id, "scl6", 0.0)][0] += agree
        tally[(lake.polygon_id, "scl6", 0.0)][1] += int(both.sum())
    print(scene.item_id, "done")

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["lake", "method", "threshold", "agreement", "n_pixels"])
    for (lake, method, t), (agree, n) in sorted(tally.items()):
        w.writerow([lake, method, t, f"{agree / n:.4f}", n])
print("lake-scene pairs scored:", passes, "->", OUT)

overall: dict[tuple[str, float], list[int]] = defaultdict(lambda: [0, 0])
for (_, method, t), (agree, n) in tally.items():
    overall[(method, t)][0] += agree; overall[(method, t)][1] += n
print("\nbest by method (pixel-weighted over lakes):")
for method in ("ndwi", "mndwi", "scl6"):
    best = max(((t, a / n) for (m, t), (a, n) in overall.items() if m == method), key=lambda x: x[1])
    print(f"  {method:5} threshold {best[0]:+.2f} agreement {best[1]:.4f}")
```

**Step 2: Run it**

Run: `uv run python scratch/spikes/s2_calibrate.py`
Expected: four lakes listed (Thomsons `dea-qd635epws_v3` and Forrestdale `dea-qd63n1ww5_v3` among them), 20 to 40 items, a CSV with one row per lake, method and threshold, and a best-threshold line per method. Expect MNDWI or a negative NDWI threshold to beat NDWI at 0.0 by a wide margin and SCL class 6 to be close to the best. Runtime 10 to 40 minutes depending on how many WO scenes exist.

**Step 3: Pick the method and write config**

Choose the method and threshold with the highest pixel-weighted agreement, breaking ties towards MNDWI (less sensitive to turbid shallow water). Set in `config/pipeline.toml`:
```toml
[water]
method = "<ndwi|mndwi>"
threshold = <value>
min_valid_fraction = 0.8
```

Then in `tests/test_live_verify.py` remove the `@pytest.mark.xfail(...)` line above `test_water_agrees_with_dea_wo`. If the best agreement is below 0.95, lower `agreement_min` in `wo_check` to the measured value minus 0.02 and record why.

**Step 4: Record the result**

Append to `LEARNINGS.md`:
```markdown
### S2 water calibration (2026-10-29)

<N> lake-scene pairs, <lakes>. Pixel-weighted agreement with DEA S2 WO:
NDWI best threshold <t> at <a>; MNDWI best threshold <t> at <a>; SCL
class 6 at <a>. Chosen: <method> at <t>. Per-lake table in
docs/research/2026-10-29-water-calibration.csv. The uncalibrated NDWI > 0
scored <a> on Thomsons (the 2026-10-27 pre-start number was 0.80).
```

**Step 5: Re-run the live verification test**

Run: `uv run pytest -q -m live tests/test_live_verify.py::test_water_agrees_with_dea_wo`
Expected: `1 passed`.

---

## Task 25: Spike S3, largest Peel-Yalgorup polygon time and memory

**Files:**
- Create: `scratch/spikes/s3_largest.py`
- Modify: `LEARNINGS.md`

**Step 1: Write the script**

`scratch/spikes/s3_largest.py`:
```python
"""Spike S3: read and summarise the largest Ramsar polygon; time and RSS."""

from __future__ import annotations

import resource
import time
from pathlib import Path

import pystac_client

from wetland_change.aoi import load_ramsar
from wetland_change.catalogue.item import parse_item
from wetland_change.config import load_config
from wetland_change.raster.read import RasterioReader, read_stack
from wetland_change.stats import summarise
from wetland_change.windows import plan_window

cfg = load_config(Path("config/pipeline.toml"))
polys = load_ramsar(cfg.aoi.ramsar_path, site_prefixes=["Peel-Yalgorup"],
                    operation_epsg=cfg.aoi.operation_epsg)
big = max(polys, key=lambda p: p.geometry.area)
minx, miny, maxx, maxy = big.geometry.bounds
print(f"{big.polygon_id} {big.geometry.area / 1e4:.0f} ha, extent "
      f"{(maxx - minx) / 1000:.1f} x {(maxy - miny) / 1000:.1f} km")

client = pystac_client.Client.open(cfg.stac.endpoint)
items = list(client.search(
    collections=[cfg.stac.collection], intersects=big.geometry_4326,
    datetime="2026-08-01/2026-10-29", query={"eo:cloud_cover": {"lt": 10}},
    sortby=[{"field": "properties.datetime", "direction": "desc"}], max_items=6,
).items_as_dicts())
reader = RasterioReader()
rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
for item in items:
    scene = parse_item(item, collection=cfg.stac.collection, required_assets=cfg.stac.required_assets)
    grid = reader.open_grid(scene.bands["green"].href)
    planned = plan_window(big.geometry, grid)
    if planned is None:
        continue
    t0 = time.perf_counter()
    stack = read_stack(scene, planned, reader)
    t_read = time.perf_counter() - t0
    t0 = time.perf_counter()
    row = summarise(big, scene, stack, planned, water=cfg.water, run_id="spike")
    t_sum = time.perf_counter() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"{scene.item_id} {scene.tile} window {planned.shape10} coverage "
          f"{planned.scene_coverage:.3f} read {t_read:.1f}s summarise {t_sum:.1f}s "
          f"valid {row.valid_fraction:.2f} water_scl {row.water_ha_scl:.0f} ha "
          f"peak RSS {rss / 2**20:.0f} MiB (start {rss0 / 2**20:.0f} MiB)")
```

On macOS `ru_maxrss` is in bytes; on Linux it is kilobytes. The GitHub runner check in Milestone 2 reads it as kilobytes.

**Step 2: Run it**

Run: `uv run python scratch/spikes/s3_largest.py`
Expected: the Peel-Yalgorup main polygon (tens of thousands of hectares, roughly 10 by 43 km), two to four items across tiles 50HLJ and 50HMJ, each read under 60 s and peak RSS under 1024 MiB. If RSS exceeds 1 GiB, note it: the Milestone 2 fix is chunking `read_stack` by row blocks, not a design change.

**Step 3: Record the result**

Append to `LEARNINGS.md`:
```markdown
### S3 largest polygon (2026-10-29)

<polygon id>, <ha>, window <rows> x <cols> px on <tile>. Read <s> s,
summarise <s> s, peak RSS <MiB>. Under the 1 GiB runner budget: <yes/no>.
```

---

## Task 26: Spike S4, backfill count against Copernicus Data Space

Sizes the Milestone 2 backfill and checks the c1 collection for gaps.

**Files:**
- Create: `scratch/spikes/s4_backfill_count.py`
- Create: `docs/research/2026-10-29-backfill-count.csv` (script output)
- Modify: `LEARNINGS.md`

**Step 1: Write the script**

`scratch/spikes/s4_backfill_count.py`:
```python
"""Spike S4: items since 2022-01-01 over the AOI, Earth Search c1 vs CDSE."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pystac_client

from wetland_change.aoi import load_ramsar, union_bbox_4326
from wetland_change.config import load_config

CDSE = "https://stac.dataspace.copernicus.eu/v1"
OUT = Path("docs/research/2026-10-29-backfill-count.csv")
START, END = "2022-01-01", "2026-10-29"

cfg = load_config(Path("config/pipeline.toml"))
bbox = list(union_bbox_4326(load_ramsar(
    cfg.aoi.ramsar_path, site_prefixes=cfg.aoi.site_prefixes, operation_epsg=cfg.aoi.operation_epsg
)))
print("bbox", [round(b, 3) for b in bbox])

es = pystac_client.Client.open(cfg.stac.endpoint)
es_items = list(es.search(
    collections=[cfg.stac.collection], bbox=bbox, datetime=f"{START}/{END}",
    query={"eo:cloud_cover": {"lt": cfg.stac.cloud_cover_max}},
).items_as_dicts())
es_count = Counter(
    (i["properties"]["grid:code"][-5:], i["properties"]["datetime"][:7]) for i in es_items
)
print("Earth Search c1 items under cloud limit:", len(es_items))

cd = pystac_client.Client.open(CDSE)
cd_items = [
    i for i in cd.search(
        collections=["sentinel-2-l2a"], bbox=bbox, datetime=f"{START}/{END}"
    ).items_as_dicts()
    if float(i["properties"].get("eo:cloud_cover", 101)) < cfg.stac.cloud_cover_max
]
cd_count = Counter(
    (i["properties"].get("grid:code", "?")[-5:], i["properties"]["datetime"][:7]) for i in cd_items
)
print("CDSE sentinel-2-l2a items under cloud limit:", len(cd_items))

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["tile", "month", "earth_search_c1", "cdse"])
    for key in sorted(es_count.keys() | cd_count.keys()):
        w.writerow([*key, es_count.get(key, 0), cd_count.get(key, 0)])
gaps = [(k, es_count.get(k, 0), cd_count.get(k, 0)) for k in cd_count if es_count.get(k, 0) < cd_count[k]]
print("tile-months where c1 has fewer items than CDSE:", len(gaps))
for k, a, b in sorted(gaps)[:20]:
    print("  ", k, a, b)
print("->", OUT)
```

**Step 2: Run it**

Run: `uv run python scratch/spikes/s4_backfill_count.py`
Expected: an Earth Search count in the low thousands (six tiles, five-day revisit, about five years, cloud under 20), a CDSE count of the same order, and a short list of tile-months that differ. CDSE lists reprocessed duplicates for some 2022 to 2023 products, so CDSE higher by a few per cent is not a gap; a tile-month with zero c1 items and several CDSE items is. Runtime 5 to 15 minutes of paging.

If `grid:code` is absent on CDSE items, key them on the tile token in `id` (`T50HLK` and so on) instead.

**Step 3: Record the result**

Append to `LEARNINGS.md`:
```markdown
### S4 backfill count (2026-10-29)

Earth Search c1 under 20 % cloud since 2022-01-01: <n> items over <k>
tiles. CDSE: <n>. Tile-months with fewer c1 than CDSE: <n>, largest gap
<tile month a b>. At <s> s per scene (S3) the backfill takes about <h> h
of runner time. Table in docs/research/2026-10-29-backfill-count.csv.
```

---

## Task 27: Spike S8, toolchain isolation

Confirms the rasterio and pyproj wheels do not pick up the MacPorts GDAL or PROJ data on this machine, and records the versions the fixture was generated with.

**Files:**
- Create: `scratch/spikes/s8_toolchain.sh`
- Modify: `LEARNINGS.md`

**Step 1: Write the script**

`scratch/spikes/s8_toolchain.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
echo "PATH gdal: $(command -v gdalinfo || echo none)"
echo "env PROJ_LIB=${PROJ_LIB:-unset} GDAL_DATA=${GDAL_DATA:-unset} PROJ_DATA=${PROJ_DATA:-unset}"
run() {
  uv run python - <<'PY'
import os
import pyproj
import rasterio
from rasterio.crs import CRS
print("rasterio", rasterio.__version__, "GDAL", rasterio.__gdal_version__)
print("pyproj", pyproj.__version__, "PROJ", pyproj.proj_version_str, "data", pyproj.datadir.get_data_dir())
with rasterio.open("tests/fixtures/thomsons_20261027/B03.tif") as src:
    print("fixture crs", src.crs.to_epsg(), "res", src.res)
print("EPSG:32750 ->", CRS.from_epsg(32750).to_wkt()[:60])
print("PROJ_LIB in process:", os.environ.get("PROJ_LIB", "unset"))
PY
}
echo "--- as-is"; run
echo "--- PROJ_LIB and GDAL_DATA unset"; env -u PROJ_LIB -u GDAL_DATA -u PROJ_DATA bash -c "$(declare -f run); run"
echo "--- PROJ_LIB pointed at MacPorts (should be ignored or harmless)"
PROJ_LIB=/opt/local/share/proj bash -c "$(declare -f run); run"
```

**Step 2: Run it**

Run: `bash scratch/spikes/s8_toolchain.sh`
Expected: the three runs print the same rasterio, GDAL and PROJ versions and the same fixture CRS (32750) and data directory inside the virtualenv. If the MacPorts run reports a different PROJ data directory or a CRS error, the fix is `export PROJ_LIB=` unset in the shell profile; record it in the user's known-fixes note as well as LEARNINGS.md.

**Step 3: Record the result**

Append to `LEARNINGS.md`:
```markdown
### S8 toolchain isolation (2026-10-29)

rasterio <v> (GDAL <v>), pyproj <v> (PROJ <v>), data dir <path>. Unaffected
by PROJ_LIB and GDAL_DATA: <yes/no>. Fixture generated with the same
versions.
```

---

## Task 28: Decision records

Three decisions already taken that a reviewer will ask about. Format: title, status, context, decision, consequences; under 40 lines each.

**Files:**
- Create: `docs/decisions/0001-sentinel-2-collection-1-only.md`, `docs/decisions/0002-three-water-columns.md`, `docs/decisions/0003-fixed-schema-ledger.md`
- Delete: `docs/decisions/.gitkeep`

**Step 1: Write the records**

`docs/decisions/0001-sentinel-2-collection-1-only.md`:
```markdown
# 0001 Read only the Sentinel-2 Collection 1 collection

Status: accepted, 2026-10-29.

## Context

Earth Search serves two Level-2A collections. `sentinel-2-l2a` mixes
items where the BOA offset of -1000 is already applied to the pixels
(flag `earthsearch:boa_offset_applied`) with items where it is not.
`sentinel-2-c1-l2a` is ESA Collection 1 throughout: raw DN, `raster:bands`
scale 0.0001 and offset -0.1 on every reflectance band, and the ESA
product XML available as an asset.

## Decision

The config validator accepts only `sentinel-2-c1-l2a`. The item guard
rejects any item carrying `earthsearch:boa_offset_applied`. Scale and
offset come from `raster:bands` and are checked against
BOA_QUANTIFICATION_VALUE and BOA_ADD_OFFSET in MTD_MSIL2A.xml for every
scene before any pixel is read.

## Consequences

No double-correction path exists. Scenes whose metadata disagree with
the XML fail the scene, not the run. Earth Search v2 renames the
collection; the rename is a one-line config change plus the validator.
```

`docs/decisions/0002-three-water-columns.md`:
```markdown
# 0002 Store three water signals per observation

Status: accepted, 2026-10-29.

## Context

On the 2026-10-27 pass over Thomsons Lake, NDWI > 0 found 5,845 water
pixels, SCL class 6 found 16,676 and DEA Sentinel-2 Water Observations
found 16,444. The textbook threshold is wrong for shallow, vegetated,
seasonal lakes, and the right threshold is an empirical question
(spike S2).

## Decision

Every observation row carries `water_ha_index` (configured index and
threshold), `water_ha_scl` (SCL class 6) and `dea_wo_agreement` (share of
mutually clear pixels where the pipeline and DEA agree, filled by the
verify step while the provisional product retains the pass). The index
medians (`ndwi_median`, `mndwi_median`, `ndvi_median`) are stored so a
different threshold can be evaluated without re-reading pixels.

## Consequences

Rows are wider but the method is auditable per row. Change detection
in Milestone 2 reads `water_ha_index` and reports `water_ha_scl` beside
it; disagreement between the two is itself a quality flag.
```

`docs/decisions/0003-fixed-schema-ledger.md`:
```markdown
# 0003 Ledger is fixed-schema Parquet, not stac-geoparquet

Status: accepted, 2026-10-29. Deviates from the design doc, which named
stac-geoparquet for the ledger.

## Context

stac-geoparquet infers an Arrow schema from each batch of items. Earth
Search items carry optional properties that vary across baselines and
dates, so ledger files written on different days do not union without
schema reconciliation, and a failed or rejected item has no item at all.

## Decision

`ledger/year=YYYY/ledger_<run_id>.parquet` uses one fixed Arrow schema
(`LEDGER_SCHEMA`) with the full source item as a JSON string column.
stac-geoparquet is used in Milestone 2 for the catalogue's
`items.parquet` asset, where every row is a valid item of one collection.

## Consequences

The ledger reads with one `cast`; watermark, seen keys and retries are
plain column operations. The catalogue is rebuildable from the ledger's
`source_item` column alone.
```

**Step 2: Remove the placeholder**

Run: `rm docs/decisions/.gitkeep && ls docs/decisions`
Expected: the three files listed.

---

## Task 29: Live run, verification report and handoff

The end-to-end check the user asked for: one real run writes observations, the ledger and a manifest to `outputs/`, the verify command scores every Milestone 1 oracle on those scenes, and the report lands in `docs/research/`.

**Files:**
- Create: `docs/handoffs/2026-10-29-milestone-1.md`
- Delete: `docs/handoffs/.gitkeep`, `docs/research/.gitkeep`

**Step 1: Fetch the AOI if not yet done**

Run: `test -f data/external/dbca_010_ramsar_sites.geojson || uv run python scripts/fetch_aoi.py`
Expected: both GeoJSON files present under `data/external/` and their rows recorded in `data/SOURCES.md` (Task 4).

**Step 2: Seed the watermark, then dry discovery**

With an empty ledger the watermark is `None` and `discover` lists the whole collection history over the AOI (thousands of lines, minutes of paging). That is correct behaviour and is why Milestone 2 adds a `backfill --since` command; for the first real run, seed the watermark to seven days ago first:

Run: `uv run python - <<'PY'
from datetime import UTC, datetime, timedelta
from wetland_change.ledger import LedgerEntry, write_ledger
from wetland_change.store import OutputStore
now = datetime.now(UTC)
seed = LedgerEntry(item_id="seed", collection=None, datetime=None, created=now - timedelta(days=7), updated=None, tile=None, cloud_cover=None, product_uri=None, status="seed", attempts=0, error=None, run_id="seed", processed_at=now, n_rows=0, observation_path=None, source_item=None)
print(write_ledger([seed], OutputStore("outputs"), run_id="seed"))
PY`
Expected: `['ledger/year=2026/ledger_seed.parquet']`. The seed row has status `seed`, so it is never a seen key, a retry or an exhausted key; it only sets the watermark.

Run: `uv run wetland-change discover`
Expected: one line per scene created in the last eight days (seven plus the overlap day) over the AOI under the cloud limit, under 20 lines, and a summary line. Stop and investigate if the per-tile cadence does not match S4 (one pass per tile every five days before cloud filtering).

**Step 3: Real run**

Run: `uv run wetland-change run`
Expected: the manifest JSON printed, `processed` equal to the discover count, `failed` 0, exit code 0. Files under `outputs/observations/year=2026/tile=*/`, `outputs/ledger/year=2026/`, `outputs/runs/`.

Run: `uv run python -c "import duckdb; print(duckdb.sql(\"SELECT site, tile, count(*) n, round(avg(water_ha_scl),1) ha FROM read_parquet('outputs/observations/*/*/*.parquet', hive_partitioning=true) GROUP BY 1,2 ORDER BY 1,2\"))"`
Expected: one row per site and tile with plausible hectares (Thomsons on the order of 100 to 200 ha of SCL water in late October).

**Step 4: Verify the run**

Run: `uv run wetland-change verify`
Expected: one line per check per scene: `reflectance_scaling` pass, the four `scl_share_*` passes, `pixels_vs_planetary_computer` pass or skip (not yet ingested), `water_vs_dea_s2_wo` pass for polygons with a WO scene. Exit code 0 unless a check reads FAIL; a FAIL here is a real finding, run kit:debugging before touching thresholds. The report is at `outputs/verification/<run_id>.json` and `docs/research/verification-<run_id>.md`.

**Step 5: Rerun to prove idempotence**

Run: `uv run wetland-change run && git status --short outputs docs/research`
Expected: the second manifest shows `discovered` 0 and `skipped_seen` equal to the first run's `processed`; no observation files change. `outputs/` is gitignored, so only the new report under `docs/research/` shows as untracked.

**Step 6: Full gate**

Run: `uv run ruff check src tests scripts && uv run ruff format --check src tests scripts && uv run mypy src scripts && uv run pytest -q && uv run pytest -q -m live`
Expected: every command clean; the offline suite reports all tests passing, the live suite reports its three tests passing (or one skip for Planetary Computer ingestion lag).

**Step 7: Write the handoff**

`docs/handoffs/2026-10-29-milestone-1.md`:
```markdown
# Milestone 1 handoff, 2026-10-29

## State

Pipeline core complete per docs/plans/2026-10-29-swan-wetland-change-milestone-1.md.
First live run <run_id>: <n> scenes, <n> observation rows, 0 failed.
Verification report docs/research/verification-<run_id>.md: <n> checks,
<n> passed, <n> skipped, 0 failed.

## Spike results

See LEARNINGS.md. Water method: <method> at <threshold> (S2). Largest
polygon <s> s and <MiB> (S3). Backfill <n> items, about <h> h (S4).

## Deviations from the design

- Ledger is fixed-schema Parquet (docs/decisions/0003).
- <anything else>

## Open for Jarrod

- AWS account and bucket name for Milestone 2 (S3 plus OIDC).
- Codename registry and inventory rows for the project.
- DBCA-010 licence text in data/SOURCES.md.

## Next

Milestone 2 plan: change detection and backfill, pystac catalogue,
S3 and OIDC, cron and verify workflows, remaining matrix rows, README.
```

Then: `rm docs/handoffs/.gitkeep docs/research/.gitkeep`.

**Step 8: Close out**

Run `kit:verify` on the full gate above, then `kit:finish-branch`. Commits are Jarrod's call per the plan conventions; if `kit:verify` passes and the commit-or-escalate directive applies, commit with subject `feat: milestone 1 wetland change pipeline`.
