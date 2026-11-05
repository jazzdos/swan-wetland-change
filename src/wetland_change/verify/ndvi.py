"""Matrix row: NDVI against DEA Sentinel-2 NBART.

The reference is the NDVI median computed from DEA Surface Reflectance NBART
(collections `ga_s2am_ard_3`, `ga_s2bm_ard_3`, `ga_s2cm_ard_3`, DEA STAC
https://explorer.dea.ga.gov.au/stac, unsigned bucket `dea-public-data`) for
the same acquisition as the pipeline scene.

Product facts (probed live 2026-10-30). Items carry
`properties["dea:dataset_maturity"]` in final, interim or nrt (nrt is DEA's
provisional product). `nbart_red` (band04) and `nbart_nir_1` (band08) are
10 m int16 with nodata -999 and EPSG:32750 on the same grid as Earth Search.
Some items lack an item-level `proj:epsg`, so the EPSG is read from the band
assets first.

Scale and offset: 1e-4 and 0. Source: DEA Knowledge Hub product page "DEA
Surface Reflectance NBART (Sentinel-2C MSI)" ("Valid data range [1,10000]";
"For all 'nbart_' bands, Surface Reflectance is scaled between 0 and
10,000"). STAC raster:bands, the ODC product YAML and the COG tags carry no
scale. NDVI is invariant to a pure scale, so only the zero offset matters; an
item whose raster:bands ever states a different scale or offset is refused.

CRS: the DEA item, the DEA raster and the scene must all be the operation
EPSG (32750), and the DEA raster must share the scene's transform, otherwise
the check fails rather than comparing misaligned pixels.

Maturity: final is preferred over interim over nrt when DEA holds several
items for the acquisition.

Mask: the pipeline's SCL clear mask (the same pixels `ndvi_median` was
computed over: SCL classes 4, 5, 6, 7, 11 with finite green, red, nir, swir16,
inside the polygon) minus pixels where either DEA band is -999. DEA fmask is
not used, so a difference measures reflectance processing (Sen2Cor L2A vs
NBART) on identical pixels, not a cloud-mask disagreement.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC
from typing import Any

import numpy as np
import requests

from wetland_change.catalogue.item import SceneItem
from wetland_change.indices import ndvi
from wetland_change.mask import clear_mask
from wetland_change.raster.read import BandStack, RasterReader
from wetland_change.verify.checks import Check
from wetland_change.verify.wo import DEA_STAC
from wetland_change.windows import Grid, PlannedWindow

DEA_ARD_COLLECTIONS: tuple[str, ...] = (
    "ga_s2am_ard_3",
    "ga_s2bm_ard_3",
    "ga_s2cm_ard_3",
)
NBART_RED = "nbart_red"
NBART_NIR = "nbart_nir_1"
NBART_NODATA = -999
NBART_SCALE = 1e-4
NBART_OFFSET = 0.0
MATURITY_PREFERENCE: tuple[str, ...] = ("final", "interim", "nrt")
CHECK_NAME = "ndvi_vs_dea_nbart"
CORRELATION_CHECK_NAME = "ndvi_correlation_vs_dea_nbart"
MEDIAN_TOLERANCE = 0.05
CORRELATION_MIN = 0.95
CORRELATION_MIN_ROWS = 5
MASK_RULE = (
    "SCL clear (4, 5, 6, 7, 11) with finite green, red, nir, swir16 inside the "
    "polygon; DEA nbart_red and nbart_nir_1 not -999"
)
CORRELATION_REFERENCE = (
    "Pearson r of pipeline ndvi_median and DEA NBART NDVI median over the "
    "run's polygon rows"
)
_S3 = "s3://dea-public-data/"
_HTTPS = "https://dea-public-data.s3.ap-southeast-2.amazonaws.com/"


class NbartMetadataError(ValueError):
    """A DEA ARD item the check cannot interpret safely."""


@dataclass(frozen=True)
class NbartItem:
    item_id: str
    collection: str
    maturity: str
    product_name: str
    epsg: int
    red_href: str
    nir_href: str

    @property
    def reference(self) -> str:
        return (
            f"{DEA_STAC} {self.collection} {self.item_id} ({self.maturity}) "
            f"{NBART_RED}, {NBART_NIR}"
        )


def dea_https(href: str) -> str:
    if href.startswith(_S3):
        return _HTTPS + href.removeprefix(_S3)
    return href


def _asset_epsg(asset: dict[str, Any]) -> int | None:
    code = asset.get("proj:code")
    if isinstance(code, str) and code.upper().startswith("EPSG:"):
        return int(code.split(":", 1)[1])
    epsg = asset.get("proj:epsg")
    return int(epsg) if epsg is not None else None


def _check_band_metadata(name: str, asset: dict[str, Any]) -> None:
    bands = asset.get("raster:bands") or [{}]
    band = bands[0]
    if band.get("nodata") != NBART_NODATA:
        raise NbartMetadataError(
            f"{name} nodata is {band.get('nodata')!r}, expected {NBART_NODATA}"
        )
    if "scale" in band and not math.isclose(band["scale"], NBART_SCALE):
        raise NbartMetadataError(f"{name} scale {band['scale']!r} is not 1e-4")
    if "offset" in band and not math.isclose(band["offset"], 0, abs_tol=1e-12):
        raise NbartMetadataError(f"{name} offset {band['offset']!r} is not 0")


def parse_nbart_item(feature: dict[str, Any]) -> NbartItem:
    assets = feature.get("assets", {})
    for name in (NBART_RED, NBART_NIR):
        if name not in assets:
            raise NbartMetadataError(f"item {feature.get('id')} has no {name} asset")
    red, nir = assets[NBART_RED], assets[NBART_NIR]
    _check_band_metadata(NBART_RED, red)
    _check_band_metadata(NBART_NIR, nir)
    props = feature.get("properties", {})
    red_epsg, nir_epsg = _asset_epsg(red), _asset_epsg(nir)
    if red_epsg is None and nir_epsg is None:
        red_epsg = nir_epsg = _asset_epsg(props)
    if red_epsg is None or red_epsg != nir_epsg:
        raise NbartMetadataError(
            f"item {feature.get('id')} EPSG not found or bands disagree "
            f"({red_epsg!r} vs {nir_epsg!r})"
        )
    return NbartItem(
        item_id=str(feature["id"]),
        collection=str(feature.get("collection", "")),
        maturity=str(props.get("dea:dataset_maturity", "unknown")),
        product_name=str(props.get("sentinel:product_name", "")),
        epsg=red_epsg,
        red_href=dea_https(str(red["href"])),
        nir_href=dea_https(str(nir["href"])),
    )


def _acquisition_key(name: str) -> tuple[str, ...] | None:
    tokens = name.removesuffix(".SAFE").split("_")
    if len(tokens) < 6:
        return None
    return (tokens[0], tokens[2], tokens[4], tokens[5])


def same_acquisition(product_uri: str, product_name: str) -> bool:
    """Platform, sensing start, relative orbit and tile all match."""
    a, b = _acquisition_key(product_uri), _acquisition_key(product_name)
    return a is not None and a == b


def _maturity_rank(feature: dict[str, Any]) -> int:
    maturity = feature.get("properties", {}).get("dea:dataset_maturity")
    if maturity in MATURITY_PREFERENCE:
        return MATURITY_PREFERENCE.index(maturity)
    return len(MATURITY_PREFERENCE)


def select_nbart_item(
    scene: SceneItem, features: Iterable[dict[str, Any]]
) -> NbartItem | None:
    matching = [
        f
        for f in features
        if same_acquisition(
            scene.product_uri,
            str(f.get("properties", {}).get("sentinel:product_name", "")),
        )
    ]
    if not matching:
        return None
    return parse_nbart_item(min(matching, key=_maturity_rank))


def find_nbart_item(
    scene: SceneItem, bbox_4326: tuple[float, float, float, float]
) -> NbartItem | None:
    day = scene.datetime.astimezone(UTC).date().isoformat()
    body: dict[str, Any] = {
        "collections": list(DEA_ARD_COLLECTIONS),
        "bbox": list(bbox_4326),
        "datetime": f"{day}T00:00:00Z/{day}T23:59:59Z",
        "limit": 100,
    }
    response = requests.post(f"{DEA_STAC}/search", json=body, timeout=60)
    response.raise_for_status()
    return select_nbart_item(scene, response.json().get("features", []))


def nbart_reflectance(dn: np.ndarray) -> np.ndarray:
    """float32 reflectance from NBART DN; NaN where DN is the nodata value."""
    if not np.issubdtype(dn.dtype, np.integer):
        raise TypeError(f"NBART DN must be integer, got {dn.dtype}")
    reflectance = (dn.astype(np.float64) * NBART_SCALE + NBART_OFFSET).astype(
        np.float32
    )
    reflectance[dn == NBART_NODATA] = np.nan
    return reflectance


def dea_ndvi_median(
    red_dn: np.ndarray, nir_dn: np.ndarray, clear: np.ndarray
) -> tuple[float, int, int]:
    """(median NDVI, pixels compared, clear pixels lost to DEA nodata)."""
    valid = (red_dn != NBART_NODATA) & (nir_dn != NBART_NODATA)
    index = ndvi(nbart_reflectance(nir_dn), nbart_reflectance(red_dn))
    use = clear & valid & np.isfinite(index)
    n_compared = int(use.sum())
    median = float(np.median(index[use])) if n_compared else float("nan")
    return median, n_compared, int((clear & ~valid).sum())


def ndvi_median_check(
    measured_median: float,
    red_dn: np.ndarray,
    nir_dn: np.ndarray,
    clear: np.ndarray,
    *,
    tolerance: float = MEDIAN_TOLERANCE,
    reference: str = DEA_STAC,
    detail: dict[str, Any] | None = None,
    min_pixels: int = 1,
) -> Check:
    dea_median, n_compared, n_nodata = dea_ndvi_median(red_dn, nir_dn, clear)
    abs_diff = abs(measured_median - dea_median)
    info: dict[str, Any] = {
        **(detail or {}),
        "ndvi_median": measured_median,
        "dea_ndvi_median": dea_median,
        "abs_diff": abs_diff,
        "n_compared": n_compared,
        "n_dea_nodata": n_nodata,
        "scale": NBART_SCALE,
        "offset": NBART_OFFSET,
        "mask": MASK_RULE,
    }
    if not math.isfinite(measured_median):
        info["reason"] = "pipeline ndvi_median is not finite"
        return Check(CHECK_NAME, None, None, tolerance, reference, info)
    if n_compared == 0:
        info["reason"] = "no clear pixels with DEA data"
        return Check(CHECK_NAME, None, None, tolerance, reference, info)
    if n_compared < min_pixels:
        info["reason"] = f"fewer than {min_pixels} compared pixels"
        info["min_pixels"] = min_pixels
        return Check(CHECK_NAME, None, None, tolerance, reference, info)
    return Check(
        CHECK_NAME, bool(abs_diff <= tolerance), abs_diff, tolerance, reference, info
    )


def ndvi_correlation_check(
    pipeline: Sequence[float],
    reference: Sequence[float],
    *,
    min_corr: float = CORRELATION_MIN,
    min_rows: int = CORRELATION_MIN_ROWS,
    detail: dict[str, Any] | None = None,
) -> Check:
    a = np.asarray(pipeline, dtype=np.float64)
    b = np.asarray(reference, dtype=np.float64)
    keep = np.isfinite(a) & np.isfinite(b)
    a, b = a[keep], b[keep]
    info: dict[str, Any] = {**(detail or {}), "n_rows": int(a.size)}

    def skipped(reason: str) -> Check:
        info["reason"] = reason
        return Check(
            CORRELATION_CHECK_NAME, None, None, min_corr, CORRELATION_REFERENCE, info
        )

    if a.size < min_rows:
        return skipped(f"fewer than {min_rows} scored rows")
    with np.errstate(invalid="ignore", divide="ignore"):
        r = float(np.corrcoef(a, b)[0, 1])
    if not math.isfinite(r):
        return skipped("correlation undefined (constant values)")
    return Check(
        CORRELATION_CHECK_NAME,
        bool(r > min_corr),
        r,
        min_corr,
        CORRELATION_REFERENCE,
        info,
    )


def ndvi_scene_check(
    scene: SceneItem,
    stack: BandStack,
    planned: PlannedWindow,
    inside: np.ndarray,
    *,
    measured_median: float,
    nbart: NbartItem,
    reader: RasterReader,
    scene_grid: Grid,
    expected_epsg: int,
    min_pixels: int = 1,
) -> Check:
    dea_grid = reader.open_grid(nbart.red_href)
    base: dict[str, Any] = {
        "item": scene.item_id,
        "dea_item": nbart.item_id,
        "dea_collection": nbart.collection,
        "dea_maturity": nbart.maturity,
        "dea_product_name": nbart.product_name,
    }

    def failed(reason: str, extra: dict[str, Any]) -> Check:
        return Check(
            CHECK_NAME,
            False,
            None,
            MEDIAN_TOLERANCE,
            nbart.reference,
            {**base, "reason": reason, **extra},
        )

    if {nbart.epsg, dea_grid.epsg, scene_grid.epsg} != {expected_epsg}:
        return failed(
            "crs differs",
            {
                "expected_epsg": expected_epsg,
                "dea_item_epsg": nbart.epsg,
                "dea_grid_epsg": dea_grid.epsg,
                "scene_grid_epsg": scene_grid.epsg,
            },
        )
    if dea_grid.transform != scene_grid.transform:
        return failed("grid differs", {})
    red = reader.read(nbart.red_href, planned.window10)
    nir = reader.read(nbart.nir_href, planned.window10)
    if red.shape != stack.shape or nir.shape != stack.shape:
        raise ValueError(
            f"DEA window shapes {red.shape}, {nir.shape} differ from {stack.shape}"
        )
    clear = clear_mask(stack.scl, stack.green, stack.red, stack.nir, stack.swir16)
    return ndvi_median_check(
        measured_median,
        red,
        nir,
        clear & inside,
        reference=nbart.reference,
        detail=base,
        min_pixels=min_pixels,
    )
