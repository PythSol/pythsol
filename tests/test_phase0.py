"""Phase 0 sanity tests: these pass with `pip install -e .` and `pytest` alone."""

from __future__ import annotations

import importlib


def test_package_importable() -> None:
    mod = importlib.import_module("pythsol")
    assert mod.__version__


def test_compiler_package_importable() -> None:
    mod = importlib.import_module("pythsol.compiler")
    assert mod is not None
    assert mod.ToolchainPaths is not None


def test_doctor_import() -> None:
    from pythsol.cli.commands.doctor import doctor  # noqa: F401
    from pythsol.cli.main import (
        cli,  # noqa: F401
    )


def test_run_doctor_pure_python_only(rpc: bool = False) -> None:
    """`run_doctor` must not call the network when `do_rpc=False`."""
    from pythsol.cli.commands.doctor import run_doctor

    report = run_doctor(do_rpc=False)
    assert report.checks
    assert all(c.ok or c.fix_cmd for c in report.checks)


def test_doctor_json_shape() -> None:
    from pythsol.cli.commands.doctor import run_doctor

    payload = run_doctor(do_rpc=False).to_json()
    assert payload["ok"] is not None
    assert isinstance(payload["checks"], list)
    assert payload["checks"]
    first = payload["checks"][0]
    for key in ("name", "ok", "detail", "fix_cmd"):
        assert key in first


def test_cli_help() -> None:
    from click.testing import CliRunner

    from pythsol.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "doctor" in result.output


def test_pysol_alias_is_packaged() -> None:
    """`pysol` should be a console script alias, not a CLI subcommand."""
    from importlib.metadata import distribution

    dist = distribution("pythsol")
    eps = next(ep for ep in dist.entry_points if ep.group == "console_scripts")
    names = {ep.name for ep in dist.entry_points if ep.group == "console_scripts"}
    assert names == {"pythsol", "pysol"}
    assert eps is not None
