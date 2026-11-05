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
        key = parts.path.removeprefix("/stub-bucket").strip("/")
        xml = {"Content-Type": "application/xml"}
        if self.command == "HEAD":
            self._reply(200 if not key else 404)
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


def test_s3_write_sends_the_content_type_header(
    stub_s3: _StubS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "stub")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "stub")
    port = stub_s3.server_address[1]
    store = OutputStore(
        f"s3://stub-bucket/prefix?endpoint_override=127.0.0.1:{port}"
        "&scheme=http&region=us-east-1"
    )
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
