"""`pythsol verify` — compare two program binaries, or a build against a dump.

Exit ``0`` when the sha256 matches. Exit ``3`` when it does not.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

import click

from pythsol.cli.cluster import resolve_url
from pythsol.cli.commands.build import BuildFailed, build_program
from pythsol.compiler.diagnostics import PysolError


def file_sha256(path: Path) -> str:
    """sha256 hex of ``path``."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_argv(address: str, url: str, dest: Path) -> list[str]:
    """``solana program dump`` invocation."""
    return ["solana", "program", "dump", "--url", url, address, str(dest)]


def _emit(left: Path, right: Path) -> None:
    left_hash = file_sha256(left)
    right_hash = file_sha256(right)
    if left_hash == right_hash:
        click.echo(f"MATCH sha256:{left_hash}")
        sys.exit(0)
    click.echo(f"MISMATCH {left} sha256:{left_hash} ({left.stat().st_size} bytes)", err=True)
    click.echo(f"MISMATCH {right} sha256:{right_hash} ({right.stat().st_size} bytes)", err=True)
    sys.exit(3)


@click.command(name="verify")
@click.argument("program", required=False, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--left", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option("--right", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option("--dump", "dump_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--address", default=None, help="On-chain program id to dump and compare.")
@click.option("--url", default=None, help="Cluster name or RPC URL for --address.")
def verify(
    program: Path | None,
    left: Path | None,
    right: Path | None,
    dump_path: Path | None,
    address: str | None,
    url: str | None,
) -> None:
    """Compare sha256 hashes. Exit 3 on a mismatch."""
    if left is not None and right is not None:
        _emit(left, right)
    if left is not None or right is not None:
        click.echo("error: pass both --left and --right", err=True)
        sys.exit(2)
    if program is None or not program.is_file():
        click.echo("error: pass two files, or a program plus --dump or --address", err=True)
        sys.exit(2)
    try:
        built = build_program(program)
    except OSError as os_error:
        click.echo(f"error: cannot read {program}: {os_error}", err=True)
        sys.exit(2)
    except BuildFailed as failed:
        for diagnostic in failed.diagnostics:
            click.echo(diagnostic.render(), err=True)
        sys.exit(1)
    except PysolError as error:
        click.echo(error.render(), err=True)
        sys.exit(1)
    if dump_path is not None:
        _emit(built.so_path, dump_path)
    if address is None:
        click.echo("error: pass --dump or --address to compare a build", err=True)
        sys.exit(2)
    import shutil

    if shutil.which("solana") is None:
        click.echo("error: solana CLI not found", err=True)
        sys.exit(1)
    with tempfile.TemporaryDirectory(prefix="pythsol-verify-") as tmp:
        dest = Path(tmp) / "chain.so"
        argv = dump_argv(address, resolve_url(url), dest)
        click.echo(" ".join(argv))
        completed = subprocess.run(argv, check=False)
        if completed.returncode != 0 or not dest.is_file():
            click.echo("error: solana program dump failed", err=True)
            sys.exit(1)
        _emit(built.so_path, dest)
