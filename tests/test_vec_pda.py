"""Vec[T, N] keeps a fixed slot count. A PDA can sign system_transfer."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pythsol.compiler.idl import build_idl
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
PURSE = ROOT / "tests" / "fixtures" / "purse.py"


def test_capacity_vec_lowers_and_bare_vec_stays_rejected() -> None:
    source = PURSE.read_text(encoding="utf-8")
    generated = emit_program(source, PURSE)
    assert generated.ok, "\n".join(item.render() for item in generated.diagnostics)
    assert generated.generated is not None
    text = generated.c_text
    assert "rt_move_lamports(" in text
    assert "rt_system_transfer(" in text
    assert "rt_st_u32" in text
    idl = build_idl(generated.generated)
    names = [item["name"] for item in idl["types"]]
    assert "VecU644" in names

    bare = """from pythsol import Init, Signer, Vec, account, instruction, u8, u64

@account
class Box:
    items: Vec[u64]
    bump: u8

@instruction
def initialize(authority: Signer, box: Init[Box], bump: u8) -> None:
    box.bump = bump
"""
    rejected = emit_program(bare, Path("vec.py"))
    assert not rejected.ok
    assert any(
        item.code == "PS4001" and "Vec[u64]" in item.message for item in rejected.diagnostics
    )


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
def test_purse_pays_from_the_pda(tmp_path: Path) -> None:
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

    source = PURSE.read_text(encoding="utf-8")
    generated = emit_program(source, PURSE)
    assert generated.ok and generated.generated is not None
    c_path = tmp_path / "purse.c"
    c_path.write_text(generated.c_text, encoding="utf-8", newline="\n")
    tools = toolchain.locate_platform_tools(None)
    assert tools is not None
    so_path = toolchain.compile_to_sbf(
        tools, c_path, tmp_path, include_dirs=(RUNTIME_INCLUDE_DIR,)
    )
    client_path = tmp_path / "purse_client.py"
    client_path.write_text(render_client(generated.generated), encoding="utf-8", newline="\n")
    namespace: dict[str, object] = {}
    exec(client_path.read_text(encoding="utf-8"), namespace)

    program_id = Pubkey.from_string("F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU")
    svm = LiteSVM()
    svm.add_program(program_id, so_path.read_bytes())
    authority = Keypair()
    dest = Keypair()
    svm.airdrop(authority.pubkey(), 50_000_000)
    svm.airdrop(dest.pubkey(), 50_000_000)
    pda, bump = Pubkey.find_program_address([b"purse"], program_id)

    def send(ix: object, signers: list[Keypair]) -> object:
        svm.expire_blockhash()
        blockhash = svm.latest_blockhash()
        message = Message.new_with_blockhash([ix], signers[0].pubkey(), blockhash)
        return svm.send_transaction(Transaction(signers, message, blockhash))

    opened = send(
        namespace["initialize"](program_id, authority.pubkey(), pda, bump),
        [authority],
    )
    assert not isinstance(opened, FailedTransactionMetadata), getattr(opened, "logs", None)
    funded = send(
        namespace["fund"](program_id, authority.pubkey(), pda, 1_000),
        [authority],
    )
    assert not isinstance(funded, FailedTransactionMetadata), getattr(funded, "logs", None)
    before = int(svm.get_account(dest.pubkey()).lamports)
    paid = send(
        namespace["pay"](program_id, authority.pubkey(), pda, dest.pubkey(), 400),
        [authority, dest],
    )
    assert not isinstance(paid, FailedTransactionMetadata), str(paid)
    data = bytes(svm.get_account(pda).data)
    assert struct.unpack_from("<Q", data, 41)[0] == 400
    assert struct.unpack_from("<I", data, 49)[0] == 1
    assert struct.unpack_from("<Q", data, 53)[0] == 400
    after = int(svm.get_account(dest.pubkey()).lamports)
    assert after - before == 400
