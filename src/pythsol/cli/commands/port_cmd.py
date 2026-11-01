"""`pythsol port` — sketch a PythSol program from an Anchor-legacy IDL."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from pythsol.client.port import PortError, render_port


@click.command(name="port")
@click.argument("idl", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", "-o", type=click.Path(dir_okay=False, path_type=Path), default=None)
def port_cmd(idl: Path, out: Path | None) -> None:
    """Write a skeleton program. Instruction bodies are ``pass``."""
    try:
        payload = json.loads(idl.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        click.echo(f"error: invalid JSON: {exc}", err=True)
        sys.exit(1)
    except OSError as exc:
        click.echo(f"error: cannot read {idl}: {exc}", err=True)
        sys.exit(2)
    if not isinstance(payload, dict):
        click.echo("error: IDL JSON must be an object", err=True)
        sys.exit(1)
    try:
        text = render_port(payload)
    except PortError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    if out is None:
        click.echo(text, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        click.echo(f"wrote {out}")
        click.echo("TODO: replace each `pass` with the instruction body")
    sys.exit(0)
