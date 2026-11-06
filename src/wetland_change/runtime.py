"""Record the environment a result was produced in.

Library versions, the uv.lock hash and the git commit are stored with each
manifest and verification report so a result can be tied to the software that
made it.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path

import geopandas
import numpy
import pyarrow
import pyproj
import rasterio

_GIT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Environment:
    runtime: dict[str, str]
    uv_lock_sha256: str | None
    git_commit: str | None


def _git_commit(root: Path) -> str | None:
    # Only ask git when root is itself a checkout (.git is a directory, or a
    # file in a worktree). Otherwise a non-editable install inside some other
    # repository would report that repository's commit.
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = result.stdout.strip()
    if result.returncode != 0 or not commit:
        return None
    return commit


def capture_environment(root: Path | None = None) -> Environment:
    """Return library versions, the uv.lock hash and the git commit of root."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    runtime = {
        "python": platform.python_version(),
        "gdal": rasterio.__gdal_version__,
        # The PROJ that pyproj is built against, which geopandas uses to reproject.
        "proj": pyproj.proj_version_str,
        "geopandas": geopandas.__version__,
        "rasterio": rasterio.__version__,
        "pyarrow": pyarrow.__version__,
        "numpy": numpy.__version__,
    }
    lock = base / "uv.lock"
    lock_sha256 = (
        hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None
    )
    return Environment(
        runtime=runtime, uv_lock_sha256=lock_sha256, git_commit=_git_commit(base)
    )
