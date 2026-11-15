"""Live check that a credentialed DuckDB reader can glob observations/.

Moved unchanged from tests/test_live_private_outputs.py by st-1a5f. Until the
operator's apply of ADR 0016 (docs/decisions/0016-public-read-output-bucket.md)
the bucket is private and credentials are the only way to read it; after the
apply this still checks the pipeline and operator route.

Run with: uv run pytest -q -m live tests/test_live_credentialed_read.py
"""

from __future__ import annotations

import duckdb
import pytest

from tests.aws_support import (
    configured_bucket,
    create_credential_chain_secret,
    credential_source,
)

pytestmark = pytest.mark.live

OBSERVATIONS_GLOB = "observations/*/*/*.parquet"


def test_credentialed_reader_globs_observations() -> None:
    _, bucket, region = configured_bucket()
    if credential_source() is None:
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
