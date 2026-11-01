"""Front-end entry point — run parse → subset → resolve → typecheck.

``check_source`` is the API the CLI and tests build on. It never raises for
malformed *user input*: every failure becomes a diagnostic. Only genuine
compiler bugs escape as ``PS9000`` diagnostics (still not exceptions), which
is what the random-AST fuzzer relies on.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping

from pythsol.compiler import resolve, subset, typecheck
from pythsol.compiler.diagnostics import PS9000, Diagnostic
from pythsol.compiler.modules import load_program

__all__ = ["check_source", "check_tree"]


def check_source(
    source: str,
    file: str = "<program>",
    *,
    modules: Mapping[str, str] | None = None,
    module_files: Mapping[str, str] | None = None,
) -> list[Diagnostic]:
    """Check a program from text; returns all diagnostics.

    ``modules`` maps a sibling module name to source text. The compiler parses
    those strings. It does not import or execute them. Omit ``modules`` for a
    single file; a foreign import is then rejected exactly as before.
    """
    try:
        program, diagnostics = load_program(source, file, modules, module_files)
    except Exception as err:
        return _internal(file, "parse", err)
    if program is None or diagnostics:
        return diagnostics
    try:
        diagnostics.extend(typecheck.check_program(program, file))
    except Exception as err:
        return diagnostics + _internal(file, "typecheck", err)
    return diagnostics


def check_tree(tree: ast.Module, file: str = "<program>") -> list[Diagnostic]:
    """Check an already-parsed module tree (parse diagnostics must be empty)."""
    diagnostics: list[Diagnostic] = []
    try:
        subset_diags = subset.scan_tree(tree, file)
    except Exception as err:
        return _internal(file, "subset", err)
    diagnostics.extend(subset_diags)
    if subset_diags:
        return diagnostics  # structural errors: resolve/typecheck results are noise

    try:
        program, resolve_diags = resolve.collect(tree, file)
    except Exception as err:
        return diagnostics + _internal(file, "resolve", err)
    diagnostics.extend(resolve_diags)
    if resolve_diags:
        return diagnostics

    try:
        diagnostics.extend(typecheck.check_program(program, file))
    except Exception as err:
        return diagnostics + _internal(file, "typecheck", err)
    return diagnostics


def _internal(file: str, stage: str, err: BaseException) -> list[Diagnostic]:
    """A raised exception from a stage is a compiler bug: report it as PS9000."""
    return [
        Diagnostic(
            code=PS9000,
            message=f"internal compiler error in {stage}: {err!r}",
            file=file,
            line=1,
            col=1,
            fix="please report this at github.com/PythSol/pythsol/issues",
        )
    ]
