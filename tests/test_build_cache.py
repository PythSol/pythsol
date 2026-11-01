"""A second build of the same program skips clang."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from pythsol.cli.main import cli

_PROGRAM = Path(__file__).parents[1] / "examples" / "counter" / "programs" / "counter.py"


def _tools_anywhere() -> bool:
    from pythsol.compiler import toolchain
    from pythsol.compiler.diagnostics import PysolError

    try:
        found = toolchain.locate_platform_tools(None)
    except PysolError:
        found = None
    if found is not None:
        return True
    sdk = Path(__file__).parents[1] / "Spikes" / "tools" / "platform-tools-1.58"
    if not sdk.is_dir():
        return False
    os.environ.setdefault("PYTHSOL_SBF_SDK", str(sdk))
    try:
        return toolchain.locate_platform_tools(None) is not None
    except PysolError:
        return False


@pytest.fixture
def toolchain_ready() -> None:
    if not _tools_anywhere():
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")


@pytest.mark.toolchain
def test_second_build_skips_clang(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    toolchain_ready: None,
) -> None:
    monkeypatch.setenv("PYTHSOL_CACHE", str(tmp_path / "cache"))
    runner = CliRunner()
    first = runner.invoke(cli, ["build", str(_PROGRAM), "--out", str(tmp_path / "one")])
    assert first.exit_code == 0, first.stderr
    assert "cache miss" in first.output

    def boom(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("clang should not run on a cache hit")

    monkeypatch.setattr("pythsol.compiler.toolchain.compile_to_sbf", boom)
    second = runner.invoke(cli, ["build", str(_PROGRAM), "--out", str(tmp_path / "two")])
    assert second.exit_code == 0, second.output + second.stderr
    assert "cache hit (skipped clang)" in second.output
    first_so = (tmp_path / "one" / "counter.so").read_bytes()
    second_so = (tmp_path / "two" / "counter.so").read_bytes()
    assert first_so == second_so
