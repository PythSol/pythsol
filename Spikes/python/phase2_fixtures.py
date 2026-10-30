"""Dev helper: print actual front-end diagnostics for every Phase 2 fixture."""

from __future__ import annotations

import sys

sys.path.insert(0, "tests")

from pythsol.compiler import front  # noqa: E402
from pythsol.compiler.diagnostics import PS9000  # noqa: E402
import test_phase2 as tp  # noqa: E402


def main() -> None:
    for fixture in tp.FIXTURES:
        diags = front.check_source(fixture.source, file=f"{fixture.name}.py")
        hit = [
            d for d in diags if d.code == fixture.code and d.line == fixture.line and d.col == fixture.col
        ]
        if hit:
            continue
        rendered = [d.render().replace("\n", " | ") for d in diags] or ["(none)"]
        if len(sys.argv) > 1 and sys.argv[1] != fixture.name:
            continue
        print(f"== {fixture.name}: want {fixture.code} {fixture.line}:{fixture.col}")
        for line in rendered:
            print("   ", line)
        if any(d.code == PS9000 for d in diags):
            print("    !! PS9000 internal error")


if __name__ == "__main__":
    main()
