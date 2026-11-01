"""`pythsol check PROGRAM.py` — run the front-end and report diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from pythsol.compiler.front import check_source
from pythsol.compiler.modules import read_sibling_modules


@click.command(name="check")
@click.argument(
    "program",
    metavar="PROGRAM.py",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON diagnostics.",
)
def check(program: Path, as_json: bool) -> None:
    """Type-check a program with the PythSol front-end (no SBF toolchain)."""
    try:
        source = program.read_text(encoding="utf-8", errors="replace")
        modules, module_files = read_sibling_modules(program)
    except OSError as err:
        click.echo(f"error: cannot read {program}: {err}", err=True)
        sys.exit(2)
    diagnostics = check_source(
        source,
        file=str(program),
        modules=modules,
        module_files=module_files,
    )
    diagnostics.sort(key=lambda d: (d.file, d.line, d.col, d.code))
    if as_json:
        payload = {
            "ok": not diagnostics,
            "diagnostics": [d.as_dict() for d in diagnostics],
        }
        click.echo(json.dumps(payload, indent=2))
    elif diagnostics:
        for diag in diagnostics:
            click.echo(diag.render())
    else:
        click.echo(f"check: {program} - no problems found")
    sys.exit(0 if not diagnostics else 1)
