"""Live check that the output bucket is private: anonymous reads are denied and a
credentialed DuckDB reader can glob observations/.

Run with: uv run pytest -q -m live tests/test_live_private_outputs.py
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import duckdb
import pytest

from tests.aws_support import create_credential_chain_secret, credential_source
from wetland_change.config import load_config
from wetland_change.stac.catalogue import WRITE_INDEX_KEY

pytestmark = pytest.mark.live

CONFIG = Path(__file__).resolve().parents[1] / "config" / "pipeline.toml"
BUCKET_HOST = re.compile(
    r"(?P<bucket>[^.]+(?:\.[^.]+)*)\.s3\.(?P<region>[a-z0-9-]+)\.amazonaws\.com"
)
OBSERVATIONS_GLOB = "observations/*/*/*.parquet"


def _bucket_and_region() -> tuple[str, str, str]:
    host = urlparse(load_config(CONFIG).catalogue.base_url).hostname or ""
    if host.endswith(".invalid"):
        pytest.skip(
            "catalogue.base_url is the committed placeholder; no bucket is applied"
        )
    match = BUCKET_HOST.fullmatch(host)
    assert match, f"cannot parse bucket and region from {host!r}"
    return host, match["bucket"], match["region"]


def _anonymous_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return int(response.status)
    except urllib.error.HTTPError as err:
        return err.code


def _aws_credentials_discoverable() -> bool:
    return credential_source() is not None


def _existing_key(bucket: str, region: str) -> str:
    """A key that exists in the bucket, so the anonymous GET probes a real object.

    S3 answers 403 for a missing key to any caller without s3:ListBucket, so a
    missing key cannot distinguish a private bucket from a public-GetObject one.
    With credentials, take the first key the credentialed glob returns; without
    them, fall back to the catalogue write index the pipeline writes.
    """
    if not _aws_credentials_discoverable():
        return WRITE_INDEX_KEY
    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("INSTALL aws")
    con.execute("LOAD aws")
    create_credential_chain_secret(con, "key_probe", region)
    row = con.execute(
        f"SELECT file FROM glob('s3://{bucket}/{OBSERVATIONS_GLOB}') LIMIT 1"
    ).fetchone()
    if row is None:
        return WRITE_INDEX_KEY
    return str(row[0]).removeprefix(f"s3://{bucket}/")


def test_anonymous_reader_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    host, bucket, region = _bucket_and_region()
    existing_key = _existing_key(bucket, region)
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)

    # Anonymous GET of an object that exists: 403 on a private bucket, 200 if a
    # public GetObject grant is reintroduced. A missing key would answer 403 either
    # way (no s3:ListBucket), so it cannot detect that leak. The listing and glob
    # checks below catch only a public s3:ListBucket.
    existing_object = f"https://{host}/{existing_key}"
    listing = f"https://{host}/?list-type=2&prefix=observations/"
    assert _anonymous_status(existing_object) == 403
    assert _anonymous_status(listing) == 403

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute(
        "CREATE OR REPLACE SECRET anonymous_probe "
        f"(TYPE s3, PROVIDER config, REGION '{region}')"
    )
    with pytest.raises(duckdb.Error):
        con.execute(
            "SELECT count(*) FROM read_parquet("
            f"'s3://{bucket}/{OBSERVATIONS_GLOB}', hive_partitioning=true)"
        ).fetchall()
    with pytest.raises(duckdb.Error):
        con.execute(f"SELECT * FROM glob('s3://{bucket}/ledger/*')").fetchall()


def test_credentialed_reader_globs_observations() -> None:
    _, bucket, region = _bucket_and_region()
    if not _aws_credentials_discoverable():
        pytest.skip(
            "no AWS credentials discoverable (AWS_ACCESS_KEY_ID, AWS_PROFILE, "
            "AWS_WEB_IDENTITY_TOKEN_FILE or ~/.aws/credentials)"
        )

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("INSTALL aws")
    con.execute("LOAD aws")
    create_credential_chain_secret(con, "outputs_s3", region)
    row_count = con.execute(
        "SELECT count(*) FROM read_parquet("
        f"'s3://{bucket}/{OBSERVATIONS_GLOB}', hive_partitioning=true)"
    ).fetchone()
    assert row_count is not None
    assert row_count[0] > 0

    file_count = con.execute(
        f"SELECT count(*) FROM glob('s3://{bucket}/{OBSERVATIONS_GLOB}')"
    ).fetchone()
    assert file_count is not None
    assert file_count[0] > 0
