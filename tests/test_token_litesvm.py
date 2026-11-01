"""LiteSVM: token_transfer moves tokens and ata_create opens an associated account."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("solders")
pytest.importorskip("spl.token")
from solders.keypair import Keypair
from solders.litesvm import LiteSVM
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import CreateAccountParams, create_account
from solders.transaction import Transaction
from solders.transaction_metadata import FailedTransactionMetadata
from spl.token.constants import (
    ACCOUNT_LEN,
    MINT_LEN,
    TOKEN_2022_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
)
from spl.token.instructions import (
    get_associated_token_address,
    initialize_account3,
    initialize_mint2,
    mint_to,
)
from spl.token.models import InitializeAccount3Params, InitializeMint2Params, MintToParams

from pythsol.client.gen import render_client
from pythsol.compiler.pipeline import emit_program
from pythsol.runtime import RUNTIME_INCLUDE_DIR

PROGRAM_ID = "F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU"
TOKEN_PATH = Path(__file__).parent / "fixtures" / "token_move.py"
FAUCET_LAMPORTS = 50_000_000
SUPPLY = 1_000
GIFT = 40


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


def _load_client(tmp: Path, source: str) -> Any:
    gen = emit_program(source, TOKEN_PATH)
    assert gen.ok and gen.generated is not None
    path = tmp / "token_client.py"
    path.write_text(render_client(gen.generated), encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location("token_client_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def token_build(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    tc = _tc()
    if tc is None:
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    source = TOKEN_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, TOKEN_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    out = tmp_path_factory.mktemp("token_build")
    c_path = out / "token_move.c"
    c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
    from pythsol.compiler import toolchain

    so_path = toolchain.compile_to_sbf(tc, c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,))
    return so_path, _load_client(out, source)


def _submit(svm: Any, payer: Keypair, ixs: list[Any], signers: list[Keypair]) -> None:
    svm.expire_blockhash()
    blockhash = svm.latest_blockhash()
    msg = Message.new_with_blockhash(ixs, payer.pubkey(), blockhash)
    result = svm.send_transaction(Transaction(signers, msg, blockhash))
    assert not isinstance(result, FailedTransactionMetadata), _logs(result)


def _amount(svm: Any, key: Pubkey) -> int:
    account = svm.get_account(key)
    assert account is not None, key
    data = bytes(account.data)
    return int.from_bytes(data[64:72], "little")


def _open_mint(svm: Any, payer: Keypair, program: Pubkey) -> Keypair:
    mint = Keypair()
    rent = int(svm.minimum_balance_for_rent_exemption(MINT_LEN))
    _submit(
        svm,
        payer,
        [
            create_account(
                CreateAccountParams(
                    from_pubkey=payer.pubkey(),
                    to_pubkey=mint.pubkey(),
                    lamports=rent,
                    space=MINT_LEN,
                    owner=program,
                )
            ),
            initialize_mint2(
                InitializeMint2Params(
                    decimals=0,
                    program_id=program,
                    mint=mint.pubkey(),
                    mint_authority=payer.pubkey(),
                )
            ),
        ],
        [payer, mint],
    )
    return mint


def _open_token(svm: Any, payer: Keypair, mint: Pubkey, program: Pubkey) -> Keypair:
    token = Keypair()
    rent = int(svm.minimum_balance_for_rent_exemption(ACCOUNT_LEN))
    _submit(
        svm,
        payer,
        [
            create_account(
                CreateAccountParams(
                    from_pubkey=payer.pubkey(),
                    to_pubkey=token.pubkey(),
                    lamports=rent,
                    space=ACCOUNT_LEN,
                    owner=program,
                )
            ),
            initialize_account3(
                InitializeAccount3Params(
                    program_id=program,
                    account=token.pubkey(),
                    mint=mint,
                    owner=payer.pubkey(),
                )
            ),
        ],
        [payer, token],
    )
    return token


def _move(client: Any, so_bytes: bytes, which: str) -> None:
    svm = LiteSVM()
    prog_id = Pubkey.from_string(PROGRAM_ID)
    svm.add_program(prog_id, so_bytes)
    payer = Keypair()
    svm.airdrop(payer.pubkey(), FAUCET_LAMPORTS)
    token_program = TOKEN_PROGRAM_ID if which == "send" else TOKEN_2022_PROGRAM_ID
    mint = _open_mint(svm, payer, token_program)
    src = _open_token(svm, payer, mint.pubkey(), token_program)
    dest = _open_token(svm, payer, mint.pubkey(), token_program)
    _submit(
        svm,
        payer,
        [
            mint_to(
                MintToParams(
                    program_id=token_program,
                    mint=mint.pubkey(),
                    dest=src.pubkey(),
                    mint_authority=payer.pubkey(),
                    amount=SUPPLY,
                )
            )
        ],
        [payer],
    )
    fn = client.send if which == "send" else client.send2022
    _submit(
        svm,
        payer,
        [fn(prog_id, payer.pubkey(), src.pubkey(), dest.pubkey(), GIFT)],
        [payer],
    )
    assert _amount(svm, src.pubkey()) == SUPPLY - GIFT
    assert _amount(svm, dest.pubkey()) == GIFT


@pytest.mark.smoke
def test_token_transfer_moves_tokens(token_build: tuple[Path, Any]) -> None:
    so_path, client = token_build
    _move(client, so_path.read_bytes(), "send")


@pytest.mark.smoke
def test_token2022_transfer_moves_tokens(token_build: tuple[Path, Any]) -> None:
    so_path, client = token_build
    _move(client, so_path.read_bytes(), "send2022")


@pytest.mark.smoke
def test_ata_create_is_idempotent(token_build: tuple[Path, Any]) -> None:
    so_path, client = token_build
    svm = LiteSVM()
    prog_id = Pubkey.from_string(PROGRAM_ID)
    svm.add_program(prog_id, so_path.read_bytes())
    payer = Keypair()
    owner = Keypair()
    svm.airdrop(payer.pubkey(), FAUCET_LAMPORTS)
    svm.airdrop(owner.pubkey(), FAUCET_LAMPORTS)
    mint = _open_mint(svm, payer, TOKEN_PROGRAM_ID)
    ata = get_associated_token_address(owner.pubkey(), mint.pubkey())
    ix = client.open_ata(prog_id, payer.pubkey(), ata, owner.pubkey(), mint.pubkey())
    _submit(svm, payer, [ix], [payer, owner])
    _submit(svm, payer, [ix], [payer, owner])
    account = svm.get_account(ata)
    assert account is not None
    assert account.owner == TOKEN_PROGRAM_ID
    data = bytes(account.data)
    assert len(data) == ACCOUNT_LEN
    assert data[:32] == bytes(mint.pubkey())
    assert int.from_bytes(data[64:72], "little") == 0
