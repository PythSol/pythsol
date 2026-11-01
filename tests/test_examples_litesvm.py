"""LiteSVM: the vault and escrow examples move lamports."""

from __future__ import annotations

import importlib.util
import os
import re
import struct
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("solders")
from solders.keypair import Keypair
from solders.litesvm import LiteSVM
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solders.transaction_metadata import FailedTransactionMetadata

from pythsol.client.gen import render_client
from pythsol.compiler.pipeline import emit_program
from pythsol.runtime import RUNTIME_INCLUDE_DIR

PROGRAM_ID = "F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU"
ROOT = Path(__file__).parents[1]
VAULT_PATH = ROOT / "examples" / "vault" / "programs" / "vault.py"
ESCROW_PATH = ROOT / "examples" / "escrow" / "programs" / "escrow.py"
FAUCET_LAMPORTS = 50_000_000
GIFT = 1_000
PRICE = 400


def _tc() -> Any:
    from pythsol.compiler import toolchain
    from pythsol.compiler.diagnostics import PysolError

    try:
        found = toolchain.locate_platform_tools(None)
    except PysolError:
        found = None
    if found is not None:
        return found
    sdk = Path(__file__).parents[1] / "Spikes" / "tools" / "platform-tools-1.58"
    if not sdk.is_dir():
        return None
    os.environ.setdefault("PYTHSOL_SBF_SDK", str(sdk))
    try:
        return toolchain.locate_platform_tools(None)
    except PysolError:
        return None


def _logs(result: Any) -> list[str]:
    try:
        logs = getattr(result, "logs", None)
        if callable(logs):
            logs = logs()
        else:
            meta = getattr(result, "meta", None)
            meta = meta() if callable(meta) else meta
            logs = getattr(meta, "logs", None)
            logs = logs() if callable(logs) else logs
        return [str(entry) for entry in (logs or [])]
    except Exception:
        return []


def _failed(result: Any) -> bool:
    return isinstance(result, FailedTransactionMetadata)


def _custom_code(result: Any) -> int | None:
    err = getattr(result, "err", None)
    if err is None:
        return None
    err = err() if callable(err) else err
    text = str(err)
    digits = re.search(r"Custom\((\d+)\)", text)
    if digits:
        return int(digits.group(1), 10)
    match = re.search(r"custom program error: 0x([0-9a-fA-F]+)", text)
    if match:
        return int(match.group(1), 16)
    return None


def _load_client(tmp: Path, source: str, path: Path, module_name: str) -> Any:
    gen = emit_program(source, path)
    assert gen.ok and gen.generated is not None
    client_path = tmp / f"{module_name}_client.py"
    client_path.write_text(render_client(gen.generated), encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location(module_name, client_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build(tmp: Path, source_path: Path) -> tuple[Path, Any]:
    tc = _tc()
    if tc is None:
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    source = source_path.read_text(encoding="utf-8")
    gen = emit_program(source, source_path)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    c_path = tmp / f"{source_path.stem}.c"
    c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
    from pythsol.compiler import toolchain

    so_path = toolchain.compile_to_sbf(tc, c_path, tmp, include_dirs=(RUNTIME_INCLUDE_DIR,))
    return so_path, _load_client(tmp, source, source_path, source_path.stem)


def _send(svm: Any, payer: Keypair, ix: Any, signers: list[Keypair]) -> Any:
    svm.expire_blockhash()
    blockhash = svm.latest_blockhash()
    msg = Message.new_with_blockhash([ix], payer.pubkey(), blockhash)
    return svm.send_transaction(Transaction(signers, msg, blockhash))


def _lamports(svm: Any, key: Pubkey) -> int:
    account = svm.get_account(key)
    if account is None:
        return 0
    return int(account.lamports)


@pytest.fixture(scope="module")
def vault_example(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    return _build(tmp_path_factory.mktemp("vault_example"), VAULT_PATH)


@pytest.fixture(scope="module")
def escrow_example(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    return _build(tmp_path_factory.mktemp("escrow_example"), ESCROW_PATH)


@pytest.mark.smoke
def test_vault_deposit_and_close(vault_example: tuple[Path, Any]) -> None:
    so_path, client = vault_example
    svm = LiteSVM()
    prog_id = Pubkey.from_string(PROGRAM_ID)
    svm.add_program(prog_id, so_path.read_bytes())
    authority = Keypair()
    svm.airdrop(authority.pubkey(), FAUCET_LAMPORTS)
    pda, bump = Pubkey.find_program_address([b"vault"], prog_id)

    opened = _send(
        svm,
        authority,
        client.initialize(prog_id, authority.pubkey(), pda, bump),
        [authority],
    )
    assert not _failed(opened), _logs(opened)
    data = bytes(svm.get_account(pda).data)
    assert data[8:40] == bytes(authority.pubkey())
    assert struct.unpack_from("<Q", data, 40)[0] == 0
    assert data[48] == bump
    rent = _lamports(svm, pda)

    funded = _send(
        svm,
        authority,
        client.deposit(prog_id, authority.pubkey(), pda, GIFT),
        [authority],
    )
    assert not _failed(funded), _logs(funded)
    data = bytes(svm.get_account(pda).data)
    assert struct.unpack_from("<Q", data, 40)[0] == GIFT
    assert _lamports(svm, pda) == rent + GIFT

    stranger = Keypair()
    svm.airdrop(stranger.pubkey(), FAUCET_LAMPORTS)
    rejected = _send(
        svm,
        stranger,
        client.close(prog_id, stranger.pubkey(), pda),
        [stranger],
    )
    assert _failed(rejected)
    assert _custom_code(rejected) == 6000
    assert _lamports(svm, pda) == rent + GIFT

    before = _lamports(svm, authority.pubkey())
    closed = _send(
        svm,
        authority,
        client.close(prog_id, authority.pubkey(), pda),
        [authority],
    )
    assert not _failed(closed), _logs(closed)
    assert _lamports(svm, pda) == 0
    left = svm.get_account(pda)
    raw = b"" if left is None else bytes(left.data)
    assert raw == b""
    assert _lamports(svm, authority.pubkey()) == before + rent + GIFT - 5_000


@pytest.mark.smoke
def test_escrow_take_and_cancel(escrow_example: tuple[Path, Any]) -> None:
    so_path, client = escrow_example
    svm = LiteSVM()
    prog_id = Pubkey.from_string(PROGRAM_ID)
    svm.add_program(prog_id, so_path.read_bytes())
    maker = Keypair()
    taker = Keypair()
    svm.airdrop(maker.pubkey(), FAUCET_LAMPORTS)
    svm.airdrop(taker.pubkey(), FAUCET_LAMPORTS)
    pda, bump = Pubkey.find_program_address([b"escrow"], prog_id)

    opened = _send(
        svm,
        maker,
        client.make(prog_id, maker.pubkey(), pda, taker.pubkey(), bump, GIFT),
        [maker],
    )
    assert not _failed(opened), _logs(opened)
    data = bytes(svm.get_account(pda).data)
    assert data[8:40] == bytes(maker.pubkey())
    assert data[40:72] == bytes(taker.pubkey())
    assert struct.unpack_from("<Q", data, 72)[0] == GIFT
    assert data[80] == bump
    held = _lamports(svm, pda)
    assert held > GIFT

    rejected = _send(
        svm,
        taker,
        client.cancel(prog_id, taker.pubkey(), pda),
        [taker],
    )
    assert _failed(rejected)
    assert _custom_code(rejected) == 6000
    assert _lamports(svm, pda) == held

    maker_before = _lamports(svm, maker.pubkey())
    taker_before = _lamports(svm, taker.pubkey())
    taken = _send(
        svm,
        taker,
        client.take(prog_id, taker.pubkey(), maker.pubkey(), pda, PRICE),
        [taker, maker],
    )
    assert not _failed(taken), _logs(taken)
    assert _lamports(svm, pda) == 0
    assert _lamports(svm, maker.pubkey()) == maker_before + PRICE
    # Taker pays `price` and the signature fee, and receives the escrowed lamports.
    # Two signers cost 10000 on this LiteSVM; a single signer is 5000.
    got = _lamports(svm, taker.pubkey())
    fee = taker_before + held - PRICE - got
    assert fee in {5_000, 10_000}, fee
