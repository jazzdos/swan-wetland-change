"""Unit tests for the live-test helpers in tests/aws_support.py."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from tests import aws_support
from tests.aws_support import (
    bucket_from_base_url,
    configured_bucket,
    create_credential_chain_secret,
    credential_source,
)
from wetland_change.config import DEFAULT_CATALOGUE_BASE_URL

SENTINEL_KEY = "sentinel-key-id-0001"
SENTINEL_SECRET = "sentinel-secret-0002"
SENTINEL_TOKEN = "sentinel-token-0003"


class _FakeConnection:
    """Records SQL and optionally raises a DuckDB error on execute."""

    def __init__(self, error_text: str | None = None) -> None:
        self.error_text = error_text
        self.statements: list[str] = []

    def execute(self, query: str, /) -> None:
        self.statements.append(query)
        if self.error_text is not None:
            raise duckdb.Error(self.error_text)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def test_credential_source_names_env_keys_profile_and_none(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert credential_source() is None

    (clean_env / ".aws").mkdir()
    (clean_env / ".aws" / "credentials").write_text("")
    source = credential_source()
    assert source is not None
    assert "~/.aws/credentials" in source

    monkeypatch.setenv("AWS_WEB_IDENTITY_TOKEN_FILE", "/some/token")
    source = credential_source()
    assert source is not None
    assert "AWS_WEB_IDENTITY_TOKEN_FILE" in source

    monkeypatch.setenv("AWS_PROFILE", "p")
    source = credential_source()
    assert source is not None
    assert "AWS_PROFILE=p" in source

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", SENTINEL_KEY)
    source = credential_source()
    assert source is not None
    assert "AWS_ACCESS_KEY_ID" in source
    assert "AWS_PROFILE=p" in source
    assert SENTINEL_KEY not in source


def test_credential_source_labels_keys_and_profile_in_order(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", SENTINEL_KEY)
    monkeypatch.setenv("AWS_PROFILE", "p")

    source = credential_source()

    assert source == "AWS_ACCESS_KEY_ID (environment keys); AWS_PROFILE=p"
    assert source.index("AWS_ACCESS_KEY_ID") < source.index("AWS_PROFILE=p")
    assert SENTINEL_KEY not in source


def test_credential_source_labels_every_discoverable_source(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", SENTINEL_KEY)
    monkeypatch.setenv("AWS_PROFILE", "p")
    monkeypatch.setenv("AWS_WEB_IDENTITY_TOKEN_FILE", "/some/token")
    (clean_env / ".aws").mkdir()
    (clean_env / ".aws" / "credentials").write_text("")

    assert credential_source() == (
        "AWS_ACCESS_KEY_ID (environment keys); AWS_PROFILE=p; "
        "AWS_WEB_IDENTITY_TOKEN_FILE; ~/.aws/credentials"
    )


def test_secret_failure_names_keys_and_profile_when_both_set(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", SENTINEL_KEY)
    monkeypatch.setenv("AWS_PROFILE", "p")
    con = _FakeConnection("Secret Validation Failure")

    with pytest.raises(pytest.fail.Exception) as exc:
        create_credential_chain_secret(con, "outputs_s3", "ap-southeast-2")

    message = str(exc.value)
    assert "AWS_ACCESS_KEY_ID" in message
    assert "AWS_PROFILE=p" in message


def test_secret_failure_names_source_and_export_route(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_PROFILE", "p")
    con = _FakeConnection("Secret Validation Failure ... Profile: p")

    with pytest.raises(pytest.fail.Exception) as exc:
        create_credential_chain_secret(con, "outputs_s3", "ap-southeast-2")

    message = str(exc.value)
    assert "AWS_PROFILE=p" in message
    assert "aws configure export-credentials" in message
    assert "--format env" in message
    assert "unset AWS_PROFILE" in message
    assert "aws login" in message


def test_secret_failure_never_prints_credentials(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", SENTINEL_KEY)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SENTINEL_SECRET)
    monkeypatch.setenv("AWS_SESSION_TOKEN", SENTINEL_TOKEN)
    con = _FakeConnection(
        f"Secret Validation Failure key={SENTINEL_KEY} "
        f"secret={SENTINEL_SECRET} token={SENTINEL_TOKEN}"
    )

    with pytest.raises(pytest.fail.Exception) as exc:
        create_credential_chain_secret(con, "outputs_s3", "ap-southeast-2")

    message = str(exc.value)
    for sentinel in (SENTINEL_KEY, SENTINEL_SECRET, SENTINEL_TOKEN):
        assert sentinel not in message
    assert "<redacted>" in message
    # pytest prints chained exceptions in the failure report, so the unredacted
    # DuckDB error must not ride along as the context or cause.
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None or exc.value.__suppress_context__ is True


def test_secret_success_issues_credential_chain_statement(clean_env: Path) -> None:
    con = _FakeConnection()

    create_credential_chain_secret(con, "outputs_s3", "ap-southeast-2")

    assert len(con.statements) == 1
    statement = con.statements[0]
    assert "TYPE s3" in statement
    assert "PROVIDER credential_chain" in statement
    assert "REGION 'ap-southeast-2'" in statement
    assert "outputs_s3" in statement


def test_bucket_from_base_url_parses_a_virtual_hosted_url() -> None:
    assert bucket_from_base_url(
        "https://example-bucket.s3.ap-southeast-2.amazonaws.com"
    ) == (
        "example-bucket.s3.ap-southeast-2.amazonaws.com",
        "example-bucket",
        "ap-southeast-2",
    )


def test_bucket_from_base_url_keeps_dots_in_the_bucket_name() -> None:
    assert bucket_from_base_url("https://a.b.s3.us-east-1.amazonaws.com") == (
        "a.b.s3.us-east-1.amazonaws.com",
        "a.b",
        "us-east-1",
    )


def test_bucket_from_base_url_is_none_for_the_placeholder() -> None:
    assert bucket_from_base_url(DEFAULT_CATALOGUE_BASE_URL) is None


def test_bucket_from_base_url_rejects_another_host() -> None:
    with pytest.raises(ValueError, match="cannot parse"):
        bucket_from_base_url("https://example.org/outputs")


def test_configured_bucket_skips_on_the_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        catalogue=SimpleNamespace(base_url=DEFAULT_CATALOGUE_BASE_URL)
    )
    monkeypatch.setattr(aws_support, "load_config", lambda path: config)
    with pytest.raises(pytest.skip.Exception):
        configured_bucket()
