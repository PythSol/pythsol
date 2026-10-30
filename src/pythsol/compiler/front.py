"""Front-end entry point — run parse → subset → resolve → typecheck.

``check_source`` is the API the CLI and tests build on. It never raises for
malformed *user input*: every failure becomes a diagnostic. Only genuine
compiler bugs escape as ``PS9000`` diagnostics (still not exceptions), which
is what the random-AST fuzzer relies on.
"""

from __future__ import annotations

import ast

from pythsol.compiler import resolve, subset, typecheck
from pythsol.compiler.diagnostics import PS9000, Diagnostic
from pythsol.compiler.parse import parse_source

__all__ = ["check_source", "check_tree"]


def check_source(source: str, file: str = "<program>") -> list[Diagnostic]:
    """Check a program from text; returns all diagnostics."""
    try:
        tree, parse_diags = parse_source(source, file)
    except Exception as err:
        return _internal(file, "parse", err)
    if tree is None:
        return parse_diags
    return check_tree(tree, file)


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
