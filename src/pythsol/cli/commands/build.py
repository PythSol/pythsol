"""`pythsol build PROGRAM.py` — C → SBF `.so` + IDL + manifest."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import click

from pythsol import __version__
from pythsol.compiler.diagnostics import PysolError
from pythsol.compiler.idl import idl_json
from pythsol.compiler.pipeline import emit_program
from pythsol.runtime import RUNTIME_INCLUDE_DIR


@click.command(name="build")
@click.argument(
    "program",
    metavar="PROGRAM.py",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory (default: target/pythsol/<name>).",
)
@click.option(
    "--name",
    default=None,
    help="Program name (default: the file stem).",
)
def build(program: Path, out: Path | None, name: str | None) -> None:
    """Compile a PythSol program to a native SBF `.so`, IDL and manifest.

    Produces ``<name>.c`` (generated C), ``<name>.so`` (the on-chain ELF),
    ``<name>.json`` (IDL) and ``manifest.json`` with sha256 hashes. Builds
    are byte-deterministic for identical input.
    """
    try:
        source_text = program.read_text(encoding="utf-8", errors="replace")
    except OSError as os_error:
        click.echo(f"error: cannot read {program}: {os_error}", err=True)
        sys.exit(2)

    generated = emit_program(source_text, program, name=name)
    if not generated.ok:
        for diagnostic in generated.diagnostics:
            click.echo(diagnostic.render(), err=True)
        sys.exit(1)
    assert generated.generated is not None  # ok-for-build guarantee from pipeline

    workdir = (out or Path("target/pythsol") / generated.name).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    c_path = workdir / f"{generated.name}.c"
    c_path.write_text(generated.c_text, encoding="utf-8", newline="\n")

    from pythsol.compiler import toolchain

    toolpaths = toolchain.locate_platform_tools(None)
    if toolpaths is None:
        raise PysolError(
            code="PS4010",
            message="no SBF platform-tools found; cannot finish the build",
            fix="run `pythsol doctor`; set PYTHSOL_SBF_SDK or install Agave "
            "platform-tools (CI Linux runners are the supported path)",
        )
    so_path = toolchain.compile_to_sbf(
        toolpaths,
        c_path,
        workdir,
        include_dirs=(RUNTIME_INCLUDE_DIR,),
    )

    idl_path = workdir / f"{generated.name}.json"
    idl_path.write_text(idl_json(generated.generated), encoding="utf-8", newline="\n")

    manifest = {
        "generator": f"pythsol {__version__}",
        "program": generated.name,
        "source": generated.source_file,
        "entrypoint": "entrypoint",
        "files": {
            "c": c_path.name,
            "idl": idl_path.name,
            "so": so_path.name,
        },
        "sha256": {
            "c": _sha256(c_path),
            "idl": _sha256(idl_path),
            "so": _sha256(so_path),
        },
        "toolchain": {
            "arch": toolpaths.arch,
            "clang": toolpaths.version or "unknown",
        },
    }
    manifest_path = workdir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    click.echo(f"build: {program} -> {so_path}")
    click.echo(f"build: idl -> {idl_path}")
    click.echo(f"build: manifest -> {manifest_path}")
    sys.exit(0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
