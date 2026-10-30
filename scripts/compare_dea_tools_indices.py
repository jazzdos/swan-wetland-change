"""One-off check of wetland_change.indices against dea-tools 0.4.10.

Compares ndwi, mndwi and ndvi with `dea_tools.bandindices.calculate_indices`
(collection 'ga_s2_3') on a synthetic case and on the Thomsons fixture window.
dea-tools is not a project dependency and must not become one. The wheel is
downloaded once into scratch/dea-tools-0.4.10/ (gitignored), its sha256 is
checked on every run, and only `dea_tools/bandindices.py` is read from the zip
and executed as a standalone module. The dea_tools package is never imported
or installed. xarray is supplied by the run command as an overlay and imported
dynamically, so mypy and the lock file need no change.

Source facts checked in dea_tools/bandindices.py 0.4.10 (the run prints them):
    calculate_indices(ds, index, collection, custom_varname, normalise, drop,
    inplace, verbose). For 'ga_s2_3', nbart_green=green, nbart_red=red,
    nbart_nir_1=nir and nbart_swir_2=swir1. NDWI=(green-nir)/(green+nir),
    MNDWI=(green-swir1)/(green+swir1), NDVI=(nir-red)/(nir+red).
    normalise=True divides every band by 10000; normalise=False leaves values
    as given. drop=True removes the input bands and keeps only the indices.
    No NaN handling is applied: x / 0 gives +-inf and 0 / 0 gives NaN.
Sentinel-2 B11 (swir16, 20 m) is the band DEA names nbart_swir_2. These match
the expected mapping; nothing differed.

Run:
    uv run --with xarray python scripts/compare_dea_tools_indices.py
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import types
import warnings
import zipfile
from pathlib import Path
from typing import Any, Final, NamedTuple

import numpy as np
import rasterio
import requests

from wetland_change.indices import mndwi, ndvi, ndwi

WHEEL_NAME: Final = "dea_tools-0.4.10-py3-none-any.whl"
WHEEL_URL: Final = (
    "https://files.pythonhosted.org/packages/cd/d4/"
    "be23d8949a04d49a932e591b74d30d1c43476b2463a923847805a8eb9683/" + WHEEL_NAME
)
WHEEL_SHA256: Final = "8f42620975a8b904446718e561c25d1c39f38c1511359e7730cf3d786890c4ba"
MEMBER: Final = "dea_tools/bandindices.py"
CACHE_DIR: Final = Path("scratch/dea-tools-0.4.10")
FIXTURE: Final = Path("tests/fixtures/thomsons_20261027")
ATOL: Final = 1e-6
INDICES: Final = ("NDWI", "MNDWI", "NDVI")


class Bands(NamedTuple):
    green: np.ndarray
    red: np.ndarray
    nir: np.ndarray
    swir16: np.ndarray


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_wheel() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / WHEEL_NAME
    if not path.exists():
        response = requests.get(WHEEL_URL, timeout=60)
        response.raise_for_status()
        path.write_bytes(response.content)
    actual = sha256_of(path)
    if actual != WHEEL_SHA256:
        raise SystemExit(
            f"sha256 mismatch for {path}: expected {WHEEL_SHA256}, got {actual}"
        )
    return path


def load_bandindices(wheel: Path) -> types.ModuleType:
    """Execute the one member of the hash-verified wheel as a module."""
    with zipfile.ZipFile(wheel) as archive:
        source = archive.read(MEMBER).decode("utf-8")
    module = types.ModuleType("dea_bandindices")
    exec(compile(source, f"{wheel.name}:{MEMBER}", "exec"), module.__dict__)
    return module


def dea_indices(module: types.ModuleType, bands: Bands) -> dict[str, np.ndarray]:
    xarray: Any = importlib.import_module("xarray")
    dims = ("y", "x")
    dataset = xarray.Dataset(
        {
            "nbart_green": (dims, bands.green),
            "nbart_red": (dims, bands.red),
            "nbart_nir_1": (dims, bands.nir),
            "nbart_swir_2": (dims, bands.swir16),
        }
    )
    result = module.calculate_indices(
        dataset,
        index=list(INDICES),
        collection="ga_s2_3",
        normalise=False,
        drop=True,
        verbose=False,
    )
    return {name: np.asarray(result[name].values) for name in INDICES}


def read_fixture_band(item: dict[str, Any], asset: str, filename: str) -> np.ndarray:
    spec = item["assets"][asset]["raster:bands"][0]
    with rasterio.open(FIXTURE / filename) as src:
        dn: np.ndarray = src.read(1)
    scaled: np.ndarray = dn.astype(np.float64) * spec["scale"] + spec["offset"]
    reflectance: np.ndarray = scaled.astype(np.float32)
    reflectance[dn == spec["nodata"]] = np.nan
    return reflectance


def fixture_bands() -> Bands:
    item = json.loads((FIXTURE / "item.json").read_text())
    swir = read_fixture_band(item, "swir16", "B11.tif")
    return Bands(
        green=read_fixture_band(item, "green", "B03.tif"),
        red=read_fixture_band(item, "red", "B04.tif"),
        nir=read_fixture_band(item, "nir", "B08.tif"),
        swir16=np.repeat(np.repeat(swir, 2, axis=0), 2, axis=1),
    )


def synthetic_bands() -> Bands:
    rng = np.random.default_rng(42)
    green, nir, red, swir16 = (rng.uniform(0, 0.6, (32, 32)) for _ in range(4))
    return Bands(green=green, red=red, nir=nir, swir16=swir16)


def compare(
    case: str,
    name: str,
    actual: np.ndarray,
    desired: np.ndarray,
    *,
    check_nan_mask: bool,
) -> bool:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        diff = np.abs(actual.astype(np.float64) - desired.astype(np.float64))
    finite = diff[np.isfinite(diff)]
    max_diff = float(finite.max()) if finite.size else 0.0
    is_pass = True
    try:
        np.testing.assert_allclose(actual, desired, rtol=0, atol=ATOL)
        if check_nan_mask:
            np.testing.assert_array_equal(np.isnan(actual), np.isnan(desired))
    except AssertionError as err:
        is_pass = False
        print("  " + "\n  ".join(str(err).strip().splitlines()[:6]))
    print(
        f"{case:9s} {name:6s} shape={actual.shape} dtype ours={actual.dtype} "
        f"dea={desired.dtype} nan ours={int(np.isnan(actual).sum())} "
        f"nan dea={int(np.isnan(desired).sum())} "
        f"inf dea={int(np.isinf(desired).sum())} "
        f"max_abs_diff={max_diff:.3e} {'PASS' if is_pass else 'FAIL'}"
    )
    return is_pass


def main() -> int:
    wheel = ensure_wheel()
    module = load_bandindices(wheel)
    print(f"wheel {WHEEL_NAME} sha256 {sha256_of(wheel)} (verified)")
    print(f"dea-tools version 0.4.10 (pinned wheel), module {MEMBER}")
    print(
        "mapping ga_s2_3: nbart_green=green nbart_red=red nbart_nir_1=nir "
        "nbart_swir_2=swir1 (B11); normalise=False, drop=True"
    )

    results: list[bool] = []
    for case, bands, check_nan_mask in (
        ("synthetic", synthetic_bands(), False),
        ("fixture", fixture_bands(), True),
    ):
        dea = dea_indices(module, bands)
        ours = {
            "NDWI": ndwi(bands.green, bands.nir),
            "MNDWI": mndwi(bands.green, bands.swir16),
            "NDVI": ndvi(bands.nir, bands.red),
        }
        for name in INDICES:
            results.append(
                compare(
                    case, name, ours[name], dea[name], check_nan_mask=check_nan_mask
                )
            )

    print(f"{sum(results)} of {len(results)} comparisons passed (atol {ATOL}, rtol 0)")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
