"""Unit enums: one-byte tags, match, IDL, and the solders client.

No SBF toolchain. ``tests/fixtures/gate.py`` is the program LiteSVM runs.
"""

from __future__ import annotations

from pathlib import Path

from pythsol.client.gen import render_client
from pythsol.compiler.front import check_source
from pythsol.compiler.idl import build_idl, validate_idl
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
GATE_PATH = ROOT / "tests" / "fixtures" / "gate.py"


def _emit(source: str, name: str = "prog.py"):
    return emit_program(source, Path(name))


def _messages(source: str) -> list[tuple[str, str]]:
    return [(diag.code, diag.message) for diag in check_source(source, "prog.py")]


def test_gate_lowers_enum_field_argument_and_match() -> None:
    source = GATE_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, GATE_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.c_text == emit_program(source, GATE_PATH).c_text
    text = gen.c_text
    assert "RT_SIZE_GATE 10u" in text
    assert "RT_OFF_GATE_STATUS 8u" in text
    assert "invalid enum tag" in text
    assert "1011u" in text
    assert gen.generated is not None
    gate = gen.generated.account("Gate")
    assert gate is not None and gate.size == 10
    status = gate.field("status")
    assert status is not None
    assert status.c_type == "uint8_t" and status.size == 1 and status.defined == "Status"
    apply = gen.generated.instruction("apply")
    assert apply is not None
    assert apply.data_params[0].name == "status"
    assert apply.data_params[0].c_type == "uint8_t"
    assert apply.data_params[0].defined == "Status"
    assert gen.generated.enums[0].variants == [("Open", 0), ("Closed", 1)]

    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    assert idl["types"] == [
        {
            "name": "Status",
            "type": {"kind": "enum", "variants": [{"name": "Open"}, {"name": "Closed"}]},
        }
    ]
    account = idl["accounts"][0]
    fields = {field["name"]: field["type"] for field in account["type"]["fields"]}
    assert fields["status"] == {"defined": "Status"}
    assert fields["bump"] == "u8"
    by_name = {instr["name"]: instr for instr in idl["instructions"]}
    assert by_name["apply"]["args"] == [{"name": "status", "type": {"defined": "Status"}}]

    client = render_client(gen.generated)
    assert "STATUS_OPEN = 0  # Status.Open" in client
    assert "STATUS_CLOSED = 1  # Status.Closed" in client
    assert 'struct.pack("<B", status)' in client
    assert "import pythsol" not in client
    assert "pythsol.compiler" not in client


def test_fixed_array_of_enum_is_packed_bytes() -> None:
    source = """from pythsol import FixedArray, Init, Mut, Signer, account, enum, instruction, u8

@enum
class Status:
    Open = 0
    Closed = 1

@account
class Bag:
    flags: FixedArray[Status, 2]
    bump: u8

@instruction
def initialize(authority: Signer, bag: Init[Bag], bump: u8) -> None:
    bag.flags[0] = Status.Open
    bag.flags[1] = Status.Closed
    bag.bump = bump

@instruction
def close_first(authority: Signer, bag: Mut[Bag]) -> None:
    match bag.flags[0]:
        case Status.Open:
            bag.flags[0] = Status.Closed
        case Status.Closed:
            bag.flags[0] = Status.Closed
"""
    gen = _emit(source, "bag.py")
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.generated is not None
    bag = gen.generated.account("Bag")
    assert bag is not None and bag.size == 11
    flags = bag.field("flags")
    assert flags is not None and flags.shape == "array" and flags.defined == "Status"
    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    field = next(item for item in idl["accounts"][0]["type"]["fields"] if item["name"] == "flags")
    assert field["type"] == {"array": [{"defined": "Status"}, 2]}
    assert "invalid enum tag" in gen.c_text


def test_enum_local_and_if_expression() -> None:
    source = """from pythsol import Init, Signer, account, enum, instruction, u8

@enum
class Status:
    Open = 0
    Closed = 1

@account
class Gate:
    status: Status
    bump: u8

@instruction
def initialize(authority: Signer, gate: Init[Gate], bump: u8, closed: bool) -> None:
    current: Status = Status.Open if not closed else Status.Closed
    gate.status = current
    gate.bump = bump
"""
    gen = _emit(source)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert "uint8_t v_current" in gen.c_text


def test_wildcard_match_accepts_every_tag() -> None:
    source = """from pythsol import Mut, Signer, account, enum, instruction

@enum
class Status:
    Open = 0
    Closed = 1

@account
class Gate:
    status: Status

@instruction
def shut(authority: Signer, gate: Mut[Gate], status: Status) -> None:
    match status:
        case Status.Open:
            gate.status = Status.Open
        case _:
            gate.status = Status.Closed
"""
    gen = _emit(source)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert "invalid enum tag" not in gen.c_text


def test_bad_enum_shapes_and_tags() -> None:
    empty = "from pythsol import enum\n@enum\nclass Status:\n    pass\n"
    assert any(code == "PS1012" and "at least one variant" in msg for code, msg in _messages(empty))

    shifted = "from pythsol import enum\n@enum\nclass Status:\n    Open = 1\n    Closed = 2\n"
    assert any(code == "PS2007" and "must be tag 0" in msg for code, msg in _messages(shifted))

    payload = "from pythsol import enum, Pubkey\n@enum\nclass Status:\n    Open: Pubkey\n"
    assert any(code == "PS2007" and "payload" in msg for code, msg in _messages(payload))

    base = "from pythsol import ProgramError, enum\n@enum\nclass Status(ProgramError):\n    Open = 0\n"
    assert any(code == "PS1012" for code, _msg in _messages(base))

    missing_import = "from pythsol import u8\n@enum\nclass Status:\n    Open = 0\n"
    assert any(code == "PS2008" for code, _msg in _messages(missing_import))

    shadow = "from pythsol import enum\n@enum\nclass u8:\n    A = 0\n"
    assert any(code == "PS2001" and "shadows" in msg for code, msg in _messages(shadow))


def test_enum_values_do_not_mix_with_integers_or_other_enums() -> None:
    source = """from pythsol import Mut, Signer, account, enum, instruction, u8

@enum
class Status:
    Open = 0
    Closed = 1

@enum
class Color:
    Red = 0
    Blue = 1

@account
class Gate:
    status: Status
    bump: u8

@instruction
def set_raw(authority: Signer, gate: Mut[Gate]) -> None:
    gate.status = 1

@instruction
def set_other(authority: Signer, gate: Mut[Gate]) -> None:
    gate.status = Color.Red

@instruction
def compare(authority: Signer, gate: Mut[Gate]) -> None:
    if gate.status == 0:
        gate.bump = 1
    if gate.status < Status.Open:
        gate.bump = 2
"""
    found = _messages(source)
    assert any(code == "PS2006" and "to enum `Status`" in msg for code, msg in found)
    assert any(code == "PS2006" and "Color.Red" in msg for code, msg in found)
    assert any(code == "PS2006" and "cannot compare" in msg for code, msg in found)
    assert any(code == "PS2006" and "only `==` and `!=`" in msg for code, msg in found)


def test_match_must_be_exhaustive_and_unguarded() -> None:
    partial = """from pythsol import Mut, Signer, account, enum, instruction

@enum
class Status:
    Open = 0
    Closed = 1

@account
class Gate:
    status: Status

@instruction
def half(authority: Signer, gate: Mut[Gate], status: Status) -> None:
    match status:
        case Status.Open:
            gate.status = Status.Open
"""
    assert any(
        code == "PS2006" and "not exhaustive" in msg and "Closed" in msg
        for code, msg in _messages(partial)
    )

    guarded = """from pythsol import Mut, Signer, account, enum, instruction

@enum
class Status:
    Open = 0
    Closed = 1

@account
class Gate:
    status: Status

@instruction
def guarded(authority: Signer, gate: Mut[Gate], status: Status) -> None:
    match status:
        case Status.Open if status == Status.Open:
            gate.status = Status.Open
        case _:
            gate.status = Status.Closed
"""
    assert any(code == "PS1003" and "guards" in msg for code, msg in _messages(guarded))

    dup = """from pythsol import Mut, Signer, account, enum, instruction

@enum
class Status:
    Open = 0
    Closed = 1

@enum
class Color:
    Red = 0

@account
class Gate:
    status: Status

@instruction
def messy(authority: Signer, gate: Mut[Gate], status: Status) -> None:
    match status:
        case Status.Open:
            gate.status = Status.Open
        case Status.Open:
            gate.status = Status.Closed
        case Status.Nope:
            gate.status = Status.Closed
        case Color.Red:
            gate.status = Status.Closed
"""
    found = _messages(dup)
    assert any(code == "PS2006" and "already matched" in msg for code, msg in found)
    assert any(code == "PS2001" and "no variant" in msg for code, msg in found)
    assert any(code == "PS2006" and "not a variant of `Status`" in msg for code, msg in found)
