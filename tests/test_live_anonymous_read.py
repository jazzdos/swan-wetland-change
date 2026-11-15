"""Live check that an anonymous reader can read the output bucket after the
operator's apply of ADR 0016 (docs/decisions/0016-public-read-output-bucket.md).

Public read takes effect only when the operator applies infra/. Until then the
bucket is private, every anonymous request is denied and this test is an
expected failure. The xfail marker is removed in the commit that records the
apply (infra/README.md, "Applying public read").

The test reads observation files. Agents do not run it until the st-b6bf and
st-dd0d decision files are committed (LEARNINGS.md); the weekly verify.yml run
executes it with the other live tests.

Run with: uv run pytest -q -m live tests/test_live_anonymous_read.py
"""

from __future__ import annotations

import urllib.error
import urllib.request

import duckdb
import pytest

from tests.aws_support import configured_bucket

pytestmark = pytest.mark.live

# build_catalogue normalises hrefs under <base_url>/stac, so the root catalog is
# this key, and every pipeline run's build-catalogue step has written it.
CATALOG_KEY = "stac/catalog.json"
OBSERVATIONS_GLOB = "observations/*/*/*.parquet"
ORIGIN = "https://example.org"


def _anonymous_get(
    url: str, origin: str | None = None
) -> tuple[int, str | None, bytes]:
    """Status, Access-Control-Allow-Origin and body of an unsigned GET."""
    headers = {"Origin": origin} if origin else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return (
                int(response.status),
                response.headers.get("Access-Control-Allow-Origin"),
                response.read(),
            )
    except urllib.error.HTTPError as err:
        return err.code, err.headers.get("Access-Control-Allow-Origin"), b""


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "public read takes effect at the operator's apply (ADR 0016); remove "
        "this marker in the commit that records the apply"
    ),
)
def test_anonymous_reader_reads_objects_and_globs_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, bucket, region = configured_bucket()
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)
    base = f"https://{host}"

    # An object that exists: 403 while the bucket is private, 200 after the
    # apply, with the CORS header for a browser origin.
    status, allow_origin, _ = _anonymous_get(f"{base}/{CATALOG_KEY}", ORIGIN)
    assert status == 200
    assert allow_origin == "*"

    # Listing under observations/ is allowed and finds a key.
    status, _, body = _anonymous_get(
        f"{base}/?list-type=2&prefix=observations/&max-keys=1"
    )
    assert status == 200
    assert b"<Key>observations/" in body

    # The bucket root, another prefix and the prefix without its slash are not
    # listable.
    for query in (
        "?list-type=2",
        "?list-type=2&prefix=ledger/",
        "?list-type=2&prefix=observations",
    ):
        status, _, _ = _anonymous_get(f"{base}/{query}")
        assert status == 403, query

    # DuckDB with a secret that names only the region reads the observations
    # with one glob, and cannot glob ledger/.
    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute(
        "CREATE OR REPLACE SECRET anonymous_outputs "
        f"(TYPE s3, PROVIDER config, REGION '{region}')"
    )
    row = con.execute(
        "SELECT count(*) FROM read_parquet("
        f"'s3://{bucket}/{OBSERVATIONS_GLOB}', hive_partitioning=true)"
    ).fetchone()
    assert row is not None
    assert row[0] > 0
    with pytest.raises(duckdb.Error):
        con.execute(f"SELECT * FROM glob('s3://{bucket}/ledger/*')").fetchall()
