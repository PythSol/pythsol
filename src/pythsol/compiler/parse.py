"""Stage 1 — parse program source with :mod:`ast` (never executed).

The compiler's contract is that user code is only ever *parsed*, so this
module is deliberately tiny: ``ast.parse`` plus turning ``SyntaxError`` into
a :class:`~pythsol.compiler.diagnostics.Diagnostic` with stable code ``PS1000``.
"""

from __future__ import annotations

import ast

from pythsol.compiler.diagnostics import PS1000, Diagnostic

__all__ = ["parse_source"]


def parse_source(
    source: str,
    file: str = "<program>",
) -> tuple[ast.Module | None, list[Diagnostic]]:
    """Parse ``source``; return ``(tree, diagnostics)``.

    ``diagnostics`` is empty on success; on failure the tree is ``None`` and
    exactly one ``PS1000`` diagnostic is returned (parse errors are never
    recoverable mid-stream, Python's parser stops at the first one).
    """

    try:
        tree = ast.parse(source, filename=file)
    except SyntaxError as err:
        line = err.lineno or 1
        # SyntaxError.offset is 1-based; keep it, but clamp into the line.
        col = err.offset or 1
        text_line = source.splitlines()[line - 1] if line <= len(source.splitlines()) else ""
        col = max(1, min(col, max(1, len(text_line) + 1)))
        return None, [
            Diagnostic(
                code=PS1000,
                message=f"syntax error: {err.msg}",
                file=file,
                line=line,
                col=col,
            )
        ]
    except (ValueError, RecursionError) as err:  # null bytes / absurd nesting
        return None, [
            Diagnostic(
                code=PS1000,
                message=f"could not parse source: {err}",
                file=file,
                line=1,
                col=1,
            )
        ]
    if not isinstance(tree, ast.Module):  # pragma: no cover — mode="exec" always wraps
        return None, [
            Diagnostic(code=PS1000, message="unexpected parse result", file=file, line=1, col=1)
        ]
    return tree, []
