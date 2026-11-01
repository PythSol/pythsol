"""A data enum is a tag plus one reserved scalar. Later fields do not move."""

from __future__ import annotations

from pythsol.compiler.idl import build_idl
from pythsol.compiler.pipeline import emit_program

SOURCE = """from pythsol import Init, Mut, Signer, account, enum, instruction, u64, u8

@enum
class Trade:
    Open = 0
    Fill: u64

@account
class Book:
    trade: Trade
    bump: u8

@instruction
def initialize(authority: Signer, book: Init[Book], bump: u8) -> None:
    book.trade = Trade.Open
    book.bump = bump

@instruction
def fill(authority: Signer, book: Mut[Book], amount: u64) -> None:
    book.trade = Trade.Fill
    book.trade.value = amount
"""


def test_data_enum_reserves_the_payload_and_keeps_the_next_field() -> None:
    generated = emit_program(SOURCE, "book.py")
    assert generated.ok, "\n".join(item.render() for item in generated.diagnostics)
    assert generated.generated is not None
    book = generated.generated.account("Book")
    assert book is not None
    trade = book.field("trade")
    bump = book.field("bump")
    assert trade is not None and bump is not None
    assert trade.size == 9
    assert bump.offset == trade.offset + 9
    assert "rt_fail_log(1011u" in generated.c_text
    idl = build_idl(generated.generated)
    variants = next(item for item in idl["types"] if item["name"] == "Trade")
    assert variants["type"]["variants"][0] == {"name": "Open"}
    assert variants["type"]["variants"][1]["fields"] == [{"name": "value", "type": "u64"}]
