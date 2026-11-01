"""CLI entry point (`pythsol`, aliased as the draft `pysol`)."""

from __future__ import annotations

import os
import sys

import click

from pythsol import __version__
from pythsol.cli.commands.build import build
from pythsol.cli.commands.check import check
from pythsol.cli.commands.client_cmd import client_cmd, cpi_cmd
from pythsol.cli.commands.deploy import deploy
from pythsol.cli.commands.docs_cmd import docs
from pythsol.cli.commands.doctor import doctor
from pythsol.cli.commands.emit_c import emit_c
from pythsol.cli.commands.faucet import faucet
from pythsol.cli.commands.idl_cmd import idl
from pythsol.cli.commands.idl_publish import idl_publish
from pythsol.cli.commands.init import init
from pythsol.cli.commands.port_cmd import port_cmd
from pythsol.cli.commands.profile import profile
from pythsol.cli.commands.serve import serve
from pythsol.cli.commands.test_cmd import test_cmd
from pythsol.cli.commands.verify import verify
from pythsol.cli.commands.wallet import wallet


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "--version", message="%(prog)s %(version)s")
@click.option("--quiet", is_flag=True, help="Silence non-essential output.")
@click.option("--verbose", is_flag=True, help="Show external commands that are run.")
def cli(quiet: bool, verbose: bool) -> None:
    """PythSol — Solana programs in typed Python."""
    # Per-command implementations use these flags; Phase 1 only needs doctor.
    _ = quiet, verbose


def main(prog_name: str | None = None) -> None:
    """Module entry point: "pythsol" or "pysol" depending on packaging aliases."""
    prog = prog_name or os.path.basename(sys.argv[0]) or "pythsol"
    cli(prog_name=prog)  # `Group.__call__` forwards to `Group.main(prog_name=prog)`.


# Re-attach commands after the group definition so auto-help works uniformly.
cli.add_command(doctor)
cli.add_command(check)
cli.add_command(emit_c)
cli.add_command(build)
cli.add_command(test_cmd)
cli.add_command(init)
cli.add_command(idl)
cli.add_command(idl_publish)
cli.add_command(client_cmd)
cli.add_command(cpi_cmd)
cli.add_command(deploy)
cli.add_command(faucet)
cli.add_command(wallet)
cli.add_command(port_cmd)
cli.add_command(verify)
cli.add_command(profile)
cli.add_command(docs)
cli.add_command(serve)


def _entrypoint() -> None:  # pragma: no cover — packaging script
    main()


if __name__ == "__main__":  # pragma: no cover
    _entrypoint()
