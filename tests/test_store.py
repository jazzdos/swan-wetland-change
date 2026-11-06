import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from wetland_change.store import OutputStore


class _Recorder:
    """Wraps a real filesystem and records the metadata of each output stream."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.metadata: list[dict[str, str] | None] = []

    def open_output_stream(self, path: str, *args: Any, **kwargs: Any) -> Any:
        self.metadata.append(kwargs.get("metadata"))
        return self.inner.open_output_stream(path, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _recorded(tmp_path: Path) -> tuple[OutputStore, _Recorder]:
    store = OutputStore(str(tmp_path / "out"))
    rec = _Recorder(store.fs)
    store.fs = rec  # type: ignore[assignment]
    return store, rec


def test_write_read_exists_list(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "out"))
    assert not store.exists("a/b.txt")
    assert store.write_bytes("a/b.txt", b"hello") == "a/b.txt"
    store.write_bytes("a/c/d.txt", b"x")
    store.write_bytes("z.txt", b"y")
    assert store.exists("a/b.txt")
    assert store.read_bytes("a/b.txt") == b"hello"
    assert store.list_files("a") == ["a/b.txt", "a/c/d.txt"]
    assert store.list_files("") == ["a/b.txt", "a/c/d.txt", "z.txt"]
    assert store.list_files("missing") == []
    assert (tmp_path / "out" / "a" / "b.txt").read_bytes() == b"hello"


def test_accepts_file_uri(tmp_path: Path) -> None:
    store = OutputStore((tmp_path / "out").as_uri())
    store.write_bytes("k.txt", b"v")
    assert (tmp_path / "out" / "k.txt").exists()
    assert store.uri.startswith("file://")


def test_write_bytes_sets_json_content_type(tmp_path: Path) -> None:
    store, rec = _recorded(tmp_path)
    store.write_bytes("runs/r.json", b"{}")
    assert rec.metadata == [{"Content-Type": "application/json"}]


def test_write_bytes_sets_parquet_content_type(tmp_path: Path) -> None:
    store, rec = _recorded(tmp_path)
    store.write_bytes("observations/year=2025/x.parquet", b"PAR1")
    assert rec.metadata == [{"Content-Type": "application/vnd.apache.parquet"}]


def test_write_bytes_matches_suffix_case_insensitively(tmp_path: Path) -> None:
    store, rec = _recorded(tmp_path)
    store.write_bytes("a/B.JSON", b"{}")
    assert rec.metadata == [{"Content-Type": "application/json"}]


def test_write_bytes_leaves_unknown_types_unset(tmp_path: Path) -> None:
    store, rec = _recorded(tmp_path)
    store.write_bytes("z.txt", b"y")
    assert rec.metadata == [None]


def test_write_bytes_content_type_argument_overrides_the_suffix(
    tmp_path: Path,
) -> None:
    store, rec = _recorded(tmp_path)
    store.write_bytes("i.json", b"{}", content_type="application/geo+json")
    assert rec.metadata == [{"Content-Type": "application/geo+json"}]


class _StubS3(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _StubS3Handler)
        self.requests: list[tuple[str, str, str | None]] = []
        self.calls: list[tuple[str, str]] = []
        self.keys: set[str] = set()


class _StubS3Handler(BaseHTTPRequestHandler):
    server: _StubS3

    def _reply(
        self, status: int, body: bytes = b"", headers: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.server.requests.append(
            (self.command, self.path, self.headers.get("Content-Type"))
        )
        parts = urlsplit(self.path)
        self.server.calls.append(
            (self.command, parts.path.removeprefix("/stub-bucket"))
        )
        key = parts.path.removeprefix("/stub-bucket").strip("/")
        xml = {"Content-Type": "application/xml"}
        if self.command == "HEAD":
            self._reply(200 if not key or key in self.server.keys else 404)
        elif self.command == "DELETE":
            self.server.keys.discard(key)
            self._reply(204)
        elif self.command == "GET":
            self._reply(
                200,
                b'<?xml version="1.0" encoding="UTF-8"?>'
                b"<ListBucketResult><Name>stub-bucket</Name>"
                b"<IsTruncated>false</IsTruncated></ListBucketResult>",
                xml,
            )
        elif self.command == "PUT":
            self._reply(200, headers={"ETag": '"stub"'})
        elif self.command == "POST" and parts.query.startswith("uploads"):
            self._reply(
                200,
                b'<?xml version="1.0" encoding="UTF-8"?>'
                b"<InitiateMultipartUploadResult><Bucket>stub-bucket</Bucket>"
                b"<Key>k</Key><UploadId>u1</UploadId>"
                b"</InitiateMultipartUploadResult>",
                xml,
            )
        elif self.command == "POST":
            self._reply(
                200,
                b'<?xml version="1.0" encoding="UTF-8"?>'
                b"<CompleteMultipartUploadResult><Bucket>stub-bucket</Bucket>"
                b'<Key>k</Key><ETag>"stub"</ETag>'
                b"</CompleteMultipartUploadResult>",
                xml,
            )
        else:
            self._reply(200)

    do_GET = do_HEAD = do_PUT = do_POST = do_DELETE = _handle

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def stub_s3() -> Iterator[_StubS3]:
    server = _StubS3()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _s3_store(
    stub_s3: _StubS3, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> OutputStore:
    """An S3 store aimed at the stub, with botocore and pyarrow kept off real AWS."""
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "stub")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "stub")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv(
        "AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials")
    )
    port = stub_s3.server_address[1]
    return OutputStore(
        f"s3://stub-bucket/prefix?endpoint_override=127.0.0.1:{port}"
        "&scheme=http&region=us-east-1"
    )


def test_s3_write_sends_the_content_type_header(
    stub_s3: _StubS3, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _s3_store(stub_s3, monkeypatch, tmp_path)
    expected = {
        "runs/r.json": "application/json",
        "observations/x.parquet": "application/vnd.apache.parquet",
    }
    for relpath in expected:
        store.write_bytes(relpath, b"{}")
    for relpath, content_type in expected.items():
        creating = [
            ctype
            for method, path, ctype in stub_s3.requests
            if f"/prefix/{relpath}" in path
            and "partNumber" not in path
            and (method == "PUT" or (method == "POST" and "uploads" in path))
        ]
        assert creating == [content_type], stub_s3.requests


def test_s3_write_creates_no_directory_marker_keys(
    stub_s3: _StubS3, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _s3_store(stub_s3, monkeypatch, tmp_path)
    store.write_bytes("runs/a/r.json", b"{}")
    store.write_bytes("z.json", b"{}")
    for relpath in ("runs/a/r.json", "z.json"):
        assert any(
            method == "POST" and f"/prefix/{relpath}" in path and "uploads" in path
            for method, path, _ in stub_s3.requests
        ), stub_s3.requests
    markers = [
        (method, key)
        for method, key in stub_s3.calls
        if method in ("PUT", "POST") and key.endswith("/")
    ]
    assert markers == [], stub_s3.calls


def _no_directory_creation(stub_s3: _StubS3) -> list[tuple[str, str]]:
    return [
        (method, key)
        for method, key in stub_s3.calls
        if method not in ("GET", "HEAD") and key.endswith("/")
    ]


def test_s3_delete_sends_only_delete_for_a_nested_key(
    stub_s3: _StubS3, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _s3_store(stub_s3, monkeypatch, tmp_path)
    stub_s3.keys.add("prefix/runs/a/r.json")
    assert store.delete("runs/a/r.json") is True
    assert ("DELETE", "/prefix/runs/a/r.json") in stub_s3.calls
    assert [c for c in stub_s3.calls if c[0] in ("PUT", "POST")] == []
    assert _no_directory_creation(stub_s3) == []
    assert "prefix/runs/a/r.json" not in stub_s3.keys


def test_s3_delete_of_a_missing_key_returns_false_without_deleting(
    stub_s3: _StubS3, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _s3_store(stub_s3, monkeypatch, tmp_path)
    assert store.delete("nope.json") is False
    assert [c for c in stub_s3.calls if c[0] == "DELETE"] == []


def test_s3_delete_sends_only_delete_for_a_top_level_key(
    stub_s3: _StubS3, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _s3_store(stub_s3, monkeypatch, tmp_path)
    stub_s3.keys.add("prefix/z.json")
    assert store.delete("z.json") is True
    assert ("DELETE", "/prefix/z.json") in stub_s3.calls
    assert [c for c in stub_s3.calls if c[0] in ("PUT", "POST")] == []


def test_s3_delete_client_targets_the_stub_endpoint(
    stub_s3: _StubS3, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _s3_store(stub_s3, monkeypatch, tmp_path)
    stub_s3.keys.add("prefix/z.json")
    store.delete("z.json")
    port = stub_s3.server_address[1]
    assert store._s3 is not None
    assert store._s3.meta.endpoint_url == f"http://127.0.0.1:{port}"


def test_local_delete_removes_files_and_reports_presence(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    store.write_bytes("a/b.txt", b"x")
    assert store.delete("a/b.txt") is True
    assert not (tmp_path / "a" / "b.txt").exists()
    assert store.delete("a/b.txt") is False
    assert store.delete("never/existed.txt") is False


def test_local_delete_builds_no_s3_client(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path))
    store.write_bytes("a/b.txt", b"x")
    store.delete("a/b.txt")
    assert store._s3 is None


def test_local_write_creates_missing_parent_directories(tmp_path: Path) -> None:
    store = OutputStore(str(tmp_path / "out"))
    store.write_bytes("a/b/c/d.txt", b"x")
    assert (tmp_path / "out" / "a" / "b" / "c" / "d.txt").read_bytes() == b"x"
    assert (tmp_path / "out" / "a" / "b" / "c").is_dir()
    store.write_bytes("a/b/c/e.txt", b"y")
    assert (tmp_path / "out" / "a" / "b" / "c" / "e.txt").read_bytes() == b"y"
