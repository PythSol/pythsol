"""LiteSVM: Seeds, HasOne, Address, Owner, and CloseTo on a vault."""

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
VAULT_PATH = Path(__file__).parent / "fixtures" / "vault.py"
FAUCET_LAMPORTS = 50_000_000
SEED0 = b"box"
_SIZE = 49  # disc + authority 32 + balance 8 + bump 1


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
    gen = emit_program(source, VAULT_PATH)
    assert gen.ok and gen.generated is not None
    path = tmp / "vault_client.py"
    path.write_text(render_client(gen.generated), encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location("vault_client_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def vault_build(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    tc = _tc()
    if tc is None:
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    source = VAULT_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, VAULT_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert '(const uint8_t *)"box", 3u,' in gen.c_text
    out = tmp_path_factory.mktemp("vault_build")
    c_path = out / "vault.c"
    c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
    from pythsol.compiler import toolchain

    so_path = toolchain.compile_to_sbf(tc, c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,))
    return so_path, _load_client(out, source)


class _Vault:
    def __init__(self, so_path: Path, client: Any) -> None:
        self.client = client
        self.svm = LiteSVM()
        self.prog_id = Pubkey.from_string(PROGRAM_ID)
        self.svm.add_program(self.prog_id, so_path.read_bytes())
        self.payer = Keypair()
        self.svm.airdrop(self.payer.pubkey(), FAUCET_LAMPORTS)
        self.pda, self.bump = Pubkey.find_program_address([SEED0], self.prog_id)

    def _send(self, ix: Any) -> Any:
        self.svm.expire_blockhash()
        blockhash = self.svm.latest_blockhash()
        msg = Message.new_with_blockhash([ix], self.payer.pubkey(), blockhash)
        tx = Transaction([self.payer], msg, blockhash)
        return self.svm.send_transaction(tx)

    def initialize(self) -> Any:
        ix = self.client.initialize(self.prog_id, self.payer.pubkey(), self.pda, self.bump)
        return self._send(ix)

    def note(self, amount: int) -> Any:
        ix = self.client.note(self.prog_id, self.payer.pubkey(), self.pda, amount)
        return self._send(ix)

    def retarget(self, who: Pubkey) -> Any:
        ix = self.client.retarget(self.prog_id, self.pda, who)
        return self._send(ix)

    def prove(self, expected: Pubkey) -> Any:
        ix = self.client.prove(self.prog_id, self.pda, expected)
        return self._send(ix)

    def own(self) -> Any:
        ix = self.client.own(self.prog_id, self.payer.pubkey(), self.pda)
        return self._send(ix)

    def close(self) -> Any:
        ix = self.client.close(self.prog_id, self.payer.pubkey(), self.pda)
        return self._send(ix)

    def read(self) -> bytes | None:
        account = self.svm.get_account(self.pda)
        if account is None:
            return None
        return bytes(account.data)

    def lamports(self) -> int:
        account = self.svm.get_account(self.pda)
        if account is None:
            return 0
        return int(account.lamports)


def _balance(data: bytes) -> int:
    return struct.unpack_from("<Q", data, 40)[0]


@pytest.mark.smoke
def test_vault_constraints_on_chain(vault_build: tuple[Path, Any]) -> None:
    _so, client = vault_build
    harness = _Vault(_so, client)
    result = harness.initialize()
    assert not _failed(result), f"initialize failed: {_logs(result)}"
    data = harness.read()
    assert data is not None and len(data) == _SIZE
    assert data[8:40] == bytes(harness.payer.pubkey())
    assert _balance(data) == 0
    assert data[48] == harness.bump
    rent = harness.lamports()
    assert rent > 0

    result = harness.note(5)
    assert not _failed(result), f"note failed: {_logs(result)}"
    assert _balance(harness.read() or b"") == 5

    stranger = Keypair().pubkey()
    result = harness.retarget(stranger)
    assert not _failed(result), f"retarget failed: {_logs(result)}"
    result = harness.note(9)
    assert _failed(result), "has-one must reject a different authority"
    assert _custom_code(result) == 1014
    assert _balance(harness.read() or b"") == 5

    result = harness.retarget(harness.payer.pubkey())
    assert not _failed(result), f"retarget back failed: {_logs(result)}"
    result = harness.note(9)
    assert not _failed(result), f"note after retarget failed: {_logs(result)}"
    assert _balance(harness.read() or b"") == 9

    result = harness.prove(harness.pda)
    assert not _failed(result), f"address match failed: {_logs(result)}"
    result = harness.prove(stranger)
    assert _failed(result), "a different address must be rejected"
    assert _custom_code(result) == 1014
    assert _balance(harness.read() or b"") == 9

    result = harness.own()
    assert _failed(result), "the payer is not the account owner"
    assert _custom_code(result) == 1014

    before = harness.svm.get_balance(harness.payer.pubkey())
    result = harness.close()
    assert not _failed(result), f"close failed: {_logs(result)}"
    after = harness.svm.get_balance(harness.payer.pubkey())
    assert harness.lamports() == 0
    left = harness.read()
    assert left is None or left == b""
    # The signature fee is 5000 lamports. The vault's rent is what remains.
    assert after == before + rent - 5_000
