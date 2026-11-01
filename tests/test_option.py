"""Fixed-width Option[T]: tag byte plus the inner value always reserved.

No SBF toolchain. ``tests/fixtures/note.py`` is the program LiteSVM runs.
The IDL type is a defined struct, not Anchor's short ``option`` encoding.
"""

from __future__ import annotations

import struct
from pathlib import Path

from pythsol.client.gen import render_client
from pythsol.compiler.front import check_source
from pythsol.compiler.idl import build_idl, validate_idl
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
NOTE_PATH = ROOT / "tests" / "fixtures" / "note.py"


def _emit(source: str, name: str = "prog.py"):
    return emit_program(source, Path(name))


def _messages(source: str) -> list[tuple[str, str]]:
    return [(diag.code, diag.message) for diag in check_source(source, "prog.py")]


def test_note_layout_idl_and_client() -> None:
    source = NOTE_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, NOTE_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.c_text == emit_program(source, NOTE_PATH).c_text
    text = gen.c_text
    assert "RT_SIZE_NOTE 26u" in text
    assert "RT_OFF_NOTE_AMOUNT 8u" in text
    assert "RT_OFF_NOTE_SEEN 17u" in text
    assert "RT_OFF_NOTE_BUMP 25u" in text
    assert "option is none" in text
    assert "1012u" in text
    assert gen.generated is not None
    note = gen.generated.account("Note")
    assert note is not None and note.size == 26
    amount = note.field("amount")
    assert amount is not None
    assert amount.shape == "option"
    assert amount.c_type == "uint64_t"
    assert amount.size == 9
    assert amount.elem_size == 8
    set_amount = gen.generated.instruction("set_amount")
    assert set_amount is not None
    assert set_amount.data_params[0].shape == "option"
    assert set_amount.data_params[0].size == 9

    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    assert idl["types"] == [
        {
            "name": "OptionU64",
            "type": {
                "kind": "struct",
                "fields": [
                    {"name": "tag", "type": "u8"},
                    {"name": "value", "type": "u64"},
                ],
            },
        }
    ]
    fields = {field["name"]: field["type"] for field in idl["accounts"][0]["type"]["fields"]}
    assert fields["amount"] == {"defined": "OptionU64"}
    assert fields["seen"] == "u64"
    by_name = {instr["name"]: instr for instr in idl["instructions"]}
    assert by_name["set_amount"]["args"] == [
        {"name": "amount", "type": {"defined": "OptionU64"}}
    ]
    assert "option" not in str(fields["amount"])

    client = render_client(gen.generated)
    assert "int | None" in client
    assert "if amount is None" in client
    assert "bytes([0]) + bytes(8)" in client
    assert "import pythsol" not in client
    assert "pythsol.compiler" not in client


def test_client_packs_none_and_zero_differently() -> None:
    solders = __import__("solders.pubkey", fromlist=["Pubkey"])
    source = NOTE_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, NOTE_PATH)
    assert gen.ok and gen.generated is not None
    namespace: dict[str, object] = {}
    exec(render_client(gen.generated), namespace)
    program = solders.Pubkey.from_string("F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU")
    set_amount = namespace["set_amount"]
    assert callable(set_amount)
    decode = namespace["decode_note"]
    assert callable(decode)

    absent = set_amount(program, program, program, None)
    present_zero = set_amount(program, program, program, 0)
    present_five = set_amount(program, program, program, 5)
    absent_data = bytes(absent.data)
    zero_data = bytes(present_zero.data)
    five_data = bytes(present_five.data)
    assert absent_data[-9] == 0
    assert absent_data[-8:] == bytes(8)
    assert zero_data[-9] == 1
    assert zero_data[-8:] == bytes(8)
    assert five_data[-9] == 1
    assert struct.unpack_from("<Q", five_data, len(five_data) - 8) == (5,)

    raw = bytearray(26)
    raw[8] = 1
    raw[9:17] = struct.pack("<Q", 5)
    raw[17:25] = struct.pack("<Q", 9)
    raw[25] = 3
    decoded = decode(bytes(raw))
    assert decoded["amount"] == (1, 5)
    assert decoded["seen"] == 9
    assert decoded["bump"] == 3
    raw[8] = 0
    cleared = decode(bytes(raw))
    assert cleared["amount"] == (0, 5)


def test_option_of_enum_is_a_defined_struct() -> None:
    source = """from pythsol import Init, Mut, Option, Signer, account, enum, instruction, u8

@enum
class Status:
    Open = 0
    Closed = 1

@account
class Gate:
    flag: Option[Status]
    bump: u8

@instruction
def initialize(authority: Signer, gate: Init[Gate], bump: u8) -> None:
    gate.flag = Status.Open
    gate.bump = bump

@instruction
def close(authority: Signer, gate: Mut[Gate]) -> None:
    current: Option[Status] = gate.flag
    match current.value:
        case Status.Open:
            gate.flag = Status.Closed
        case Status.Closed:
            gate.flag = None
"""
    gen = _emit(source, "flag.py")
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.generated is not None
    gate = gen.generated.account("Gate")
    assert gate is not None and gate.size == 11
    flag = gate.field("flag")
    assert flag is not None and flag.shape == "option" and flag.defined == "Status"
    assert flag.size == 2
    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    names = [entry["name"] for entry in idl["types"]]
    assert names == ["Status", "OptionStatus"]
    option = idl["types"][1]["type"]
    assert option["fields"][1]["type"] == {"defined": "Status"}
    assert "1012u" in gen.c_text
    assert "invalid enum tag" in gen.c_text
    assert "v_current_tag" in gen.c_text


def test_option_pubkey_local_and_none() -> None:
    source = """from pythsol import Init, Mut, Option, Pubkey, Signer, account, instruction, u8

@account
class Card:
    who: Option[Pubkey]
    bump: u8

@instruction
def initialize(authority: Signer, card: Init[Card], bump: u8) -> None:
    who: Option[Pubkey] = None
    card.who = who
    card.who = authority.key
    card.bump = bump
"""
    gen = _emit(source, "card.py")
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.generated is not None
    card = gen.generated.account("Card")
    assert card is not None and card.size == 42
    who = card.field("who")
    assert who is not None and who.elem_size == 32 and who.size == 33
    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    assert idl["types"][0]["name"] == "OptionPubkey"
    assert idl["types"][0]["type"]["fields"][1]["type"] == "publicKey"
    assert "v_who_tag" in gen.c_text
    assert "rt_st_key" in gen.c_text


def test_option_i16_argument_loads_with_a_closed_block() -> None:
    source = """from pythsol import Mut, Option, account, instruction, i16

@account
class Box:
    n: Option[i16]

@instruction
def set_n(box: Mut[Box], n: Option[i16]) -> None:
    box.n = n
"""
    gen = _emit(source, "box.py")
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert "int16_t dp_n = 0;" in gen.c_text
    assert "= (int16_t)rt_bits; }" in gen.c_text
    assert gen.generated is not None
    assert gen.generated.instruction("set_n") is not None
    param = gen.generated.instruction("set_n")
    assert param is not None and param.data_params[0].size == 3


def test_none_outside_option_is_rejected() -> None:
    source = """from pythsol import Mut, account, instruction, u64

@account
class Box:
    n: u64

@instruction
def bad(box: Mut[Box]) -> None:
    box.n = None
"""
    messages = _messages(source)
    assert ("PS2006", "`None` is only valid in `return` or `Option[T]`") in messages


def test_bad_option_shapes_and_reads() -> None:
    source = """from pythsol import FixedArray, Mut, Option, Signer, Vec, account, instruction, u64

@account
class Box:
    n: Option[u64]

@instruction
def bad(authority: Signer, box: Mut[Box], items: Vec[u64]) -> None:
    box.n.value = 1
    wide: Option[FixedArray[u64, 2]] = None
    box.n += 1
"""
    messages = _messages(source)
    codes = [code for code, _message in messages]
    assert "PS3001" in codes
    assert any("collections are not instruction arguments" in message for _c, message in messages)
    assert any("nested attribute writes" in message for _c, message in messages)
    assert any("Option[T] needs" in message for _c, message in messages)
    assert any("accumulator" in message for _c, message in messages)


def test_vec_field_stays_unsupported() -> None:
    source = """from pythsol import Init, Signer, Vec, account, instruction, u8, u64

@account
class Box:
    items: Vec[u64]
    bump: u8

@instruction
def initialize(authority: Signer, box: Init[Box], bump: u8) -> None:
    box.bump = bump
"""
    gen = _emit(source, "vec.py")
    assert not gen.ok
    assert any(diag.code == "PS4001" and "Vec[u64]" in diag.message for diag in gen.diagnostics)
