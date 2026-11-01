"""Plain helper functions: typed, non-recursive, inlined into the instruction.

Helpers are not instructions. They do not get a discriminator, an IDL entry,
or a dispatch row. Checked math inside a helper still aborts the instruction.
"""

from __future__ import annotations

from pathlib import Path

from pythsol.compiler.front import check_source
from pythsol.compiler.idl import build_idl
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
COUNTER = ROOT / "examples" / "counter" / "programs" / "counter.py"

_HEADER = "from pythsol import Init, Mut, Signer, account, instruction, u8, u64\n"


def _account() -> str:
    return (
        "@account\n"
        "class Counter:\n"
        "    count: u64\n"
        "    bump: u8\n"
    )


def _program(body: str) -> str:
    return _HEADER + "\n" + _account() + "\n" + body


def _codes(source: str) -> set[str]:
    return {item.code for item in check_source(source, file="helper.py")}


def test_counter_lowering_has_no_helper_block() -> None:
    generated = emit_program(COUNTER.read_text(encoding="utf-8"), COUNTER)
    assert generated.ok, "\n".join(item.render() for item in generated.diagnostics)
    assert "do {" not in generated.c_text
    assert "while (0)" not in generated.c_text


def test_helper_is_inlined_and_is_not_an_instruction() -> None:
    source = _program(
        "def fee(amount: u64) -> u64:\n"
        "    extra: u64 = 1\n"
        "    return amount + extra\n"
        "\n"
        "@instruction\n"
        "def initialize(payer: Signer, counter: Init[Counter], bump: u8) -> None:\n"
        "    counter.count = 0\n"
        "\n"
        "@instruction\n"
        "def apply(counter: Mut[Counter], by: u64) -> None:\n"
        "    counter.count = fee(by)\n"
    )
    generated = emit_program(source, Path("fee.py"))
    assert generated.ok, "\n".join(item.render() for item in generated.diagnostics)
    text = generated.c_text
    assert "do {" in text
    assert "} while (0);" in text
    assert "rt_checked_add_u64" in text
    assert "v_extra" in text
    assert "pyf_fee" not in text
    assert "pyf_apply" in text
    assert generated.generated is not None
    idl = build_idl(generated.generated)
    assert {item["name"] for item in idl["instructions"]} == {"initialize", "apply"}


def test_helper_defined_after_the_call_is_visible() -> None:
    source = _program(
        "@instruction\n"
        "def apply(counter: Mut[Counter], by: u64) -> None:\n"
        "    counter.count = fee(by)\n"
        "\n"
        "def fee(amount: u64) -> u64:\n"
        "    return amount + 1\n"
    )
    generated = emit_program(source, Path("later.py"))
    assert generated.ok, "\n".join(item.render() for item in generated.diagnostics)
    assert text_has_one_dispatch_helper(generated.c_text)


def text_has_one_dispatch_helper(text: str) -> bool:
    assert "do {" in text
    assert "pyf_fee" not in text
    return True


def test_account_argument_is_the_caller_account() -> None:
    source = _program(
        "def add_one(counter: Mut[Counter]) -> None:\n"
        "    counter.count = counter.count + 1\n"
        "\n"
        "@instruction\n"
        "def initialize(payer: Signer, counter: Init[Counter], bump: u8) -> None:\n"
        "    counter.count = 0\n"
        "\n"
        "@instruction\n"
        "def inc(counter: Mut[Counter]) -> None:\n"
        "    add_one(counter)\n"
    )
    generated = emit_program(source, Path("add.py"))
    assert generated.ok, "\n".join(item.render() for item in generated.diagnostics)
    text = generated.c_text
    assert "pyf_add_one" not in text
    assert "do {" in text
    assert "acc_counter" in text
    assert "rt_checked_add_u64" in text


def test_nested_helpers_inline_inside_each_other() -> None:
    source = _program(
        "def inc(n: u64) -> u64:\n"
        "    return n + 1\n"
        "\n"
        "def fee(n: u64) -> u64:\n"
        "    return inc(n)\n"
        "\n"
        "@instruction\n"
        "def apply(counter: Mut[Counter], by: u64) -> None:\n"
        "    counter.count = fee(by)\n"
    )
    generated = emit_program(source, Path("nest.py"))
    assert generated.ok, "\n".join(item.render() for item in generated.diagnostics)
    assert generated.c_text.count("do {") == 2
    assert "pyf_inc" not in generated.c_text
    assert "pyf_fee" not in generated.c_text


def test_readonly_account_cannot_fill_a_mut_parameter() -> None:
    source = (
        "from pythsol import Account, Mut, account, instruction, u64\n"
        "\n"
        "@account\n"
        "class Counter:\n"
        "    count: u64\n"
        "\n"
        "def touch(counter: Mut[Counter]) -> None:\n"
        "    counter.count = 1\n"
        "\n"
        "@instruction\n"
        "def bad(counter: Account[Counter]) -> None:\n"
        "    touch(counter)\n"
    )
    diagnostics = check_source(source, file="ro.py")
    assert any(item.code == "PS3001" for item in diagnostics)


def test_helper_cannot_init_or_take_an_option() -> None:
    init = _program(
        "def make(counter: Init[Counter], bump: u8) -> None:\n"
        "    counter.count = 0\n"
    )
    assert "PS3001" in _codes(init)
    option = (
        "from pythsol import Option, instruction, u64\n"
        "\n"
        "def nope(amount: Option[u64]) -> None:\n"
        "    pass\n"
        "\n"
        "@instruction\n"
        "def go(amount: u64) -> None:\n"
        "    pass\n"
    )
    assert "PS2006" in _codes(option)


def test_recursion_and_a_long_chain_are_rejected() -> None:
    direct = _program(
        "def loop(n: u64) -> u64:\n"
        "    return loop(n)\n"
        "\n"
        "@instruction\n"
        "def apply(counter: Mut[Counter], by: u64) -> None:\n"
        "    counter.count = loop(by)\n"
    )
    assert any(item.code == "PS2006" and "recurses" in item.message for item in check_source(direct))
    mutual = _program(
        "def left(n: u64) -> u64:\n"
        "    return right(n)\n"
        "\n"
        "def right(n: u64) -> u64:\n"
        "    return left(n)\n"
        "\n"
        "@instruction\n"
        "def apply(counter: Mut[Counter], by: u64) -> None:\n"
        "    counter.count = left(by)\n"
    )
    assert "PS2006" in _codes(mutual)

    deep = _program(_chain(9) + "\n@instruction\ndef apply(counter: Mut[Counter], by: u64) -> None:\n    counter.count = h0(by)\n")
    assert any("depth" in item.message for item in check_source(deep, file="deep.py"))
    shallow = _program(
        _chain(8) + "\n@instruction\ndef apply(counter: Mut[Counter], by: u64) -> None:\n    counter.count = h0(by)\n"
    )
    generated = emit_program(shallow, Path("shallow.py"))
    assert generated.ok, "\n".join(item.render() for item in generated.diagnostics)


def _chain(count: int) -> str:
    lines: list[str] = []
    for index in range(count):
        if index + 1 < count:
            lines.append(f"def h{index}(n: u64) -> u64:\n    return h{index + 1}(n)\n")
        else:
            lines.append(f"def h{index}(n: u64) -> u64:\n    return n\n")
    return "\n".join(lines)


def test_helper_cannot_see_a_caller_local_or_hide_len() -> None:
    closed = _program(
        "def fee(amount: u64) -> u64:\n"
        "    return amount + extra\n"
        "\n"
        "@instruction\n"
        "def apply(counter: Mut[Counter], by: u64) -> None:\n"
        "    extra: u64 = 1\n"
        "    counter.count = fee(by)\n"
    )
    assert "PS2001" in _codes(closed)
    hidden = _program(
        "def len(n: u64) -> u64:\n"
        "    return n\n"
    )
    assert any(
        item.code == "PS2001" and "hides a built-in" in item.message
        for item in check_source(hidden, file="len.py")
    )


def test_void_helper_is_a_statement_and_not_a_value() -> None:
    source = _program(
        "def touch(counter: Mut[Counter]) -> None:\n"
        "    counter.count = 1\n"
        "\n"
        "@instruction\n"
        "def inc(counter: Mut[Counter]) -> None:\n"
        "    touch(counter)\n"
    )
    generated = emit_program(source, Path("void.py"))
    assert generated.ok, "\n".join(item.render() for item in generated.diagnostics)
    value = _program(
        "def touch(counter: Mut[Counter]) -> None:\n"
        "    counter.count = 1\n"
        "\n"
        "@instruction\n"
        "def bad(counter: Mut[Counter]) -> None:\n"
        "    counter.count = touch(counter)\n"
    )
    assert "PS2006" in _codes(value)
