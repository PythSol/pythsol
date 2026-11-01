"""`pythsol build PROGRAM.py` — C → SBF `.so` + IDL + manifest."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from pythsol import __version__
from pythsol.cli.cache import artifact_key, cache_directory, lookup_so, store_so
from pythsol.client.gen import render_client
from pythsol.compiler.diagnostics import Diagnostic, PysolError
from pythsol.compiler.idl import idl_json
from pythsol.compiler.modules import read_sibling_modules
from pythsol.compiler.pipeline import emit_program
from pythsol.runtime import HEADER_NAME, RUNTIME_INCLUDE_DIR


class BuildFailed(Exception):  # noqa: N818
    """The program did not pass the compiler. ``diagnostics`` is non-empty."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__(f"{len(diagnostics)} diagnostics")


@dataclass(frozen=True)
class BuiltProgram:
    """Paths written by one successful build."""

    name: str
    workdir: Path
    c_path: Path
    so_path: Path
    idl_path: Path
    client_path: Path
    manifest_path: Path
    #: ``hit`` skipped clang, ``miss`` compiled, ``off`` cache disabled.
    cache: str


def build_program(
    program: Path,
    out: Path | None = None,
    name: str | None = None,
) -> BuiltProgram:
    """Compile ``program`` and return the artifact paths.

    Raises :class:`BuildFailed` for diagnostics, :class:`OSError` when a
    source file cannot be read, and :class:`PysolError` when clang is missing
    or the link fails.
    """
    source_text = program.read_text(encoding="utf-8", errors="replace")
    modules, module_files = read_sibling_modules(program)
    generated = emit_program(
        source_text,
        program,
        name=name,
        modules=modules,
        module_files=module_files,
    )
    if not generated.ok or generated.generated is None:
        raise BuildFailed(list(generated.diagnostics))

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

    header_path = RUNTIME_INCLUDE_DIR / HEADER_NAME
    header = header_path.read_bytes()
    key = artifact_key(
        c_text=generated.c_text,
        clang_version=toolpaths.version or "unknown",
        arch=toolpaths.arch,
        runtime_header=header,
    )
    root = cache_directory()
    cached = lookup_so(root, key) if root is not None else None
    so_path = workdir / f"{generated.name}.so"
    if cached is not None:
        shutil.copyfile(cached, so_path)
        cache = "hit"
    else:
        so_path = toolchain.compile_to_sbf(
            toolpaths,
            c_path,
            workdir,
            include_dirs=(RUNTIME_INCLUDE_DIR,),
        )
        if root is not None:
            store_so(root, key, so_path)
        cache = "miss" if root is not None else "off"

    idl_path = workdir / f"{generated.name}.json"
    idl_path.write_text(idl_json(generated.generated), encoding="utf-8", newline="\n")

    client_path = workdir / f"{generated.name}_client.py"
    client_path.write_text(
        render_client(generated.generated),
        encoding="utf-8",
        newline="\n",
    )

    manifest = {
        "generator": f"pythsol {__version__}",
        "program": generated.name,
        "source": generated.source_file,
        "entrypoint": "entrypoint",
        "cache": cache,
        "files": {
            "c": c_path.name,
            "idl": idl_path.name,
            "so": so_path.name,
            "client": client_path.name,
        },
        "sha256": {
            "c": _sha256(c_path),
            "idl": _sha256(idl_path),
            "so": _sha256(so_path),
            "client": _sha256(client_path),
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
    return BuiltProgram(
        name=generated.name,
        workdir=workdir,
        c_path=c_path,
        so_path=so_path,
        idl_path=idl_path,
        client_path=client_path,
        manifest_path=manifest_path,
        cache=cache,
    )


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
    ``<name>.json`` (IDL), ``<name>_client.py`` (solders builders) and
    ``manifest.json`` with sha256 hashes. Builds are byte-deterministic
    for identical input. A second build of the same C skips clang when the
    cache is on.
    """
    try:
        built = build_program(program, out=out, name=name)
    except OSError as os_error:
        click.echo(f"error: cannot read {program}: {os_error}", err=True)
        sys.exit(2)
    except BuildFailed as failed:
        for diagnostic in failed.diagnostics:
            click.echo(diagnostic.render(), err=True)
        sys.exit(1)
    except PysolError as error:
        click.echo(error.render(), err=True)
        sys.exit(1)

    click.echo(f"build: {program} -> {built.so_path}")
    if built.cache == "hit":
        click.echo("build: cache hit (skipped clang)")
    elif built.cache == "miss":
        click.echo("build: cache miss")
    click.echo(f"build: idl -> {built.idl_path}")
    click.echo(f"build: client -> {built.client_path}")
    click.echo(f"build: manifest -> {built.manifest_path}")
    sys.exit(0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
