"""CLI entry point (`pythsol`, aliased as the draft `pysol`)."""

from __future__ import annotations

import os
import sys

import click

from pythsol import __version__
from pythsol.cli.commands.doctor import doctor


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


def _entrypoint() -> None:  # pragma: no cover — packaging script
    main()


if __name__ == "__main__":  # pragma: no cover
    _entrypoint()
