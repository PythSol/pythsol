"""Phase 2 acceptance: front-end diagnostics, negative fixtures, CLI, fuzzing.

Fixtures here are *programs that must be rejected*, each pinned to a stable
 ``(code, line, col)``. They double as the language's negative reference set —
when you change the subset, change these expectations deliberately.
"""

from __future__ import annotations

import ast  # noqa: F401 — re-exported for the fuzzer helpers below
from dataclasses import dataclass
from pathlib import Path

import pytest

import pythsol
from pythsol.compiler import front
from pythsol.compiler.diagnostics import PS9000, Diagnostic
from pythsol.compiler.subset import PYTHSOL_EXPORTS

# ---------------------------------------------------------------------------
# Fixture table
# ---------------------------------------------------------------------------

#: 13-line shared header; body fixtures start at line 14.
_HEADER = "\n".join(
    (
        "from pythsol import Init, Mut, ProgramError, Pubkey, Signer, account, error, instruction, require, u64, u8",
        "",
        "@account",
        "class Counter:",
        "    authority: Pubkey",
        "    count: u64",
        "",
        "@error",
        "class Err(ProgramError):",
        "    Unauthorized = 100",
        "",
        "@instruction",
        "def increment(authority: Signer, counter: Mut[Counter], n: u64) -> None:",
    )
)


@dataclass(frozen=True)
class Fixture:
    name: str
    source: str
    code: str
    line: int
    col: int


def _body_fixture(name: str, code: str, line: int, col: int, *body_lines: str) -> Fixture:
    """Fixture sharing the 13-line header; `line` is absolute."""
    return Fixture(
        name=name,
        source=_HEADER + "\n" + "\n".join(body_lines) + "\n",
        code=code,
        line=line,
        col=col,
    )


FIXTURES: list[Fixture] = [
    # --- PS1000 syntax -----------------------------------------------------
    Fixture(
        "syntax-error",
        "from pythsol import u64\nx =\n",
        "PS1000",
        2,
        4,
    ),
    # --- PS1001 imports ----------------------------------------------------
    Fixture("import-module", "import os\n", "PS1001", 1, 1),
    Fixture(
        "import-typing",
        "from typing import Any\n",
        "PS1001",
        1,
        1,
    ),
    Fixture("import-star", "from pythsol import *\n", "PS1001", 1, 21),
    Fixture(
        "import-unknown-export",
        "from pythsol import Nope\n",
        "PS1001",
        1,
        21,
    ),
    Fixture("import-alias", "from pythsol import u64 as N\n", "PS1001", 1, 21),
    Fixture("import-relative", "from . import x\n", "PS1001", 1, 1),
    Fixture("import-random", "import json.tool\n", "PS1001", 1, 1),
    # --- PS1004 dynamic execution -----------------------------------------
    _body_fixture(
        "dunder-import",
        "PS1004",
        14,
        5,
        '    __import__("os")',
    ),
    _body_fixture("eval-call", "PS1004", 14, 5, '    eval("1 + 1")'),
    # --- PS1002 floats -----------------------------------------------------
    _body_fixture("float-literal", "PS1002", 14, 14, "    x: u64 = 1.5"),
    _body_fixture("complex-literal", "PS1002", 14, 14, "    x: u64 = 2j"),
    # --- PS1003 statements/forms ------------------------------------------
    _body_fixture("global-stmt", "PS1003", 14, 5, "    global n"),
    _body_fixture("nested-def", "PS1003", 14, 5, "    def inner() -> None:", "        pass"),
    _body_fixture("assert-stmt", "PS1003", 14, 5, "    assert n < 1"),
    _body_fixture("raise-stmt", "PS1003", 14, 5, "    raise ValueError"),
    _body_fixture("lambda-expr", "PS1003", 14, 9, "    f = lambda: 0"),
    _body_fixture("walrus-expr", "PS1003", 14, 9, "    if (x := 1) > 0:", "        pass"),
    _body_fixture("yield-stmt", "PS1003", 14, 5, "    yield 1"),
    _body_fixture("fstring", "PS1003", 14, 9, '    s = f"{n}"'),
    Fixture(
        "module-level-assign",
        "from pythsol import u64\nx = 1\n",
        "PS1003",
        2,
        1,
    ),
    Fixture(
        "module-level-if",
        "from pythsol import u64\nif True:\n    pass\n",
        "PS1003",
        2,
        1,
    ),
    # --- PS2004 literal containers / strings ------------------------------
    _body_fixture("str-literal", "PS2004", 14, 9, '    s = "hi"'),
    _body_fixture("list-literal", "PS2004", 14, 10, "    xs = [1, 2]"),
    _body_fixture("dict-literal", "PS2004", 14, 10, "    xs = {1: 2}"),
    _body_fixture("tuple-literal", "PS2004", 14, 10, "    xs = (1, 2)"),
    _body_fixture("set-literal", "PS2004", 14, 10, "    xs = {1}"),
    # --- PS1005 signatures -------------------------------------------------
    Fixture(
        "star-args",
        "from pythsol import u64, instruction\n@instruction\ndef f(*a: u64) -> None:\n    pass\n",
        "PS1005",
        3,
        8,
    ),
    Fixture(
        "kwargs",
        "from pythsol import u64, instruction\n@instruction\ndef f(**kw: u64) -> None:\n    pass\n",
        "PS1005",
        3,
        9,
    ),
    Fixture(
        "default-value",
        "from pythsol import u8, instruction\n@instruction\ndef f(x: u8 = 0) -> None:\n    pass\n",
        "PS1005",
        3,
        15,
    ),
    Fixture(
        "kwonly-args",
        "from pythsol import u8, u64, instruction\n@instruction\ndef f(x: u64, *, y: u8) -> None:\n    pass\n",
        "PS1005",
        3,
        18,
    ),
    Fixture(
        "posonly-args",
        "from pythsol import u64, instruction\n@instruction\ndef f(x: u64, /, n: u64) -> None:\n    pass\n",
        "PS1005",
        3,
        7,
    ),
    # --- PS1006 missing annotations ----------------------------------------
    Fixture(
        "missing-param-annotation",
        "from pythsol import Mut, account, instruction\n"
        "@account\nclass Counter:\n    count: u64\n"
        "@instruction\ndef increment(counter: Mut[Counter], missing) -> None:\n    pass\n",
        "PS1006",
        6,
        38,
    ),
    Fixture(
        "missing-return-annotation",
        "from pythsol import u64, instruction\n@instruction\ndef f(x: u64):\n    pass\n",
        "PS1006",
        3,
        1,
    ),
    Fixture(
        "account-field-unannotated",
        "from pythsol import account\n@account\nclass Counter:\n    count = None\n",
        "PS1012",
        4,
        5,
    ),
    # --- PS1007 annotations ------------------------------------------------
    _body_fixture("ann-list", "PS1007", 14, 8, "    x: list[u64]"),
    _body_fixture("ann-any", "PS1007", 14, 8, "    x: Any = 1"),
    _body_fixture("ann-float", "PS1007", 14, 8, "    x: float = 1.0"),
    _body_fixture("ann-str", "PS1007", 14, 8, '    x: str = "hi"'),
    # --- PS2003 int --------------------------------------------------------
    _body_fixture("ann-builtin-int", "PS2003", 14, 8, "    x: int = 1"),
    # --- PS2007 widths/constants ------------------------------------------
    _body_fixture("const-overflow", "PS2007", 14, 13, "    x: u8 = 300"),
    _body_fixture(
        "width-narrow",
        "PS2007",
        15,
        13,
        "    small: u8 = 0",
        "    small = n",
    ),
    # --- PS2005 assignment targets ----------------------------------------
    Fixture(
        "tuple-assign",
        "from pythsol import u8, instruction\n@instruction\ndef f(x: u8) -> None:\n    a, b = 1, 2\n",
        "PS2005",
        4,
        5,
    ),
    # --- PS1008 attribute misuse ------------------------------------------
    _body_fixture(
        "attr-write-int-local",
        "PS1008",
        15,
        5,
        "    x: u8 = 0",
        "    x.flag = 1",
    ),
    _body_fixture("write-signer", "PS1008", 14, 5, "    authority.key = n"),
    # --- PS1009 operators --------------------------------------------------
    _body_fixture("is-operator", "PS1009", 14, 13, "    if n is None:", "        pass"),
    _body_fixture("in-operator", "PS1009", 14, 13, "    if 1 in n:", "        pass"),
    # --- PS1010 calls ------------------------------------------------------
    _body_fixture("print-call", "PS1010", 14, 5, "    print(1)"),
    _body_fixture("unknown-call", "PS1010", 14, 5, "    helper()"),
    _body_fixture(
        "starred-call",
        "PS1005",
        14,
        13,
        "    require(*n)",
    ),
    _body_fixture("keyword-call", "PS1003", 14, 18, "    require(cond=1, err=Err.Unauthorized)"),
    # --- PS1011 comprehensions ---------------------------------------------
    _body_fixture("comprehension", "PS1011", 14, 10, "    xs = [i for i in range(10)]"),
    _body_fixture("generator", "PS1011", 14, 10, "    xs = (i for i in range(10))"),
    # --- PS1012 classes ----------------------------------------------------
    Fixture(
        "class-undecorated",
        "from pythsol import instruction\nclass Counter:\n    count: u64\n",
        "PS1012",
        2,
        1,
    ),
    Fixture(
        "account-on-function",
        "from pythsol import account\ndef broken(:\n    pass\n",
        "PS1000",
        2,
        12,
    ),
    Fixture(
        "account-decorates-function",
        "from pythsol import account\n@account\ndef f(x: u64) -> None:\n    pass\n",
        "PS2008",
        2,
        2,
    ),
    Fixture(
        "error-wrong-base",
        "from pythsol import error\n@error\nclass Err(int):\n    Bad = 1\n",
        "PS1012",
        3,
        11,
    ),
    Fixture(
        "error-member-not-constant",
        "from pythsol import ProgramError, error\n@error\nclass Err(ProgramError):\n    Bad = 2 ** 32\n",
        "PS1012",
        4,
        5,
    ),
    Fixture(
        "error-overflow",
        "from pythsol import ProgramError, error\n@error\nclass Err(ProgramError):\n    Bad = 4294967296\n",
        "PS2007",
        4,
        11,
    ),
    Fixture(
        "account-inherits",
        "from pythsol import account\nclass _D:  # noqa\n    pass\n\n@account\nclass Counter(_D):\n    count: u64\n",
        "PS1012",
        6,
        1,
    ),
    # --- PS2008 decorators -------------------------------------------------
    Fixture(
        "decorator-unimported",
        "from pythsol import u64\n@instruction\ndef f(x: u64) -> None:\n    pass\n",
        "PS2008",
        2,
        2,
    ),
    Fixture(
        "two-decorators",
        "from pythsol import instruction\n@instruction\n@instruction\ndef f(x: u64) -> None:\n    pass\n",
        "PS2008",
        3,
        2,
    ),
    # --- PS2000 / PS2001 names --------------------------------------------
    _body_fixture("assign-undeclared", "PS2000", 14, 5, "    y = 1"),
    _body_fixture("aug-undeclared", "PS2000", 14, 5, "    y += 1"),
    _body_fixture("redeclare-local", "PS2001", 15, 5, "    x: u8 = 0", "    x: u8 = 1"),
    _body_fixture("unknown-name", "PS2001", 14, 13, "    require(nope < 1, Err.Unauthorized)"),
    _body_fixture(
        "unknown-field-read",
        "PS2001",
        14,
        13,
        "    require(counter.ghost < 1, Err.Unauthorized)",
    ),
    _body_fixture("unknown-field-write", "PS2001", 14, 5, "    counter.ghost = 1"),
    _body_fixture("unknown-error-member", "PS2001", 14, 19, "    require(True, Err.Nope)"),
    # --- PS3000/PS3001 semantics ------------------------------------------
    Fixture(
        "read-only-write",
        "from pythsol import Account, account, instruction\n"
        "@account\nclass Counter:\n    count: u64\n\n"
        "@instruction\ndef peek(counter: Account[Counter]) -> None:\n    counter.count = 1\n",
        "PS3001",
        8,
        5,
    ),
    Fixture(
        "bare-account-param",
        "from pythsol import account, instruction\n"
        "@account\nclass Counter:\n    count: u64\n\n"
        "@instruction\ndef f(counter: Counter) -> None:\n    pass\n",
        "PS3001",
        7,
        16,
    ),
    Fixture(
        "collection-param",
        "from pythsol import Vec, account, instruction, u64\n"
        "@instruction\ndef f(items: Vec[u64]) -> None:\n    pass\n",
        "PS3001",
        3,
        14,
    ),
    Fixture(
        "aliasing-mut",
        "from pythsol import Mut, account, instruction\n"
        "@account\nclass Counter:\n    count: u64\n\n"
        "@instruction\ndef dup(a: Mut[Counter], b: Mut[Counter]) -> None:\n    pass\n",
        "PS3000",
        7,
        26,
    ),
    Fixture(
        "duplicate-init",
        "from pythsol import Init, account, instruction\n"
        "@account\nclass Counter:\n    count: u64\n\n"
        "@instruction\ndef a(x: Init[Counter]) -> None:\n    pass\n\n"
        "@instruction\ndef b(x: Init[Counter]) -> None:\n    pass\n",
        "PS3001",
        11,
        10,
    ),
    _body_fixture("require-non-error", "PS3001", 14, 20, "    require(n < 2, 3)"),
    _body_fixture("require-one-arg", "PS3001", 14, 5, "    require(n < 2)"),
    _body_fixture("require-three-args", "PS3001", 14, 5, "    require(True, Err.Unauthorized, 3)"),
    Fixture(
        "wrapper-on-error",
        "from pythsol import Mut, ProgramError, account, error, instruction\n"
        "@account\nclass Counter:\n    count: u64\n\n"
        "@error\nclass Err(ProgramError):\n    Bad = 1\n\n"
        "@instruction\ndef f(c: Mut[Err]) -> None:\n    pass\n",
        "PS3001",
        11,
        14,
    ),
    Fixture(
        "duplicate-class",
        "from pythsol import account\n@account\nclass Counter:\n    count: u64\n\n@account\nclass Counter:\n    other: u64\n",
        "PS2001",
        7,
        1,
    ),
    Fixture(
        "duplicate-instruction",
        "from pythsol import instruction, u64\n"
        "@instruction\ndef f(x: u64) -> None:\n    pass\n\n"
        "@instruction\ndef f(x: u64) -> None:\n    pass\n",
        "PS2001",
        7,
        1,
    ),
    # --- PS2006 type errors ------------------------------------------------
    _body_fixture("if-nonbool", "PS2006", 14, 8, "    if n:", "        pass"),
    _body_fixture("bool-into-int", "PS2006", 15, 9, "    x: u8 = 0", "    x = True"),
    _body_fixture(
        "pubkey-arithmetic",
        "PS2006",
        14,
        13,
        "    require(authority.key + 1, Err.Unauthorized)",
    ),
    _body_fixture(
        "int-lt-pubkey",
        "PS2006",
        14,
        13,
        "    require(counter.count < authority.key, Err.Unauthorized)",
    ),
    _body_fixture(
        "true-division",
        "PS2006",
        14,
        13,
        "    require(counter.count / 2 > 0, Err.Unauthorized)",
    ),
    _body_fixture("return-value", "PS2006", 14, 12, "    return 1"),
    _body_fixture("require-nonbool", "PS2006", 14, 13, "    require(n, Err.Unauthorized)"),
    _body_fixture("len-on-int", "PS2006", 14, 17, "    require(len(n) > 0, Err.Unauthorized)"),
    _body_fixture(
        "index-out-of-range",
        "PS2007",
        15,
        17,
        "    arr: FixedArray[u64, 4]",
        "    require(arr[7] > 0, Err.Unauthorized)",
    ),
    _body_fixture(
        "pubkey-subscript",
        "PS2006",
        14,
        13,
        "    require(authority[0] == authority[0], Err.Unauthorized)",
    ),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fixture_count() -> None:
    assert len(FIXTURES) >= 40


def test_fixture_names_unique() -> None:
    names = [f.name for f in FIXTURES]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f.name for f in FIXTURES])
def test_negative_fixture(fixture: Fixture) -> None:
    diagnostics = front.check_source(fixture.source, file=f"{fixture.name}.py")
    matches = [
        d
        for d in diagnostics
        if d.code == fixture.code and d.line == fixture.line and d.col == fixture.col
    ]
    rendered = "\n".join(d.render() for d in diagnostics)
    assert matches, (
        f"expected {fixture.code} at "
        f"{fixture.name}.py:{fixture.line}:{fixture.col}\n--- diagnostics ---\n{rendered or '(none)'}"
    )
    assert not any(d.code == PS9000 for d in diagnostics), rendered


def test_counter_example_is_clean() -> None:
    source = Path("examples/counter/programs/counter.py").read_text(encoding="utf-8")
    diagnostics = front.check_source(source, file="counter.py")
    assert diagnostics == [], "\n".join(d.render() for d in diagnostics)


def test_export_list_matches_surface() -> None:
    assert set(PYTHSOL_EXPORTS) == set(pythsol.__all__)


def test_diagnostic_rendering() -> None:
    d = Diagnostic("PS1003", "unsupported statement", file="p.py", line=3, col=5)
    assert d.render() == "PS1003 p.py:3:5: unsupported statement"
    assert d.as_dict()["line"] == 3


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _invoke(args: list[str]):
    from click.testing import CliRunner

    from pythsol.cli.main import cli

    return CliRunner().invoke(cli, ["check", *args])


def test_cli_check_clean(tmp_path: Path) -> None:
    target = tmp_path / "counter.py"
    target.write_text(
        Path("examples/counter/programs/counter.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = _invoke([str(target)])
    assert result.exit_code == 0, result.output
    assert "no problems found" in result.output


def test_cli_check_reports_fixture(tmp_path: Path) -> None:
    fixture = FIXTURES[0]
    target = tmp_path / "prog.py"
    target.write_text(fixture.source, encoding="utf-8")
    result = _invoke([str(target)])
    assert result.exit_code == 1
    assert fixture.code in result.output


def test_cli_check_json(tmp_path: Path) -> None:
    import json as _json

    target = tmp_path / "prog.py"
    target.write_text(_HEADER + "\n    y = 1\n", encoding="utf-8")
    result = _invoke(["--json", str(target)])
    assert result.exit_code == 1
    payload = _json.loads(result.output)
    assert payload["ok"] is False
    codes = {d["code"] for d in payload["diagnostics"]}
    assert "PS2000" in codes
    assert all({"code", "file", "line", "col", "message"} <= set(d) for d in payload["diagnostics"])


def test_cli_check_missing_file(tmp_path: Path) -> None:
    result = _invoke([str(tmp_path / "nope.py")])
    assert result.exit_code == 2  # click arg validation


def test_cli_check_json_clean(tmp_path: Path) -> None:
    import json as _json

    target = tmp_path / "counter.py"
    target.write_text(
        Path("examples/counter/programs/counter.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = _invoke(["--json", str(target)])
    assert result.exit_code == 0
    payload = _json.loads(result.output)
    assert payload == {"ok": True, "diagnostics": []}


def test_docstring_program_is_accepted() -> None:
    source = (
        '"""A documented program."""\n'
        + _HEADER
        + '\n    """Instruction docstring."""\n    return\n'
    )
    diagnostics = front.check_source(source, file="docd.py")
    assert diagnostics == [], "\n".join(d.render() for d in diagnostics)


def test_fuzz_never_crashes_smoke() -> None:
    """A crash-prone module-level pattern must fold into diagnostics."""
    weird = "from pythsol import u8\n@instruction\ndef f(x: u8) -> None:\n    return (1,)\n"
    diagnostics = front.check_source(weird, file="w.py")
    codes = {d.code for d in diagnostics}
    assert codes and PS9000 not in codes
