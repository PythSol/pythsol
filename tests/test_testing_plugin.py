"""`pythsol test` builds a template and runs its plugin-only pytest file."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from pythsol.cli.main import cli


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
@pytest.mark.parametrize("template", ["counter", "ledger", "vault", "escrow"])
def test_template_pytest_uses_the_plugin(
    template: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    toolchain_ready: None,
) -> None:
    monkeypatch.setenv("PYTHSOL_CACHE", str(tmp_path / "cache"))
    project = tmp_path / template
    created = CliRunner().invoke(
        cli,
        ["init", str(project), "--template", template, "--name", template],
    )
    assert created.exit_code == 0, created.stderr
    monkeypatch.chdir(project)
    result = CliRunner().invoke(cli, ["test"])
    assert result.exit_code == 0, result.stdout + "\n" + result.stderr
