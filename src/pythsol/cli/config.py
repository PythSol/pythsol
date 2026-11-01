"""Read ``pysol.toml`` project files."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["ConfigError", "ProgramEntry", "ProjectConfig", "find_config", "load_config"]


class ConfigError(Exception):
    """``pysol.toml`` is missing a required field or has the wrong shape."""


@dataclass(frozen=True)
class ProgramEntry:
    """One ``[[programs]]`` row."""

    name: str
    entry: Path


@dataclass(frozen=True)
class ProjectConfig:
    """The fields `pythsol test` and `pythsol build` read from a project."""

    path: Path
    name: str
    programs: tuple[ProgramEntry, ...]
    out_dir: Path
    cluster: str


def find_config(start: Path) -> Path | None:
    """Walk from ``start`` toward the filesystem root looking for ``pysol.toml``."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for directory in [current, *current.parents]:
        candidate = directory / "pysol.toml"
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path) -> ProjectConfig:
    """Parse ``path``. Raises :class:`ConfigError` on a bad shape."""
    raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    project = raw.get("project")
    build = raw.get("build")
    cluster = raw.get("cluster")
    programs_raw = raw.get("programs")
    if not isinstance(programs_raw, list) or not programs_raw:
        raise ConfigError("pysol.toml needs at least one [[programs]] entry")
    root = path.parent
    programs: list[ProgramEntry] = []
    for item in programs_raw:
        if not isinstance(item, dict):
            raise ConfigError("[[programs]] entries must be tables")
        name = item.get("name")
        entry = item.get("entry")
        if not isinstance(name, str) or not name:
            raise ConfigError("a program needs a name")
        if not isinstance(entry, str) or not entry:
            raise ConfigError(f"program `{name}` needs an entry path")
        programs.append(ProgramEntry(name, (root / entry).resolve()))
    out_raw = "target/pythsol"
    if isinstance(build, dict) and isinstance(build.get("out_dir"), str):
        out_raw = build["out_dir"]
    default_cluster = "devnet"
    if isinstance(cluster, dict) and isinstance(cluster.get("default"), str):
        default_cluster = cluster["default"]
    project_name = root.name
    if isinstance(project, dict) and isinstance(project.get("name"), str):
        project_name = project["name"]
    return ProjectConfig(
        path=path,
        name=project_name,
        programs=tuple(programs),
        out_dir=(root / out_raw).resolve(),
        cluster=default_cluster,
    )
