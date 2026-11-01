"""SPL Token, Token-2022, and associated-token CPIs. Counter stays token-free."""

from __future__ import annotations

from pathlib import Path

from pythsol.client.gen import render_client
from pythsol.compiler.front import check_source
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
TOKEN = ROOT / "tests" / "fixtures" / "token_move.py"
COUNTER = ROOT / "examples" / "counter" / "programs" / "counter.py"


def test_token_cpis_lower_and_counter_stays() -> None:
    gen = emit_program(TOKEN.read_text(encoding="utf-8"), TOKEN)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.generated is not None
    send = gen.generated.instruction("send")
    send2022 = gen.generated.instruction("send2022")
    opened = gen.generated.instruction("open_ata")
    assert send is not None and send.needs_token and not send.needs_system
    assert send2022 is not None and send2022.needs_token2022
    assert opened is not None and opened.needs_ata and opened.needs_system and opened.needs_token
    text = gen.c_text
    assert "rt_token_transfer(rt, RT_TOKEN_ID," in text
    assert "rt_token_transfer(rt, RT_TOKEN_2022_ID," in text
    assert "rt_ata_create(" in text
    assert "writable required: src" in text
    assert "RT_DISC_" not in text.split("pyf_send")[1].split("pyf_send2022")[0]
    client = render_client(gen.generated)
    assert "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA" in client
    assert "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb" in client
    assert "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL" in client
    send_fn = client.split("def send(", 1)[1].split("def send2022(", 1)[0]
    assert "_TOKEN_PROGRAM" in send_fn and "_TOKEN_2022_PROGRAM" not in send_fn
    ata_fn = client.split("def open_ata(", 1)[1]
    assert "_ATA_PROGRAM" in ata_fn and "_SYSTEM_PROGRAM" in ata_fn
    assert "AccountMeta(mint, is_signer=False, is_writable=False)" in ata_fn
    assert "AccountMeta(src, is_signer=False, is_writable=True)" in send_fn

    counter = emit_program(COUNTER.read_text(encoding="utf-8"), COUNTER)
    assert counter.ok
    rendered = render_client(counter.generated) if counter.generated is not None else ""
    assert "_TOKEN_PROGRAM" not in rendered
    assert "rt_token_transfer(" not in counter.c_text
    assert "return 0u; /* RT_OK */" in counter.c_text


def test_token_shapes_are_rejected() -> None:
    same = """from pythsol import Signer, TokenAccount, instruction, token_transfer, u64

@instruction
def send(authority: Signer, src: TokenAccount, amount: u64) -> None:
    token_transfer(src, src, authority, amount)
"""
    codes = [(diag.code, diag.message) for diag in check_source(same, "prog.py")]
    assert any("must differ" in message for _code, message in codes)
