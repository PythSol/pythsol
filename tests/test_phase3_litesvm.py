"""Phase 3 acceptance — run the compiled counter program in LiteSVM.

TRD §18 Phase 3 acceptance:

* initialize → increment(5) leaves ``count = 5``;
* an *unauthorized* increment fails with code 6000 and a program log that
  contains ``(counter.py:51)`` (the ``require`` source location);
* an *overflowing* increment aborts with a log at ``(counter.py:52)``;
  any failure code is acceptable (the runtime aborts with 1009).

Needs the SBF platform-tools (to link ``counter.so``) and the ``solders``
package for the LiteSVM bindings; both skip gracefully when absent.
The harness mirrors the Phase 1 spike (``tests/test_phase1.py``); the binary
input layout follows ADR-0010 (verified against solana-program 1.18.26).
"""

from __future__ import annotations

import hashlib
import os
import re
import struct
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("solders")
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.litesvm import LiteSVM
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solders.transaction_metadata import FailedTransactionMetadata

from pythsol.compiler.pipeline import emit_program
from pythsol.runtime import RUNTIME_INCLUDE_DIR

#: Deterministic program id (same pattern as Spikes/python/cn_litesvm_hello.py).
PROGRAM_ID = "F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU"

PROGRAM_DIR = Path(__file__).parents[1] / "examples" / "counter" / "programs"
PROGRAM_SOURCE = PROGRAM_DIR / "counter.py"

#: 49-byte account rent ≈ 1,231,920 lamports + fees; airdrops are uncapped.
FAUCET_LAMPORTS = 50_000_000

#: PDA seed #1 for `Init[Counter]` = snake_case(Counter) per ADR-0010.
SEED0 = b"counter"

#: The System program — required in initialize's account list for the CPI.
SYSTEM_ID = Pubkey.from_string("11111111111111111111111111111111")

_SIZE = 49  # disc(8) + authority(32) + count(8) + bump(1)


def _global_disc(name: str) -> bytes:
    """sha256("global:<snake_name>")[..8] — the instruction discriminator."""
    return hashlib.sha256(b"global:" + name.encode()).digest()[:8]


def _account_disc(name: str) -> bytes:
    """sha256("account:<PascalName>")[..8] — the account discriminator."""
    return hashlib.sha256(b"account:" + name.encode()).digest()[:8]


def _tc() -> Any:
    """Locate the SBF toolchain, pointing PYTHSOL_SBF_SDK at the spike dir."""
    from pythsol.compiler import toolchain
    from pythsol.compiler.diagnostics import PysolError

    try:
        return toolchain.locate_platform_tools(None)
    except PysolError:
        sdk = Path(__file__).parents[1] / "Spikes" / "tools" / "platform-tools-1.58"
        if not sdk.is_dir():
            return None
        os.environ.setdefault("PYTHSOL_SBF_SDK", str(sdk))
        try:
            return toolchain.locate_platform_tools(None)
        except PysolError:
            return None


@pytest.fixture(scope="module")
def counter_so(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Compile counter.py → .so once per test module (expensive)."""
    tc = _tc()
    if tc is None:
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    gen = emit_program(PROGRAM_SOURCE.read_text(encoding="utf-8"), PROGRAM_SOURCE)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    out = tmp_path_factory.mktemp("counter_build")
    c_path = out / "counter.c"
    c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
    from pythsol.compiler import toolchain

    return toolchain.compile_to_sbf(tc, c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,))


def _logs(result: Any) -> list[str]:
    """Collect program logs from a TransactionMetadata (or failure) result.

    `solders` exposes `.logs()` on TransactionMetadata but a FailedTransaction-
    Metadata only carries `.meta()` → the same metadata. Callables are probed
    before attributes so both shapes work.
    """
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
    """Best-effort extraction of a custom instruction error code.

    solders formats the failure as ``InstructionErrorCustom(N)`` (via the
    ``err()`` accessor); a plain ``custom program error: 0x…`` string is also
    accepted for compatibility with agave's Display form.
    """
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


class _Counter:
    """One LiteSVM + fresh authority/counter-PDA pair per test."""

    def __init__(self, so_path: Path) -> None:
        self.svm = LiteSVM()
        self.prog_id = Pubkey.from_string(PROGRAM_ID)
        self.svm.add_program(self.prog_id, so_path.read_bytes())
        self.authority = Keypair()
        self.svm.airdrop(self.authority.pubkey(), FAUCET_LAMPORTS)
        # Seeds = [b"counter", bump]; find_program_address derives the bump.
        self.pda, self.bump = Pubkey.find_program_address([SEED0], self.prog_id)

    def _send(self, ix: Instruction, signer: Keypair) -> Any:
        blockhash = self.svm.latest_blockhash()
        msg = Message.new_with_blockhash([ix], signer.pubkey(), blockhash)
        tx = Transaction([signer], msg, blockhash)
        return self.svm.send_transaction(tx)

    def initialize(self) -> Any:
        """authority pays and creates the counter at the PDA.

        The System program itself rides along as the third account: the
        create_account CPI needs it in the caller's account list (ADR-0010).
        """
        return self._send(
            Instruction(
                program_id=self.prog_id,
                accounts=[
                    AccountMeta(self.authority.pubkey(), is_signer=True, is_writable=True),
                    AccountMeta(self.pda, is_signer=False, is_writable=True),
                    AccountMeta(SYSTEM_ID, is_signer=False, is_writable=False),
                ],
                data=_global_disc("initialize") + bytes([self.bump]),
            ),
            self.authority,
        )

    def increment(self, amount: int, signer: Keypair | None = None) -> Any:
        return self._send(
            Instruction(
                program_id=self.prog_id,
                accounts=[
                    AccountMeta(
                        (signer or self.authority).pubkey(),
                        is_signer=True,
                        is_writable=False,
                    ),
                    AccountMeta(self.pda, is_signer=False, is_writable=True),
                ],
                data=_global_disc("increment") + struct.pack("<Q", amount),
            ),
            signer or self.authority,
        )

    def read(self) -> bytes:
        account = self.svm.get_account(self.pda)
        assert account is not None, "counter account missing from the ledger"
        return bytes(account.data)


@pytest.mark.smoke
def test_counter_initialize_then_increment_five(counter_so: Path) -> None:
    """Acceptance №1: initialize → increment(5) leaves count == 5."""
    harness = _Counter(counter_so)
    result = harness.initialize()
    assert not _failed(result), f"initialize failed: {_logs(result)}"

    data = harness.read()
    assert len(data) == _SIZE
    assert data[:8] == _account_disc("Counter")
    assert data[8:40] == bytes(harness.authority.pubkey())
    assert int.from_bytes(data[40:48], "little") == 0
    assert data[48] == harness.bump

    result = harness.increment(5)
    assert not _failed(result), f"increment(5) failed: {_logs(result)}"
    data = harness.read()
    assert int.from_bytes(data[40:48], "little") == 5


@pytest.mark.smoke
def test_counter_increment_unauthorized(counter_so: Path) -> None:
    """Acceptance №2: a foreign signer fails with 6000 + (counter.py:51)."""
    harness = _Counter(counter_so)
    result = harness.initialize()
    assert not _failed(result), f"initialize failed: {_logs(result)}"

    intruder = Keypair()
    harness.svm.airdrop(intruder.pubkey(), FAUCET_LAMPORTS)
    result = harness.increment(1, signer=intruder)
    assert _failed(result), "a foreign signer must not pass the require()"
    assert _custom_code(result) == 6000
    logs = "\n".join(_logs(result))
    assert "(counter.py:51)" in logs

    # No side effects: count must still be zero.
    data = harness.read()
    assert int.from_bytes(data[40:48], "little") == 0


@pytest.mark.smoke
def test_counter_increment_overflow_aborts(counter_so: Path) -> None:
    """Acceptance №3: u64 overflow aborts with a (counter.py:52) log."""
    harness = _Counter(counter_so)
    assert not _failed(harness.initialize())
    result = harness.increment(3)
    assert not _failed(result), f"increment(3) failed: {_logs(result)}"

    result = harness.increment(2**64 - 1)  # 3 + (2^64 - 1) overflows
    assert _failed(result), "an overflow must abort the transaction"
    logs = "\n".join(_logs(result))
    assert "(counter.py:52)" in logs

    # The aborted add must not have touched the stored count.
    data = harness.read()
    assert int.from_bytes(data[40:48], "little") == 3
