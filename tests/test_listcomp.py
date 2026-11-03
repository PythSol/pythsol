"""List comprehensions fill a fixed-size array local at compile time."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
BOARD = ROOT / "tests" / "fixtures" / "listcomp.py"


def test_a_comprehension_lowers_to_a_fixed_array_fill() -> None:
    source = BOARD.read_text(encoding="utf-8")
    generated = emit_program(source, BOARD)
    assert generated.ok, "\n".join(item.render() for item in generated.diagnostics)
    assert generated.generated is not None
    text = generated.c_text
    assert "uint64_t v_values[4] = {0};" in text
    assert "v_values[v_i] = (uint64_t)" in text
    assert "rt_h" in text


def test_a_comprehension_needs_a_constant_length() -> None:
    source = """from pythsol import FixedArray, Mut, Signer, account, instruction, u8, u64

@account
class Box:
    total: u64
    bump: u8

@instruction
def fill(authority: Signer, box: Mut[Box], n: u64) -> None:
    values: FixedArray[u64, 4] = [i for i in range(n)]
    box.total = values[0]
"""
    rejected = emit_program(source, Path("comp.py"))
    assert not rejected.ok
    assert any(item.code == "PS1011" for item in rejected.diagnostics)


def test_a_comprehension_result_cannot_be_assigned_to_a_scalar() -> None:
    source = """from pythsol import Mut, Signer, account, instruction, u8, u64

@account
class Box:
    total: u64
    bump: u8

@instruction
def fill(authority: Signer, box: Mut[Box]) -> None:
    box.total = [i for i in range(4)]
"""
    rejected = emit_program(source, Path("comp.py"))
    assert not rejected.ok
    assert any(item.code == "PS2006" for item in rejected.diagnostics)


def _tools() -> bool:
    from pythsol.compiler import toolchain
    from pythsol.compiler.diagnostics import PysolError

    try:
        found = toolchain.locate_platform_tools(None)
    except PysolError:
        found = None
    if found is not None:
        return True
    sdk = ROOT / "Spikes" / "tools" / "platform-tools-1.58"
    if not sdk.is_dir():
        return False
    os.environ.setdefault("PYTHSOL_SBF_SDK", str(sdk))
    try:
        return toolchain.locate_platform_tools(None) is not None
    except PysolError:
        return False


@pytest.mark.toolchain
def test_a_comprehension_runs_in_litesvm(tmp_path: Path) -> None:
    pytest.importorskip("solders")
    if not _tools():
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    import struct

    from solders.keypair import Keypair
    from solders.litesvm import LiteSVM
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction
    from solders.transaction_metadata import FailedTransactionMetadata

    from pythsol.client.gen import render_client
    from pythsol.compiler import toolchain
    from pythsol.runtime import RUNTIME_INCLUDE_DIR

    source = BOARD.read_text(encoding="utf-8")
    generated = emit_program(source, BOARD)
    assert generated.ok and generated.generated is not None
    c_path = tmp_path / "board.c"
    c_path.write_text(generated.c_text, encoding="utf-8", newline="\n")
    tools = toolchain.locate_platform_tools(None)
    assert tools is not None
    so_path = toolchain.compile_to_sbf(
        tools, c_path, tmp_path, include_dirs=(RUNTIME_INCLUDE_DIR,)
    )
    client_path = tmp_path / "board_client.py"
    client_path.write_text(render_client(generated.generated), encoding="utf-8", newline="\n")
    namespace: dict[str, object] = {}
    exec(client_path.read_text(encoding="utf-8"), namespace)

    program_id = Pubkey.from_string("F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU")
    svm = LiteSVM()
    svm.add_program(program_id, so_path.read_bytes())
    authority = Keypair()
    svm.airdrop(authority.pubkey(), 50_000_000)
    board, bump = Pubkey.find_program_address([b"board"], program_id)

    def send(ix: object) -> object:
        svm.expire_blockhash()
        blockhash = svm.latest_blockhash()
        message = Message.new_with_blockhash([ix], authority.pubkey(), blockhash)
        return svm.send_transaction(Transaction([authority], message, blockhash))

    opened = send(namespace["initialize"](program_id, authority.pubkey(), board, bump))
    assert not isinstance(opened, FailedTransactionMetadata), getattr(opened, "logs", None)
    filled = send(namespace["fill"](program_id, authority.pubkey(), board, 10))
    assert not isinstance(filled, FailedTransactionMetadata), str(filled)

    data = bytes(svm.get_account(board).data)
    assert struct.unpack_from("<4Q", data, 40) == (10, 11, 12, 13)
    assert struct.unpack_from("<Q", data, 72)[0] == 46
