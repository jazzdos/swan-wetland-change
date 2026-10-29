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
        (
            RasterioIOError(
                "/vsicurl/https://x/S2B_T50HLK_20250503T022351_L2A_B03.tif: "
                "No such file or directory"
            ),
            False,
        ),
        (RasterioIOError("HTTP response code: 503"), True),
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
