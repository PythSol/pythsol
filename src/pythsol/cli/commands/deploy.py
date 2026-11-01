"""`pythsol deploy` — build, then `solana program deploy`.

``--dry-run`` prints the command and does not run it. Mainnet requires
``--yes``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from pythsol.cli.cluster import is_mainnet, resolve_url
from pythsol.cli.commands.build import BuildFailed, build_program
from pythsol.compiler.diagnostics import PysolError
from pythsol.compiler.toolchain import default_solana_keypair

#: Lamports per program-data byte, the figure the TRD cites for a rent estimate.
_LAMPORTS_PER_BYTE = 6960


def deploy_argv(
    so: Path,
    url: str,
    *,
    keypair: Path | None,
    program_keypair: Path | None,
) -> list[str]:
    """The ``solana program deploy`` invocation for this artifact."""
    argv = ["solana", "program", "deploy", str(so), "--url", url]
    if keypair is not None:
        argv.extend(["--keypair", str(keypair)])
    if program_keypair is not None:
        argv.extend(["--program-id", str(program_keypair)])
    return argv


@click.command(name="deploy")
@click.argument(
    "program",
    required=False,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--so", "so_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--url", default=None, help="Cluster name or RPC URL. Default: devnet.")
@click.option("--keypair", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--program-keypair", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--dry-run", is_flag=True, help="Print the deploy command and do not run it.")
@click.option("--yes", is_flag=True, help="Required for mainnet.")
def deploy(
    program: Path | None,
    so_path: Path | None,
    url: str | None,
    keypair: Path | None,
    program_keypair: Path | None,
    dry_run: bool,
    yes: bool,
) -> None:
    """Build (unless ``--so`` is set) and deploy with the Solana CLI."""
    cluster = resolve_url(url)
    if is_mainnet(cluster) and not yes:
        click.echo("error: mainnet deploy requires --yes", err=True)
        sys.exit(1)
    if so_path is None:
        if program is None:
            click.echo("error: pass a program or --so", err=True)
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
        so_path = built.so_path
    size = so_path.stat().st_size
    rent = size * _LAMPORTS_PER_BYTE
    payer = keypair or default_solana_keypair()
    argv = deploy_argv(so_path, cluster, keypair=payer, program_keypair=program_keypair)
    click.echo(f"program bytes: {size}")
    click.echo(f"estimated rent: {rent / 1_000_000_000:.6f} SOL (program data only)")
    click.echo(" ".join(argv))
    if dry_run:
        sys.exit(0)
    if shutil_which("solana") is None:
        click.echo("error: solana CLI not found", err=True)
        sys.exit(1)
    completed = subprocess.run(argv, check=False)
    sys.exit(int(completed.returncode))


def shutil_which(name: str) -> str | None:
    """Indirection so tests can replace the lookup."""
    import shutil

    return shutil.which(name)
