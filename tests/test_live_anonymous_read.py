"""Live check that an unsigned reader is denied by the output bucket under
ADR 0017 (docs/decisions/0017-private-output-bucket-again.md), applied on
2026-11-17.

This test is no longer an expected failure. The weekly verify.yml run fails
if the bucket becomes anonymously readable again.

It sends unsigned requests, reads status codes only and discards bodies.
Agents do not run it: the weekly verify.yml run does, before it assumes AWS
credentials. Agents do not read observation files (st-b6bf and st-dd0d rules
in LEARNINGS.md).

Run with: uv run pytest -q -m live tests/test_live_anonymous_read.py
"""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from tests.aws_support import configured_bucket

pytestmark = [pytest.mark.live]


def _unsigned_status(url: str) -> int:
    """Return the HTTP status of an unsigned GET, leaving the body unread."""
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url), timeout=30
        ) as response:
            return int(response.status)
    except urllib.error.HTTPError as err:
        with err:
            return err.code


def test_unsigned_get_of_catalogue_root_is_denied() -> None:
    host, _bucket, _region = configured_bucket()
    assert _unsigned_status(f"https://{host}/stac/catalog.json") == 403


def test_unsigned_listing_of_observations_is_denied() -> None:
    host, _bucket, _region = configured_bucket()
    url = f"https://{host}/?list-type=2&prefix=observations/&max-keys=1"
    assert _unsigned_status(url) == 403
