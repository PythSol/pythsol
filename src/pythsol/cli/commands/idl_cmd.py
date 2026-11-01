"""`pythsol idl PROGRAM.py` — write the Anchor-style IDL (no SBF toolchain)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from pythsol.compiler.idl import idl_json
from pythsol.compiler.modules import read_sibling_modules
from pythsol.compiler.pipeline import emit_program


@click.command(name="idl")
@click.argument(
    "program",
    metavar="PROGRAM.py",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--out",
    "-o",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default=None,
    help="Write the IDL here instead of printing it.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable diagnostics on stdout when the program fails.",
)
def idl(program: Path, out: Path | None, as_json: bool) -> None:
    """Generate the legacy IDL for a PythSol program."""
    try:
        source_text = program.read_text(encoding="utf-8", errors="replace")
        modules, module_files = read_sibling_modules(program)
    except OSError as os_error:
        click.echo(f"error: cannot read {program}: {os_error}", err=True)
        sys.exit(2)

    generated = emit_program(
        source_text,
        program,
        modules=modules,
        module_files=module_files,
    )
    if not generated.ok or generated.generated is None:
        for diagnostic in generated.diagnostics:
            click.echo(diagnostic.render(), err=True)
        if as_json:
            payload = {
                "ok": False,
                "diagnostics": [item.as_dict() for item in generated.diagnostics],
            }
            click.echo(json.dumps(payload, indent=2))
        sys.exit(1)

    text = idl_json(generated.generated)
    if out is None:
        click.echo(text, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        click.echo(f"idl: wrote {out}")
    sys.exit(0)
