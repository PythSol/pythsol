"""LiteSVM: system_transfer moves lamports between two signers."""

from __future__ import annotations

import importlib.util
import os
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
PAY_PATH = Path(__file__).parent / "fixtures" / "pay.py"
FAUCET_LAMPORTS = 50_000_000
GIFT = 1_000


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
    gen = emit_program(source, PAY_PATH)
    assert gen.ok and gen.generated is not None
    path = tmp / "pay_client.py"
    path.write_text(render_client(gen.generated), encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location("pay_client_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pay_build(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    tc = _tc()
    if tc is None:
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    source = PAY_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, PAY_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    out = tmp_path_factory.mktemp("pay_build")
    c_path = out / "pay.c"
    c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
    from pythsol.compiler import toolchain

    so_path = toolchain.compile_to_sbf(tc, c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,))
    return so_path, _load_client(out, source)


def _lamports(svm: Any, key: Any) -> int:
    account = svm.get_account(key)
    if account is None:
        return 0
    return int(account.lamports)


@pytest.mark.smoke
def test_pay_moves_lamports(pay_build: tuple[Path, Any]) -> None:
    so_path, client = pay_build
    svm = LiteSVM()
    prog_id = Pubkey.from_string(PROGRAM_ID)
    svm.add_program(prog_id, so_path.read_bytes())
    payer = Keypair()
    dest = Keypair()
    svm.airdrop(payer.pubkey(), FAUCET_LAMPORTS)
    svm.airdrop(dest.pubkey(), FAUCET_LAMPORTS)
    before_payer = _lamports(svm, payer.pubkey())
    before_dest = _lamports(svm, dest.pubkey())
    ix = client.pay(prog_id, payer.pubkey(), dest.pubkey(), GIFT)
    svm.expire_blockhash()
    blockhash = svm.latest_blockhash()
    msg = Message.new_with_blockhash([ix], payer.pubkey(), blockhash)
    tx = Transaction([payer, dest], msg, blockhash)
    result = svm.send_transaction(tx)
    assert not isinstance(result, FailedTransactionMetadata), _logs(result)
    assert _lamports(svm, dest.pubkey()) == before_dest + GIFT
    spent = before_payer - _lamports(svm, payer.pubkey())
    assert spent in {GIFT + 5_000, GIFT + 10_000}, spent
