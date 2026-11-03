"""Packaging: the wheel carries every playground asset and both CLI names."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _config() -> dict[str, object]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_every_playground_asset_is_force_included_in_the_wheel() -> None:
    config = _config()
    force = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]  # type: ignore[index]
    playground = ROOT / "src" / "pythsol" / "playground"
    assets = {path.name for path in playground.iterdir() if path.is_file() and path.suffix != ".py"}
    included = {Path(source).name for source in force}
    assert assets == included, f"wheel is missing {sorted(assets - included)}"


def test_wheel_metadata_exposes_both_cli_names_and_the_pytest_plugin() -> None:
    project = _config()["project"]
    assert project["name"] == "pythsol"  # type: ignore[index]
    scripts = project["scripts"]  # type: ignore[index]
    assert scripts["pythsol"] == "pythsol.cli.main:main"
    assert scripts["pysol"] == "pythsol.cli.main:main"
    entry_points = project["entry-points"]  # type: ignore[index]
    assert entry_points["pytest11"]["pythsol"] == "pythsol.testing.plugin"
