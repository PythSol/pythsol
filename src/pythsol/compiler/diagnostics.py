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
class PysolError(Exception):
    """A structured compiler/toolchain error raised back to the CLI."""

    code: str
    message: str
    fix: str | None = None

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
PS1012 = "PS1012"  # unsupported `class` (only @account/@error programs).

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
# Toolchain problems (PS4xxx) — see toolchain.py for exact text.
# ---------------------------------------------------------------------------
PS4010 = "PS4010"

# ---------------------------------------------------------------------------
# Internal compiler errors (PS9xxx)
# ---------------------------------------------------------------------------
PS9000 = "PS9000"  # internal bug: unhandled construct in emitter.
