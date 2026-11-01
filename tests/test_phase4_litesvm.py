"""Phase 4 acceptance — run the ledger program in LiteSVM.

initialize → deposit(slot=1, amount=5) → apply(mode=1, amount=2) → fill(7).
A foreign signer fails with 6000. Slot 4 fails the `slot < 4` require (6001);
the emitter still plants an index check (1006) behind that require.
"""

from __future__ import annotations

import importlib.util
import os
import re
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
PROGRAM_PATH = Path(__file__).parents[1] / "examples" / "ledger" / "programs" / "ledger.py"
FAUCET_LAMPORTS = 50_000_000
SEED0 = b"ledger"
_SIZE = 81  # disc + authority 32 + total 8 + slots 32 + bump 1


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


def _load_client(tmp: Path, source: str) -> Any:
    gen = emit_program(source, PROGRAM_PATH)
    assert gen.ok and gen.generated is not None
    path = tmp / "ledger_client.py"
    path.write_text(render_client(gen.generated), encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location("ledger_client_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ledger_build(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    tc = _tc()
    if tc is None:
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    source = PROGRAM_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, PROGRAM_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    out = tmp_path_factory.mktemp("ledger_build")
    c_path = out / "ledger.c"
    c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
    from pythsol.compiler import toolchain

    so_path = toolchain.compile_to_sbf(tc, c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,))
    client = _load_client(out, source)
    return so_path, client


def _slots(data: bytes) -> list[int]:
    return [int.from_bytes(data[48 + index * 8 : 56 + index * 8], "little") for index in range(4)]


class _Ledger:
    def __init__(self, so_path: Path, client: Any) -> None:
        self.client = client
        self.svm = LiteSVM()
        self.prog_id = Pubkey.from_string(PROGRAM_ID)
        self.svm.add_program(self.prog_id, so_path.read_bytes())
        self.authority = Keypair()
        self.svm.airdrop(self.authority.pubkey(), FAUCET_LAMPORTS)
        self.pda, self.bump = Pubkey.find_program_address([SEED0], self.prog_id)

    def _send(self, ix: Any, signer: Keypair) -> Any:
        blockhash = self.svm.latest_blockhash()
        msg = Message.new_with_blockhash([ix], signer.pubkey(), blockhash)
        tx = Transaction([signer], msg, blockhash)
        return self.svm.send_transaction(tx)

    def initialize(self) -> Any:
        ix = self.client.initialize(
            self.prog_id,
            self.authority.pubkey(),
            self.pda,
            self.bump,
        )
        return self._send(ix, self.authority)

    def deposit(self, slot: int, amount: int, signer: Keypair | None = None) -> Any:
        who = signer or self.authority
        ix = self.client.deposit(self.prog_id, who.pubkey(), self.pda, slot, amount)
        return self._send(ix, who)

    def apply(self, amount: int, mode: int) -> Any:
        ix = self.client.apply(
            self.prog_id,
            self.authority.pubkey(),
            self.pda,
            amount,
            mode,
        )
        return self._send(ix, self.authority)

    def fill(self, value: int) -> Any:
        ix = self.client.fill(self.prog_id, self.authority.pubkey(), self.pda, value)
        return self._send(ix, self.authority)

    def read(self) -> bytes:
        account = self.svm.get_account(self.pda)
        assert account is not None, "ledger account missing"
        return bytes(account.data)


@pytest.mark.smoke
def test_ledger_deposit_apply_and_fill(ledger_build: tuple[Path, Any]) -> None:
    so_path, client = ledger_build
    harness = _Ledger(so_path, client)
    result = harness.initialize()
    assert not _failed(result), f"initialize failed: {_logs(result)}"
    data = harness.read()
    assert len(data) == _SIZE
    assert int.from_bytes(data[40:48], "little") == 0
    assert data[80] == harness.bump

    result = harness.deposit(1, 5)
    assert not _failed(result), f"deposit failed: {_logs(result)}"
    data = harness.read()
    assert _slots(data) == [0, 5, 0, 0]
    assert int.from_bytes(data[40:48], "little") == 5

    result = harness.apply(2, 1)
    assert not _failed(result), f"apply failed: {_logs(result)}"
    data = harness.read()
    assert int.from_bytes(data[40:48], "little") == 3
    assert _slots(data)[1] == 5

    result = harness.fill(7)
    assert not _failed(result), f"fill failed: {_logs(result)}"
    data = harness.read()
    assert _slots(data) == [7, 7, 7, 7]
    assert int.from_bytes(data[40:48], "little") == 28


@pytest.mark.smoke
def test_ledger_unauthorized_and_bad_slot(ledger_build: tuple[Path, Any]) -> None:
    so_path, client = ledger_build
    harness = _Ledger(so_path, client)
    assert not _failed(harness.initialize())

    intruder = Keypair()
    harness.svm.airdrop(intruder.pubkey(), FAUCET_LAMPORTS)
    denied = harness.deposit(0, 1, signer=intruder)
    assert _failed(denied)
    assert _custom_code(denied) == 6000
    assert "ledger.py" in "\n".join(_logs(denied))

    bad = harness.deposit(4, 1)
    assert _failed(bad)
    assert _custom_code(bad) == 6001
    data = harness.read()
    assert int.from_bytes(data[40:48], "little") == 0
