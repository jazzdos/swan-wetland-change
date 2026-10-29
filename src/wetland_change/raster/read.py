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


def read_stack(
    scene: SceneItem, planned: PlannedWindow, reader: RasterReader
) -> BandStack:
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
