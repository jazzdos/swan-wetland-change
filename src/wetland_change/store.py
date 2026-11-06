"""Output storage behind a pyarrow filesystem.

A plain path becomes a `file://` URI; `s3://bucket/prefix` resolves to
`S3FileSystem` with the same interface, so Milestone 2 changes only config.

Writes carry a Content-Type: by key suffix (`CONTENT_TYPES`) or the caller's
`content_type`. S3 stores it as the object's content type; local files ignore it.

Only a local root creates parent directories on write. Object stores have no
directories, and `create_dir` on S3 PUTs zero-byte `application/x-directory`
marker keys for the root prefix and every parent.

Deletes on S3 go through a botocore `DeleteObject`. pyarrow's S3 `delete_file`
PUTs the parent directory marker after deleting, which writes avoid, and it has
no batch delete or option to stop that.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

import botocore.session
from botocore.config import Config
from pyarrow import fs as pafs

CONTENT_TYPES: Final[dict[str, str]] = {
    ".json": "application/json",
    ".parquet": "application/vnd.apache.parquet",
}


def _content_type_for(relpath: str) -> str | None:
    return CONTENT_TYPES.get(PurePosixPath(relpath).suffix.lower())


class OutputStore:
    def __init__(self, root: str) -> None:
        if "://" not in root:
            root = Path(root).resolve().as_uri()
        self.uri = root
        self.fs, root_path = pafs.FileSystem.from_uri(root)
        self.root: str = root_path
        # Decided here, before any caller wraps `fs`.
        self._creates_parents: bool = isinstance(self.fs, pafs.LocalFileSystem)
        self._is_s3: bool = isinstance(self.fs, pafs.S3FileSystem)
        query = parse_qs(urlsplit(root).query)
        self._s3_endpoint: str | None = next(
            iter(query.get("endpoint_override", [])), None
        )
        self._s3_scheme: str = next(iter(query.get("scheme", [])), "https")
        self._s3_region: str | None = next(iter(query.get("region", [])), None)
        self._s3: Any = None

    def _s3_client(self) -> Any:
        if self._s3 is None:
            region = self._s3_region or getattr(self.fs, "region", None) or None
            endpoint = self._s3_endpoint
            self._s3 = botocore.session.get_session().create_client(
                "s3",
                region_name=region,
                endpoint_url=f"{self._s3_scheme}://{endpoint}" if endpoint else None,
                config=Config(s3={"addressing_style": "path"}) if endpoint else None,
            )
        return self._s3

    def _full(self, relpath: str) -> str:
        if not relpath:
            return self.root.rstrip("/")
        return f"{self.root.rstrip('/')}/{relpath.lstrip('/')}"

    def write_bytes(
        self, relpath: str, data: bytes, *, content_type: str | None = None
    ) -> str:
        full = self._full(relpath)
        if self._creates_parents:
            # Object stores have no directories; S3 create_dir PUTs x-directory
            # marker keys.
            self.fs.create_dir(full.rsplit("/", 1)[0], recursive=True)
        ctype = content_type or _content_type_for(relpath)
        metadata = {"Content-Type": ctype} if ctype else None
        with self.fs.open_output_stream(full, metadata=metadata) as stream:
            stream.write(data)
        return relpath

    def read_bytes(self, relpath: str) -> bytes:
        with self.fs.open_input_stream(self._full(relpath)) as stream:
            data: bytes = stream.read()
            return data

    def exists(self, relpath: str) -> bool:
        info = self.fs.get_file_info(self._full(relpath))
        return bool(info.type != pafs.FileType.NotFound)

    def delete(self, relpath: str) -> bool:
        """Delete the file if present; returns whether it existed."""
        if not self.exists(relpath):
            return False
        # pyarrow's S3 delete_file PUTs the parent directory marker, so S3
        # deletes use DeleteObject.
        full = self._full(relpath)
        if self._is_s3:
            bucket, key = full.split("/", 1)
            self._s3_client().delete_object(Bucket=bucket, Key=key)
        else:
            self.fs.delete_file(full)
        return True

    def list_files(self, prefix: str) -> list[str]:
        """Relative paths of every file under `prefix`, sorted."""
        selector = pafs.FileSelector(
            self._full(prefix), recursive=True, allow_not_found=True
        )
        base = self.root.rstrip("/") + "/"
        return sorted(
            info.path[len(base) :]
            for info in self.fs.get_file_info(selector)
            if info.type == pafs.FileType.File
        )
