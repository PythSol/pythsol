"""Nested ``@struct`` values: fixed width, inline, no discriminator of their own.

No SBF toolchain. ``tests/fixtures/spot.py`` is the program LiteSVM runs.
A struct field is a defined IDL type. The client decodes it to a dict.
``box.n.value = 1`` on an option still says nested attribute writes.
"""

from __future__ import annotations

import struct
from pathlib import Path

from pythsol.client.gen import render_client
from pythsol.compiler.front import check_source
from pythsol.compiler.idl import build_idl, validate_idl
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
SPOT_PATH = ROOT / "tests" / "fixtures" / "spot.py"
COUNTER = ROOT / "examples" / "counter" / "programs" / "counter.py"


def _messages(source: str) -> list[tuple[str, str]]:
    return [(diag.code, diag.message) for diag in check_source(source, "prog.py")]


def test_spot_layout_idl_client_and_stores() -> None:
    source = SPOT_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, SPOT_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.c_text == emit_program(source, SPOT_PATH).c_text
    text = gen.c_text
    assert "RT_SIZE_SPOT 25u" in text
    assert "RT_OFF_SPOT_ORIGIN 8u" in text
    assert "RT_OFF_SPOT_BUMP 24u" in text
    assert ' (const uint8_t *)"spot", 4u,' in text
    assert "rt_st_u64(acc_spot->data, 8u, 0u);" in text
    assert "rt_st_u64(acc_spot->data, 16u, 0u);" in text
    assert "acc_spot->data[24u] = (uint8_t)(dp_bump);" in text
    assert "rt_st_u64(acc_spot->data, 8u, dp_x);" in text
    assert "rt_st_u64(acc_spot->data, 16u, dp_y);" in text
    assert "rt_ld_u64(acc_spot->data, 8u," in text
    assert "rt_checked_add_u64" in text
    assert "rt_st_u64(acc_spot->data, 8u, rt_t" in text
    assert gen.generated is not None
    spot = gen.generated.account("Spot")
    assert spot is not None and spot.size == 25
    origin = spot.field("origin")
    assert origin is not None
    assert origin.shape == "struct"
    assert origin.defined == "Point"
    assert origin.offset == 0
    assert origin.size == 16
    point = next(item for item in gen.generated.structs if item.name == "Point")
    assert point.size == 16
    assert [(field.name, field.offset) for field in point.fields] == [("x", 0), ("y", 8)]

    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    assert idl["types"] == [
        {
            "name": "Point",
            "type": {
                "kind": "struct",
                "fields": [
                    {"name": "x", "type": "u64"},
                    {"name": "y", "type": "u64"},
                ],
            },
        }
    ]
    fields = {item["name"]: item["type"] for item in idl["accounts"][0]["type"]["fields"]}
    assert fields["origin"] == {"defined": "Point"}
    assert fields["bump"] == "u8"

    client = render_client(gen.generated)
    assert "def _decode_struct_Point(" in client
    assert "import pythsol" not in client
    assert "pythsol.compiler" not in client
    namespace: dict[str, object] = {}
    exec(client, namespace)
    decode = namespace["decode_spot"]
    assert callable(decode)
    raw = bytearray(25)
    raw[8:16] = struct.pack("<Q", 3)
    raw[16:24] = struct.pack("<Q", 4)
    raw[24] = 7
    assert decode(bytes(raw)) == {"origin": {"x": 3, "y": 4}, "bump": 7}


def test_nested_struct_offsets_and_whole_copy() -> None:
    source = """from pythsol import Mut, account, instruction, struct, u8, u64

@struct
class Point:
    x: u64
    y: u64

@struct
class Box:
    origin: Point
    z: u64

@account
class Crate:
    item: Box
    bump: u8

@account
class Seg:
    a: Point
    b: Point
    bump: u8

@instruction
def set_z(crate: Mut[Crate], z: u64) -> None:
    crate.item.origin.x = 7
    crate.item.z = z

@instruction
def mirror(seg: Mut[Seg]) -> None:
    seg.b = seg.a
"""
    gen = emit_program(source, Path("crate.py"))
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.generated is not None
    crate = gen.generated.account("Crate")
    seg = gen.generated.account("Seg")
    assert crate is not None and crate.size == 33
    assert seg is not None and seg.size == 41
    box = next(item for item in gen.generated.structs if item.name == "Box")
    assert [(field.name, field.offset, field.size) for field in box.fields] == [
        ("origin", 0, 16),
        ("z", 16, 8),
    ]
    text = gen.c_text
    assert "rt_st_u64(acc_crate->data, 8u, 7u);" in text
    assert "rt_st_u64(acc_crate->data, 24u, dp_z);" in text
    assert "acc_seg->data[24u + rt_t" in text
    assert "acc_seg->data[8u + rt_t" in text
    assert "< 16u" in text

    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    names = [entry["name"] for entry in idl["types"]]
    assert names == ["Point", "Box"]
    client = render_client(gen.generated)
    namespace: dict[str, object] = {}
    exec(client, namespace)
    decode = namespace["decode_crate"]
    assert callable(decode)
    raw = bytearray(33)
    raw[8:16] = struct.pack("<Q", 7)
    raw[16:24] = struct.pack("<Q", 8)
    raw[24:32] = struct.pack("<Q", 9)
    raw[32] = 1
    assert decode(bytes(raw)) == {
        "item": {"origin": {"x": 7, "y": 8}, "z": 9},
        "bump": 1,
    }


def test_struct_string_and_array_stay_fixed_width() -> None:
    source = """from pythsol import FixedArray, FixedString, Mut, account, instruction, struct, u64

@struct
class Tag:
    name: FixedString[4]
    slots: FixedArray[u64, 2]

@account
class Item:
    tag: Tag
    bump: u64

@instruction
def label(item: Mut[Item], i: u64, amount: u64) -> None:
    item.tag.name = "hi"
    item.tag.slots[i] = amount
"""
    gen = emit_program(source, Path("item.py"))
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.generated is not None
    item = gen.generated.account("Item")
    assert item is not None and item.size == 8 + 4 + 4 + 16 + 8
    text = gen.c_text
    assert "rt_st_u32(acc_item->data, 8u, 2u);" in text
    assert "16u + (" in text
    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    type_names = [entry["name"] for entry in idl["types"]]
    assert type_names == ["Tag", "FixedString4"]
    client = render_client(gen.generated)
    namespace: dict[str, object] = {}
    exec(client, namespace)
    decode = namespace["decode_item"]
    assert callable(decode)
    raw = bytearray(item.size)
    raw[8:12] = struct.pack("<I", 2)
    raw[12:14] = b"hi"
    raw[16:24] = struct.pack("<Q", 5)
    raw[24:32] = struct.pack("<Q", 6)
    decoded = decode(bytes(raw))
    assert decoded["tag"] == {"name": "hi", "slots": [5, 6]}


def test_option_nested_write_message_stays() -> None:
    source = """from pythsol import Mut, Option, account, instruction, struct, u64

@struct
class Point:
    x: u64

@account
class Box:
    n: Option[u64]
    origin: Point

@instruction
def bad(box: Mut[Box]) -> None:
    box.n.value = 1
    box.origin.x = 1
"""
    messages = _messages(source)
    assert any("nested attribute writes" in message for _code, message in messages)
    assert not any("origin" in message and "nested attribute writes" in message for _c, message in messages)


def test_struct_is_not_an_argument_a_local_or_an_account() -> None:
    arg = """from pythsol import instruction, struct, u64

@struct
class Point:
    x: u64

@instruction
def bad(point: Point) -> None:
    return
"""
    assert any(
        code == "PS3001" and "is data, not an instruction argument" in message
        for code, message in _messages(arg)
    )
    local = """from pythsol import Mut, account, instruction, struct, u8, u64

@struct
class Point:
    x: u64

@account
class Spot:
    origin: Point
    bump: u8

@instruction
def bad(spot: Mut[Spot]) -> None:
    here: Point = spot.origin
"""
    assert any(
        code == "PS2006" and "stored in an account field" in message
        for code, message in _messages(local)
    )
    wrapped = """from pythsol import Mut, instruction, struct, u64

@struct
class Point:
    x: u64

@instruction
def bad(point: Mut[Point]) -> None:
    return
"""
    assert any(
        code == "PS3001" and "structs are data, not accounts" in message
        for code, message in _messages(wrapped)
    )
    other = """from pythsol import Mut, account, instruction, struct, u64

@struct
class Point:
    x: u64

@struct
class Pair:
    x: u64

@account
class Spot:
    origin: Point

@instruction
def bad(spot: Mut[Spot]) -> None:
    other: Pair
    spot.origin = other
"""
    # A struct local is rejected before the mismatched assign is interesting.
    # The mismatch itself is the message we want when both sides are fields.
    mismatch = """from pythsol import Mut, account, instruction, struct, u64

@struct
class Point:
    x: u64

@struct
class Pair:
    x: u64

@account
class Spot:
    origin: Point
    extra: Pair

@instruction
def bad(spot: Mut[Spot]) -> None:
    spot.origin = spot.extra
"""
    assert any(
        code == "PS2006" and "cannot assign" in message and "struct `Point`" in message
        for code, message in _messages(mismatch)
    )
    assert any("stored in an account field" in message for _code, message in _messages(other))


def test_struct_cycles_and_empty_are_rejected() -> None:
    loop = """from pythsol import struct, u64

@struct
class Loop:
    inner: Loop
    n: u64
"""
    assert any(
        code == "PS2006" and "refers to itself" in message for code, message in _messages(loop)
    )
    empty = """from pythsol import struct

@struct
class Empty:
    pass
"""
    diags = check_source(empty, "prog.py")
    assert any(diag.code == "PS1012" and "at least one field" in diag.message for diag in diags)
    base = """from pythsol import struct, u64

@struct
class Point:
    x: u64

@struct
class Child(Point):
    y: u64
"""
    assert any(diag.code == "PS1012" for diag in check_source(base, "prog.py"))


def test_counter_lowering_is_unchanged_by_structs() -> None:
    generated = emit_program(COUNTER.read_text(encoding="utf-8"), COUNTER)
    assert generated.ok, "\n".join(item.render() for item in generated.diagnostics)
    assert "do {" not in generated.c_text
    assert generated.generated is not None
    assert generated.generated.structs == []
