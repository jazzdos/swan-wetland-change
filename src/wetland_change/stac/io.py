"""StacIO that reads catalogue hrefs back out of the output store.

Written hrefs are absolute https URLs of a bucket that may not exist yet, so
pystac could not otherwise re-read the catalogue it wrote.
"""

from __future__ import annotations

from typing import Any

import pystac.stac_io

from wetland_change.store import OutputStore


class StoreStacIO(pystac.stac_io.DefaultStacIO):
    def __init__(self, store: OutputStore, base_url: str) -> None:
        super().__init__()
        self._store = store
        self._base_url = base_url.rstrip("/")

    def read_text(self, source: Any, *args: Any, **kwargs: Any) -> str:
        text = str(source)
        prefix = f"{self._base_url}/"
        if text.startswith(prefix):
            return self._store.read_bytes(text[len(prefix) :]).decode()
        result: str = super().read_text(source, *args, **kwargs)
        return result
