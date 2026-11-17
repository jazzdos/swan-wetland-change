"""Helpers for the live tests that read the output bucket.

`configured_bucket` names the bucket from `catalogue.base_url`, and
`create_credential_chain_secret` builds the DuckDB S3 secret for the
credentialed reads, and `fail_on_expired_credentials` turns a DuckDB
ExpiredToken error from an S3 read into a readable test failure.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import urlparse

import duckdb
import pytest

from wetland_change.config import load_config

EXPORT_COMMAND: Final = (
    'eval "$(aws configure export-credentials --profile <profile> --format env)" '
    "&& unset AWS_PROFILE"
)

EXPIRED_TOKEN_MARKER: Final = "ExpiredToken"

CONFIG: Final = Path(__file__).resolve().parents[1] / "config" / "pipeline.toml"
BUCKET_HOST: Final = re.compile(
    r"(?P<bucket>[^.]+(?:\.[^.]+)*)\.s3\.(?P<region>[a-z0-9-]+)\.amazonaws\.com"
)

_CREDENTIAL_ENV_NAMES: Final = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)


class _SupportsExecute(Protocol):
    def execute(self, query: str, /) -> object: ...


def bucket_from_base_url(base_url: str) -> tuple[str, str, str] | None:
    """Host, bucket and region of a virtual-hosted S3 base URL.

    None for the committed `.invalid` placeholder, which names no bucket.
    """
    host = urlparse(base_url).hostname or ""
    if host.endswith(".invalid"):
        return None
    match = BUCKET_HOST.fullmatch(host)
    if match is None:
        raise ValueError(f"cannot parse bucket and region from {host!r}")
    return host, match["bucket"], match["region"]


def configured_bucket() -> tuple[str, str, str]:
    """The output bucket that catalogue.base_url in config/pipeline.toml names.

    Skips the calling test while base_url is the `.invalid` placeholder.
    """
    parsed = bucket_from_base_url(load_config(CONFIG).catalogue.base_url)
    if parsed is None:
        pytest.skip(
            "catalogue.base_url is the committed placeholder; no bucket is applied"
        )
    return parsed


def credential_source() -> str | None:
    """Label every discoverable AWS credential source, or None if there is none.

    The labels are joined with "; ". The label never contains a credential value.
    Which source DuckDB uses when several are set is not measured here.
    """
    labels: list[str] = []
    if os.environ.get("AWS_ACCESS_KEY_ID"):
        labels.append("AWS_ACCESS_KEY_ID (environment keys)")
    profile = os.environ.get("AWS_PROFILE")
    if profile:
        labels.append(f"AWS_PROFILE={profile}")
    if os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE"):
        labels.append("AWS_WEB_IDENTITY_TOKEN_FILE")
    if (Path.home() / ".aws" / "credentials").exists():
        labels.append("~/.aws/credentials")
    return "; ".join(labels) if labels else None


def _redact(text: str) -> str:
    for name in _CREDENTIAL_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "<redacted>")
    return text


def create_credential_chain_secret(
    con: _SupportsExecute, name: str, region: str
) -> None:
    """Create an s3 credential_chain DuckDB secret, or fail the test readably.

    A DuckDB error becomes a pytest failure that names the credential source and
    the export-credentials route, with any credential value in the error text
    replaced by a placeholder.
    """
    try:
        con.execute(
            f"CREATE OR REPLACE SECRET {name} "
            f"(TYPE s3, PROVIDER credential_chain, REGION '{region}')"
        )
    except duckdb.Error as err:
        source = credential_source() or "no discoverable source"
        message = (
            f"DuckDB could not build an s3 credential_chain secret from {source}. "
            "A profile created by `aws login` (login_session in ~/.aws/config, "
            "key type 'login' in `aws configure list`) is not read by the DuckDB "
            "credential chain although the AWS CLI resolves it. To run this test, "
            f"export the credentials to the environment with: {EXPORT_COMMAND}. "
            f"DuckDB error: {_redact(str(err))}"
        )
    else:
        return
    # Raised outside the except block so pytest does not chain the unredacted
    # DuckDB error as __context__ and print it above the redacted message.
    pytest.fail(message, pytrace=False)


@contextmanager
def fail_on_expired_credentials() -> Iterator[None]:
    """Fail the test readably when an S3 read raises a DuckDB ExpiredToken error.

    Other errors propagate unchanged. Any credential value in the error text is
    replaced by a placeholder.
    """
    try:
        yield
    except duckdb.Error as err:
        if EXPIRED_TOKEN_MARKER not in str(err):
            raise
        message = (
            "The AWS credentials in the environment have expired (DuckDB reported "
            f"{EXPIRED_TOKEN_MARKER}). Credentials exported from an `aws login` "
            "profile expire 15 minutes after they are minted and are not "
            "refreshed once they are environment variables. Export fresh "
            f"credentials and rerun this test on its own: {EXPORT_COMMAND}. "
            "The S3 region hint in the DuckDB error is not the cause when the "
            f"region is correct. DuckDB error: {_redact(str(err))}"
        )
    else:
        return
    # Raised outside the except block, and with the context suppressed: the
    # with statement calls this generator while the body's DuckDB error is
    # still being handled, so Python would otherwise set that unredacted error
    # as __context__ and pytest would print it above the redacted message.
    try:
        pytest.fail(message, pytrace=False)
    except pytest.fail.Exception as failure:
        failure.__suppress_context__ = True
        raise
