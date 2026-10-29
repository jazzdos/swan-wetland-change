"""Bounded retry on transient network errors.

GDAL and rasterio give no structured error type for a flaky S3 read: a 404
and a 503 both surface as a `RasterioIOError` with a free-text message, so
classification is a documented heuristic over message markers plus a
duck-typed `status_code` for HTTP client errors.
"""

from __future__ import annotations

import re
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
)

#: Status codes match only as standalone numbers: scene dates and times in the
#: href that RasterioIOError messages include (20190502, T022429) must not hit.
_HTTP_TRANSIENT_STATUS = re.compile(r"(?<!\d)(429|50[0234])(?!\d)")


def _has_transient_marker(message: str) -> bool:
    lowered = message.lower()
    return any(m in lowered for m in _RASTERIO_TRANSIENT_MARKERS) or bool(
        _HTTP_TRANSIENT_STATUS.search(lowered)
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
        return _has_transient_marker(str(exc))

    if isinstance(exc, WarpOperationError):
        seen: set[int] = {id(exc)}
        link = exc.__cause__
        for _ in range(_MAX_CAUSE_HOPS):
            if link is None or id(link) in seen:
                break
            seen.add(id(link))
            if _has_transient_marker(str(link)):
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
