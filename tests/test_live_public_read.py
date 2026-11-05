"""Live check that an anonymous DuckDB reader can glob the public bucket.

Run with: uv run pytest -q -m live tests/test_live_public_read.py
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import duckdb
import pytest

from wetland_change.config import load_config

pytestmark = pytest.mark.live

CONFIG = Path(__file__).resolve().parents[1] / "config" / "pipeline.toml"
BUCKET_HOST = re.compile(
    r"(?P<bucket>[^.]+(?:\.[^.]+)*)\.s3\.(?P<region>[a-z0-9-]+)\.amazonaws\.com"
)


def test_anonymous_reader_globs_observations_but_not_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = urlparse(load_config(CONFIG).catalogue.base_url).hostname or ""
    if host.endswith(".invalid"):
        pytest.skip(
            "catalogue.base_url is the committed placeholder; no bucket is applied"
        )
    match = BUCKET_HOST.fullmatch(host)
    assert match, f"cannot parse bucket and region from {host!r}"
    bucket, region = match["bucket"], match["region"]

    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute(
        "CREATE OR REPLACE SECRET public_outputs "
        f"(TYPE s3, PROVIDER config, REGION '{region}')"
    )
    row = con.execute(
        "SELECT count(*) FROM read_parquet("
        f"'s3://{bucket}/observations/*/*/*.parquet', hive_partitioning=true)"
    ).fetchone()
    assert row is not None
    assert row[0] > 0

    with pytest.raises(duckdb.Error):
        con.execute(f"SELECT * FROM glob('s3://{bucket}/ledger/*')").fetchall()
