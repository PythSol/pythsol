"""`pythsol idl-publish` — write the IDL and optionally hand it to Anchor.

On-chain publish runs ``anchor idl init`` only when the Anchor CLI is on
``PATH``. ``--dry-run`` prints that command and does not look for Anchor.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from pythsol.cli.cluster import resolve_url
from pythsol.compiler.idl import idl_json
from pythsol.compiler.modules import read_sibling_modules
from pythsol.compiler.pipeline import emit_program


def anchor_idl_argv(idl_path: Path, address: str, url: str) -> list[str]:
    """The Anchor CLI invocation that would publish this IDL."""
    return [
        "anchor",
        "idl",
        "init",
        "--filepath",
        str(idl_path),
        "--provider.cluster",
        url,
        address,
    ]


@click.command(name="idl-publish")
@click.argument("program", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", "-o", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--address", required=True, help="Program id the IDL is published for.")
@click.option("--url", default=None, help="Cluster name or RPC URL. Default: devnet.")
@click.option("--dry-run", is_flag=True, help="Write the IDL and print the anchor command.")
def idl_publish(
    program: Path,
    out: Path | None,
    address: str,
    url: str | None,
    dry_run: bool,
) -> None:
    """Write an IDL file. Publish it only when the Anchor CLI is installed."""
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
        sys.exit(1)
    dest = out or Path("target/pythsol") / generated.name / f"{generated.name}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(idl_json(generated.generated, address=address), encoding="utf-8", newline="\n")
    cluster = resolve_url(url)
    argv = anchor_idl_argv(dest, address, cluster)
    click.echo(f"idl: wrote {dest}")
    click.echo(" ".join(argv))
    if dry_run:
        sys.exit(0)
    import shutil

    if shutil.which("anchor") is None:
        click.echo("error: anchor CLI not found; IDL file was written", err=True)
        sys.exit(1)
    completed = subprocess.run(argv, check=False)
    sys.exit(int(completed.returncode))
