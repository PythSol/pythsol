"""Stable diagnostic codes and helpers shared by every compiler stage.

Codes follow the pattern used in ``TRD.md`` §5.3:

* ``PS1xxx`` — subset/parse
* ``PS2xxx`` — type check
* ``PS3xxx`` — semantic/aliasing
* ``PS9xxx`` — internal compiler error (always a bug: report it)

The registry below is written for Phase 2, but Phase 1 already hands back
structured objects for toolchain errors.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    """One problem with a stable code and 1-based source position.

    ``render()`` produces the clang-style string the CLI prints:

        PS1003 program.py:4:5: unsupported statement: Try

    The shape of :meth:`as_dict` is the ``--json`` contract; keep it additive.
    """

    code: str
    message: str
    file: str = "<program>"
    line: int = 1
    col: int = 1
    fix: str | None = None

    def render(self) -> str:
        text = f"{self.code} {self.file}:{self.line}:{self.col}: {self.message}"
        if self.fix:
            return f"{text}\n  fix: {self.fix}"
        return text

    def position_key(self) -> tuple[int, int]:
        return (self.line, self.col)

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "code": self.code,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "fix": self.fix,
        }


class PysolError(Exception):
    """A structured compiler/toolchain error raised back to the CLI.

    Not a dataclass: exceptions must accept ``__traceback__`` writes when
    raised (a frozen dataclass blocks click's re-raise machinery).
    """

    def __init__(self, code: str, message: str, fix: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fix = fix

    def render(self) -> str:
        text = f"{self.code}: {self.message}"
        if self.fix:
            return f"{text}\nsuggested fix: {self.fix}"
        return text


# ---------------------------------------------------------------------------
# Subset / parse problems (PS1xxx)
# ---------------------------------------------------------------------------
PS1000 = "PS1000"  # unparseable syntax
PS1001 = "PS1001"  # unsupported import
PS1002 = "PS1002"  # floats/complex in program code
PS1003 = "PS1003"  # unsupported statement (try/except, with, yield…)
PS1004 = "PS1004"  # dynamic `import` or `__import__`
PS1005 = "PS1005"  # `*args`/`**kwargs`/defaults on instruction functions are not callable.
PS1006 = "PS1006"  # missing annotation on a parameter/field local.
PS1007 = "PS1007"  # unsupported type annotation (unbounded containers, Any).
PS1008 = "PS1008"  # unsupported attribute access / dynamic attribute assignment.
PS1009 = "PS1009"  # unsupported operator (is, in, not-in on non-enums).
PS1010 = "PS1010"  # unsupported call (dynamic callee).
PS1011 = "PS1011"  # unsupported comprehension/generator.
PS1012 = "PS1012"  # unsupported `class` (only @account/@error/@enum programs).

# ---------------------------------------------------------------------------
# Type-check problems (PS2xxx)
# ---------------------------------------------------------------------------
PS2000 = "PS2000"  # missing annotation on anything not inferable.
PS2001 = "PS2001"  # unsupported/unknown type annotation.
PS2002 = "PS2002"  # `float`/`complex` literal in program code.
PS2003 = "PS2003"  # unbounded integers (int) are not allowed.
PS2004 = "PS2004"  # bytes/str/list/tuple/dict/set in a program.
PS2005 = "PS2005"  # unsupported assignment target.
PS2006 = "PS2006"  # TypeError / unexpected operand.
PS2007 = "PS2007"  # int width mismatch/overflow on constant expression.
PS2008 = "PS2008"  # unsupported decorator target.

# ---------------------------------------------------------------------------
# Semantic / account-model problems (PS3xxx)
# ---------------------------------------------------------------------------
PS3000 = "PS3000"  # aliasing refusal (mutable data used for a live aliasing reference).
PS3001 = "PS3001"  # unsupported constraint combination.

# ---------------------------------------------------------------------------
# Toolchain problems (PS40xx) — see toolchain.py for exact text.
# ---------------------------------------------------------------------------
PS4010 = "PS4010"

# Model/elaboration problems (PS41xx) — raised by model.py when a type-checked
# program still contains something the emitter model cannot represent.
PS4001 = "PS4001"  # unsupported construct in the emitter model

# Emitter problems (PS5xxx) — raised by emit.py while lowering an AST body.
PS5001 = "PS5001"  # unsupported statement in an instruction body
PS5002 = "PS5002"  # unsupported expression in an instruction body
PS5003 = "PS5003"  # Init[...] without a `bump: u8` data parameter / payer signer

# ---------------------------------------------------------------------------
# Internal compiler errors (PS9xxx)
# ---------------------------------------------------------------------------
PS9000 = "PS9000"  # internal bug: unhandled construct in emitter.
