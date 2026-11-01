"""`pythsol test` — build the program, then run pytest against LiteSVM."""

from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import click

from pythsol.cli.commands.build import BuildFailed, build_program
from pythsol.cli.config import ConfigError, find_config, load_config
from pythsol.compiler.diagnostics import PysolError

_VALUE_FLAGS = {"-k", "-m", "--tb", "-p", "-c", "--override-ini", "-o", "--rootdir"}


def _has_node(args: tuple[str, ...]) -> bool:
    """True when the user already named a file or directory for pytest."""
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in _VALUE_FLAGS:
            skip = True
            continue
        if arg.startswith("-"):
            continue
        return True
    return False


def _project_root(program: Path) -> Path:
    if program.parent.name == "programs":
        return program.parent.parent
    return program.parent


def _pytest_cmd(paths: list[str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "pythsol.testing.plugin",
        "-q",
        "--tb=short",
        *paths,
    ]


def _wait_rpc(url: str, timeout_s: float) -> bool:
    import time

    from pythsol.cli.rpc import post_json

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            post_json(url, "getHealth", [])
            return True
        except Exception:
            time.sleep(0.4)
    return False


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_localnet(so: Path, cmd: list[str], env: dict[str, str], cwd: Path) -> int:
    """Start a test validator, deploy ``so``, run pytest, then stop the validator."""
    port = _free_port()
    ledger = Path(tempfile.mkdtemp(prefix="pythsol-ledger-"))
    url = f"http://127.0.0.1:{port}"
    validator = [
        "solana-test-validator",
        "--ledger",
        str(ledger),
        "--rpc-port",
        str(port),
        "--bind-address",
        "127.0.0.1",
        "--reset",
        "--quiet",
    ]
    proc = subprocess.Popen(validator, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not _wait_rpc(url, 90):
            click.echo("error: solana-test-validator did not open an RPC port", err=True)
            return 1
        deploy = ["solana", "program", "deploy", str(so), "--url", url]
        completed = subprocess.run(deploy, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            click.echo(completed.stderr or completed.stdout or "deploy failed", err=True)
            return 1
        child_env = dict(env)
        child_env["PYSOL_RPC_URL"] = url
        child_env["PYTHSOL_TEST_RPC"] = url
        click.echo(f"localnet: {url}")
        result = subprocess.run(cmd, cwd=cwd, env=child_env, check=False)
        return int(result.returncode)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(ledger, ignore_errors=True)


@click.command(
    name="test",
    context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False},
)
@click.option(
    "--program",
    "program_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Program entry. Default: the first [[programs]] entry in pysol.toml.",
)
@click.option("--localnet", is_flag=True, help="Also deploy onto solana-test-validator.")
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
def test_cmd(program_path: Path | None, localnet: bool, pytest_args: tuple[str, ...]) -> None:
    """Build the program and run pytest.

    Tests use the ``program``, ``payer``, ``svm``, ``accounts``, and ``send``
    fixtures. The runner is LiteSVM. ``--localnet`` also starts
    ``solana-test-validator`` and deploys the ``.so`` when that CLI is installed.
    The fixtures stay on LiteSVM either way.
    """
    if localnet and (
        shutil.which("solana-test-validator") is None or shutil.which("solana") is None
    ):
        click.echo("error: solana-test-validator not found", err=True)
        click.echo(
            '  fix: sh -c "$(curl -sSfL https://release.anza.xyz/stable/install)"',
            err=True,
        )
        sys.exit(1)
    if importlib.util.find_spec("pytest") is None:
        click.echo("error: pytest is not installed. pip install 'pythsol[test]'", err=True)
        sys.exit(1)

    config_path = None if program_path is not None else find_config(Path.cwd())
    out: Path | None = None
    name: str | None = None
    root: Path
    if program_path is None:
        if config_path is None:
            click.echo("error: pass a program or run from a directory with pysol.toml", err=True)
            sys.exit(2)
        try:
            config = load_config(config_path)
        except ConfigError as exc:
            click.echo(f"error: {exc}", err=True)
            sys.exit(2)
        entry = config.programs[0]
        program_path = entry.entry
        name = entry.name
        out = config.out_dir / entry.name
        root = config_path.parent
    else:
        root = _project_root(program_path)

    if not program_path.is_file():
        click.echo(f"error: program not found: {program_path}", err=True)
        sys.exit(2)

    try:
        built = build_program(program_path, out=out, name=name)
    except OSError as os_error:
        click.echo(f"error: cannot read {program_path}: {os_error}", err=True)
        sys.exit(2)
    except BuildFailed as failed:
        for diagnostic in failed.diagnostics:
            click.echo(diagnostic.render(), err=True)
        sys.exit(1)
    except PysolError as error:
        click.echo(error.render(), err=True)
        sys.exit(1)

    if built.cache == "hit":
        click.echo("build: cache hit (skipped clang)")
    click.echo(f"test: {built.so_path}")

    if _has_node(pytest_args):
        nodes = list(pytest_args)
    else:
        tests = root / "tests"
        if not tests.is_dir():
            click.echo(f"error: no tests directory at {tests}", err=True)
            sys.exit(1)
        nodes = [str(tests), *pytest_args]

    env = os.environ.copy()
    env["PYTHSOL_TEST_SO"] = str(built.so_path)
    env["PYTHSOL_TEST_CLIENT"] = str(built.client_path)
    env["PYTHSOL_TEST_SOURCE"] = str(program_path)
    env["PYTHSOL_TEST_IDL"] = str(built.idl_path)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    cmd = _pytest_cmd(nodes)
    if localnet:
        code = _run_localnet(built.so_path, cmd, env, root)
    else:
        completed = subprocess.run(cmd, cwd=root, env=env, check=False)
        code = int(completed.returncode)
    sys.exit(code)
