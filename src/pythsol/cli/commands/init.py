"""`pythsol init DIR` — scaffold a counter, ledger, vault, or escrow program."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click

from pythsol.cli.templates import TEMPLATES, project_files

_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")


@click.command(name="init")
@click.argument(
    "directory",
    metavar="DIR",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option(
    "--template",
    type=click.Choice(TEMPLATES),
    default="counter",
    show_default=True,
    help="Program to write into programs/.",
)
@click.option(
    "--name",
    default=None,
    help="Project name (default: the directory name).",
)
def init(directory: Path, template: str, name: str | None) -> None:
    """Create a PythSol project (pysol.toml, program, README).

    Refuses to write into a directory that already has files.
    """
    project = name or directory.name
    if _NAME.fullmatch(project) is None:
        click.echo(
            f"error: name `{project}` must match {_NAME.pattern}",
            err=True,
        )
        sys.exit(2)
    if directory.exists() and not directory.is_dir():
        click.echo(f"error: {directory} is not a directory", err=True)
        sys.exit(2)
    if directory.exists() and any(directory.iterdir()):
        click.echo(f"error: {directory} is not empty", err=True)
        sys.exit(2)

    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for relative, text in project_files(project, template).items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)

    click.echo(f"Created {directory} (template: {template})")
    for path in written:
        click.echo(f"  {path.relative_to(directory).as_posix()}")
    click.echo(f"Next: cd {directory} && pythsol check programs/{project}.py && pythsol test")
    sys.exit(0)
