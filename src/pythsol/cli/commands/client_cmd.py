"""`pythsol client` and `pythsol cpi` — write a solders client.

A ``.py`` program is compiled with the front-end (no clang) and rendered from
the model. A ``.json`` IDL is rendered from the document. Neither output
imports the compiler.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from pythsol.client.from_idl import IdlClientError, render_client_from_idl
from pythsol.client.gen import render_client
from pythsol.compiler.modules import read_sibling_modules
from pythsol.compiler.pipeline import emit_program

_CPI_BANNER = (
    "# Off-chain instruction builders for CPI into this program.\n"
    "# PythSol does not lower a generic on-chain invoke. Call these from a client.\n"
)


def render_client_source(source: Path, *, address: str | None, cpi: bool) -> str:
    """Return client source for a program or an IDL file."""
    if source.suffix.lower() == ".json":
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise click.ClickException(f"invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise click.ClickException("IDL JSON must be an object")
        try:
            text = render_client_from_idl(payload, address=address)
        except IdlClientError as exc:
            raise click.ClickException(str(exc)) from exc
    else:
        try:
            source_text = source.read_text(encoding="utf-8", errors="replace")
            modules, module_files = read_sibling_modules(source)
        except OSError as exc:
            raise click.ClickException(f"cannot read {source}: {exc}") from exc
        generated = emit_program(
            source_text,
            source,
            modules=modules,
            module_files=module_files,
        )
        if not generated.ok or generated.generated is None:
            for diagnostic in generated.diagnostics:
                click.echo(diagnostic.render(), err=True)
            raise SystemExit(1)
        text = render_client(generated.generated)
        if address:
            needle = f"PROGRAM_NAME = {generated.generated.snake_name!r}\n"
            insert = needle + f"PROGRAM_ID = {address!r}\n"
            if needle in text:
                text = text.replace(needle, insert, 1)
            else:
                text = f"PROGRAM_ID = {address!r}\n" + text
    if cpi:
        text = _CPI_BANNER + text
    return text


def _write(text: str, out: Path | None) -> None:
    if out is None:
        click.echo(text, nl=False)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    click.echo(f"wrote {out}")


@click.command(name="client")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", "-o", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--address", default=None, help="Optional program id constant.")
def client_cmd(source: Path, out: Path | None, address: str | None) -> None:
    """Generate a solders client from a program or an IDL JSON file."""
    text = render_client_source(source, address=address, cpi=False)
    _write(text, out)
    sys.exit(0)


@click.command(name="cpi")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", "-o", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--address", default=None, help="Optional program id constant.")
def cpi_cmd(source: Path, out: Path | None, address: str | None) -> None:
    """Generate off-chain CPI builders from a program or an IDL JSON file."""
    text = render_client_source(source, address=address, cpi=True)
    _write(text, out)
    sys.exit(0)
