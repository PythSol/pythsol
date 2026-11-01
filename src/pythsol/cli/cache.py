"""Content-addressed cache for the SBF ``.so``.

The key is the generated C, the compiler version, the clang version, the
runtime header, and a flavor tag. A hit copies the ``.so`` and skips clang.
The C text is part of the key so an emitter change is a miss even when the
package version stays ``0.1.0``.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from pythsol import __version__

__all__ = ["artifact_key", "cache_directory", "lookup_so", "store_so"]

#: Bump when compile or link flags change but the C text might not.
CACHE_FLAVOR = "sbf-o2-gc-strip-v1"


def cache_directory() -> Path | None:
    """Return the cache root, or ``None`` when caching is off.

    ``PYTHSOL_NO_CACHE=1`` disables it. ``PYTHSOL_CACHE`` (or ``PYSOL_CACHE``)
    overrides the default directory.
    """
    flag = os.environ.get("PYTHSOL_NO_CACHE", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return None
    override = os.environ.get("PYTHSOL_CACHE") or os.environ.get("PYSOL_CACHE")
    if override:
        return Path(override).expanduser()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "pythsol" / "cache"
    return Path.home() / ".cache" / "pythsol"


def artifact_key(
    *,
    c_text: str,
    clang_version: str,
    arch: str,
    runtime_header: bytes,
) -> str:
    """sha256 of everything that changes the linked ``.so``."""
    digest = hashlib.sha256()
    digest.update(b"pythsol-cache\0")
    digest.update(CACHE_FLAVOR.encode())
    digest.update(b"\0")
    digest.update(__version__.encode())
    digest.update(b"\0")
    digest.update(clang_version.encode())
    digest.update(b"\0")
    digest.update(arch.encode())
    digest.update(b"\0")
    digest.update(hashlib.sha256(runtime_header).digest())
    digest.update(c_text.encode())
    return digest.hexdigest()


def lookup_so(root: Path, key: str) -> Path | None:
    """Return a cached ``.so`` for ``key``, or ``None``."""
    path = root / key / "program.so"
    if path.is_file() and path.stat().st_size > 0:
        return path
    return None


def store_so(root: Path, key: str, so_path: Path) -> None:
    """Copy ``so_path`` into the cache. A crash mid-write leaves the old file."""
    dest_dir = root / key
    dest_dir.mkdir(parents=True, exist_ok=True)
    temporary = dest_dir / "program.so.tmp"
    temporary.write_bytes(so_path.read_bytes())
    temporary.replace(dest_dir / "program.so")
