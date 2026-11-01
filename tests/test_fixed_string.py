"""Fixed-width FixedString[N]: a u32 byte length plus N reserved bytes.

No SBF toolchain. ``tests/fixtures/label.py`` is the program LiteSVM runs.
The IDL type is a defined struct, not Anchor's short ``string`` encoding.
``s = "hi"`` stays PS2004: a literal is only the direct right-hand side of an
attribute store or a ``FixedString[N]`` annotation.
"""

from __future__ import annotations

import struct
from pathlib import Path

from pythsol.client.gen import render_client
from pythsol.compiler.front import check_source
from pythsol.compiler.idl import build_idl, validate_idl
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
LABEL_PATH = ROOT / "tests" / "fixtures" / "label.py"


def _emit(source: str, name: str = "prog.py"):
    return emit_program(source, Path(name))


def _messages(source: str) -> list[tuple[str, str]]:
    return [(diag.code, diag.message) for diag in check_source(source, "prog.py")]


def test_label_layout_idl_and_client() -> None:
    source = LABEL_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, LABEL_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.c_text == emit_program(source, LABEL_PATH).c_text
    text = gen.c_text
    assert "RT_SIZE_LABEL 29u" in text
    assert "RT_OFF_LABEL_TEXT 8u" in text
    assert "RT_OFF_LABEL_NCHARS 20u" in text
    assert "RT_OFF_LABEL_BUMP 28u" in text
    assert "rt_st_u32(acc_label->data, 8u, 2u);" in text
    assert "104u, 105u" in text
    assert "uint32_t dp_text_len" in text
    assert "uint8_t v_note[8]" in text
    assert "1013u" in text
    assert "FixedString length is past its reserved bytes" in text
    assert "uint8_t rt_" in text and "{104u, 105u}" in text
    assert gen.generated is not None
    label = gen.generated.account("Label")
    assert label is not None and label.size == 29
    field = label.field("text")
    assert field is not None
    assert field.shape == "string"
    assert field.length == 8
    assert field.size == 12
    assert field.offset == 0
    set_text = gen.generated.instruction("set_text")
    assert set_text is not None
    assert set_text.data_params[0].shape == "string"
    assert set_text.data_params[0].length == 8
    assert set_text.data_params[0].size == 12

    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    assert idl["types"] == [
        {
            "name": "FixedString8",
            "type": {
                "kind": "struct",
                "fields": [
                    {"name": "len", "type": "u32"},
                    {"name": "data", "type": {"array": ["u8", 8]}},
                ],
            },
        }
    ]
    fields = {item["name"]: item["type"] for item in idl["accounts"][0]["type"]["fields"]}
    assert fields["text"] == {"defined": "FixedString8"}
    assert "string" not in str(fields["text"])
    by_name = {instr["name"]: instr for instr in idl["instructions"]}
    assert by_name["set_text"]["args"] == [
        {"name": "text", "type": {"defined": "FixedString8"}}
    ]

    client = render_client(gen.generated)
    assert "text: str" in client
    assert "def _pack_fixed_str(" in client
    assert "import pythsol" not in client
    assert "pythsol.compiler" not in client


def test_client_packs_length_and_rejects_a_long_string() -> None:
    solders = __import__("solders.pubkey", fromlist=["Pubkey"])
    source = LABEL_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, LABEL_PATH)
    assert gen.ok and gen.generated is not None
    namespace: dict[str, object] = {}
    exec(render_client(gen.generated), namespace)
    program = solders.Pubkey.from_string("F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU")
    set_text = namespace["set_text"]
    decode = namespace["decode_label"]
    assert callable(set_text) and callable(decode)

    hi = bytes(set_text(program, program, program, "hi").data)
    empty = bytes(set_text(program, program, program, "").data)
    accent = bytes(set_text(program, program, program, "é").data)
    assert hi[-12:] == struct.pack("<I", 2) + b"hi" + bytes(6)
    assert empty[-12:] == struct.pack("<I", 0) + bytes(8)
    assert accent[-12:] == struct.pack("<I", 2) + "é".encode() + bytes(6)
    try:
        set_text(program, program, program, "123456789")
    except ValueError as err:
        assert "FixedString[8]" in str(err)
    else:
        raise AssertionError("a 9-byte string must be rejected before it is sent")

    raw = bytearray(29)
    raw[8:12] = struct.pack("<I", 2)
    raw[12:14] = b"hi"
    raw[20:28] = struct.pack("<Q", 2)
    raw[28] = 4
    decoded = decode(bytes(raw))
    assert decoded["text"] == "hi"
    assert decoded["nchars"] == 2
    assert decoded["bump"] == 4
    raw[8:12] = struct.pack("<I", 9)
    try:
        decode(bytes(raw))
    except ValueError as err:
        assert "longer than 8" in str(err)
    else:
        raise AssertionError("a stored length past N must not decode")


def test_string_literal_rules_stay_put() -> None:
    bare = """from pythsol import Mut, account, instruction, u64

@account
class Box:
    n: u64

@instruction
def bad(box: Mut[Box]) -> None:
    s = "hi"
"""
    bare_diags = check_source(bare, "prog.py")
    assert any(
        diag.code == "PS2004" and diag.line == 9 and diag.col == 9 for diag in bare_diags
    )
    assert any("string literals are not part of the program surface" in diag.message for diag in bare_diags)

    reassign = """from pythsol import FixedString, Mut, account, instruction, u64

@account
class Box:
    n: u64

@instruction
def bad(box: Mut[Box]) -> None:
    note: FixedString[8] = "hi"
    note = "bye"
"""
    messages = _messages(reassign)
    assert ("PS2004", "string literals are not part of the program surface") in messages
    assert not any(code == "PS2007" for code, _message in messages)

    too_long = """from pythsol import FixedString, Mut, account, instruction, u8

@account
class Box:
    text: FixedString[4]
    bump: u8

@instruction
def bad(box: Mut[Box]) -> None:
    box.text = "hello"
"""
    messages = _messages(too_long)
    assert any(
        code == "PS2007" and "string is 5 bytes" in message and "FixedString[4]" in message
        for code, message in messages
    )

    mismatch = """from pythsol import FixedString, Mut, account, instruction, u64

@account
class Box:
    n: u64

@instruction
def bad(box: Mut[Box]) -> None:
    wide: FixedString[8] = "hi"
    short: FixedString[4] = wide
"""
    messages = _messages(mismatch)
    assert any(code == "PS2006" and "fixed string" in message for code, message in messages)

    outside = """from pythsol import FixedString, Mut, account, instruction, u64

@account
class Box:
    text: FixedString[8]

@instruction
def bad(box: Mut[Box]) -> None:
    box.text[8] = 1
    box.text += 1
"""
    messages = _messages(outside)
    assert any(code == "PS2007" and "outside 0..7" in message for code, message in messages)
    assert any("accumulator" in message for _code, message in messages)


def test_option_struct_is_listed_before_the_string_struct() -> None:
    source = """from pythsol import FixedString, Init, Option, Signer, account, instruction, u8, u64

@account
class Box:
    name: FixedString[4]
    note: Option[u64]
    bump: u8

@instruction
def initialize(authority: Signer, box: Init[Box], bump: u8) -> None:
    box.name = "ab"
    box.note = None
    box.bump = bump
"""
    gen = _emit(source, "box.py")
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.generated is not None
    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    assert [entry["name"] for entry in idl["types"]] == ["OptionU64", "FixedString4"]


def test_string_type_name_cannot_reuse_an_account() -> None:
    source = """from pythsol import FixedString, Init, Signer, account, instruction, u8

@account
class FixedString4:
    n: u8

@account
class Box:
    name: FixedString[4]
    bump: u8

@instruction
def initialize(authority: Signer, box: Init[Box], bump: u8) -> None:
    box.bump = bump
"""
    gen = _emit(source, "clash.py")
    assert not gen.ok
    assert any(
        diag.code == "PS4001" and "FixedString4" in diag.message for diag in gen.diagnostics
    )
