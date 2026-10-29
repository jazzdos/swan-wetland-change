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
