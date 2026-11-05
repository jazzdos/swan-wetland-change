"""Output storage behind a pyarrow filesystem.

A plain path becomes a `file://` URI; `s3://bucket/prefix` resolves to
`S3FileSystem` with the same interface, so Milestone 2 changes only config.

Writes carry a Content-Type: by key suffix (`CONTENT_TYPES`) or the caller's
`content_type`. S3 stores it as the object's content type; local files ignore it.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Final

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

    def _full(self, relpath: str) -> str:
        if not relpath:
            return self.root.rstrip("/")
        return f"{self.root.rstrip('/')}/{relpath.lstrip('/')}"

    def write_bytes(
        self, relpath: str, data: bytes, *, content_type: str | None = None
    ) -> str:
        full = self._full(relpath)
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
        self.fs.delete_file(self._full(relpath))
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
