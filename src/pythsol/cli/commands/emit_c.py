"""`pythsol emit-c PROGRAM.py` — print or write the generated C."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from pythsol.compiler.modules import read_sibling_modules
from pythsol.compiler.pipeline import emit_program


@click.command(name="emit-c")
@click.argument(
    "program",
    metavar="PROGRAM.py",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default=None,
    help="Write the C file here instead of printing it.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable diagnostics on stdout.",
)
def emit_c(program: Path, out: Path | None, as_json: bool) -> None:
    """Generate C from a PythSol program (no SBF toolchain needed)."""
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
    if not generated.ok:
        for diagnostic in generated.diagnostics:
            click.echo(diagnostic.render(), err=True)
        if as_json:
            payload = {
                "ok": False,
                "diagnostics": [d.as_dict() for d in generated.diagnostics],
            }
            click.echo(json.dumps(payload, indent=2))
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"ok": True, "diagnostics": []}, indent=2))

    if out is None:
        click.echo(generated.c_text)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(generated.c_text, encoding="utf-8", newline="\n")
        click.echo(f"emit-c: wrote {out}")
    sys.exit(0)
