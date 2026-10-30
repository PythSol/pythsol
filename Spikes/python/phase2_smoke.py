"""Smoke script for Phase 2 front-end stages (dev helper, not shipped)."""

from __future__ import annotations

from pathlib import Path

from pythsol.compiler.front import check_source

cases: dict[str, str] = {
    "try": "from pythsol import u64\nx = 1\ntry:\n    pass\nexcept Exception:\n    pass\n",
    "float": "from pythsol import u8\n@instruction\ndef f(x: u8) -> None:\n    y: u8 = 1.5\n",
    "alias": (
        "from pythsol import Mut, account, instruction\n"
        "@account\nclass Counter:\n    count: u64\n"
        "@instruction\ndef dup(a: Mut[Counter], b: Mut[Counter]) -> None:\n    pass\n"
    ),
    "field": (
        "from pythsol import Mut, account, instruction, require, u64, error, ProgramError\n"
        "@account\nclass Counter:\n    count: u64\n"
        "@error\nclass Err(ProgramError):\n    Bad = 1\n"
        "@instruction\ndef f(c: Mut[Counter]) -> None:\n"
        "    require(c.count < 1, Err.Bad)\n    c.missing = 1\n"
    ),
}

if __name__ == "__main__":
    for name, src in cases.items():
        diags = check_source(src, name + ".py")
        print(f"== {name}: {len(diags)}")
        for d in diags:
            print("  ", d.render().replace("\n", " | "))
    counter = Path("examples/counter/programs/counter.py").read_text(encoding="utf-8")
    print("== counter:", [d.render() for d in check_source(counter, "counter.py")])
