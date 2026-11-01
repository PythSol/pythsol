"""Run the note program: fixed-width Option[u64] round-trips, and a clear tag is 1012."""

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
NOTE_PATH = Path(__file__).parent / "fixtures" / "note.py"
FAUCET_LAMPORTS = 50_000_000
SEED0 = b"note"
_SIZE = 26  # disc + option 9 + seen 8 + bump 1


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
    gen = emit_program(source, NOTE_PATH)
    assert gen.ok and gen.generated is not None
    path = tmp / "note_client.py"
    path.write_text(render_client(gen.generated), encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location("note_client_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def note_build(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    tc = _tc()
    if tc is None:
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    source = NOTE_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, NOTE_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    out = tmp_path_factory.mktemp("note_build")
    c_path = out / "note.c"
    c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
    from pythsol.compiler import toolchain

    so_path = toolchain.compile_to_sbf(tc, c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,))
    return so_path, _load_client(out, source)


class _Note:
    def __init__(self, so_path: Path, client: Any) -> None:
        self.client = client
        self.svm = LiteSVM()
        self.prog_id = Pubkey.from_string(PROGRAM_ID)
        self.svm.add_program(self.prog_id, so_path.read_bytes())
        self.authority = Keypair()
        self.svm.airdrop(self.authority.pubkey(), FAUCET_LAMPORTS)
        self.pda, self.bump = Pubkey.find_program_address([SEED0], self.prog_id)

    def _send(self, ix: Any) -> Any:
        # Identical instructions (take, twice) need a fresh blockhash or the
        # second signature is AlreadyProcessed.
        self.svm.expire_blockhash()
        blockhash = self.svm.latest_blockhash()
        msg = Message.new_with_blockhash([ix], self.authority.pubkey(), blockhash)
        tx = Transaction([self.authority], msg, blockhash)
        return self.svm.send_transaction(tx)

    def initialize(self) -> Any:
        ix = self.client.initialize(
            self.prog_id,
            self.authority.pubkey(),
            self.pda,
            self.bump,
        )
        return self._send(ix)

    def set_amount(self, amount: int | None) -> Any:
        ix = self.client.set_amount(
            self.prog_id, self.authority.pubkey(), self.pda, amount
        )
        return self._send(ix)

    def apply(self, amount: int | None) -> Any:
        ix = self.client.apply(self.prog_id, self.authority.pubkey(), self.pda, amount)
        return self._send(ix)

    def take(self) -> Any:
        ix = self.client.take(self.prog_id, self.authority.pubkey(), self.pda)
        return self._send(ix)

    def read(self) -> bytes:
        account = self.svm.get_account(self.pda)
        assert account is not None, "note account missing"
        return bytes(account.data)


def _amount(data: bytes) -> tuple[int, int]:
    return data[8], struct.unpack_from("<Q", data, 9)[0]


def _seen(data: bytes) -> int:
    return struct.unpack_from("<Q", data, 17)[0]


@pytest.mark.smoke
def test_note_option_round_trip_and_none_value(note_build: tuple[Path, Any]) -> None:
    so_path, client = note_build
    harness = _Note(so_path, client)
    result = harness.initialize()
    assert not _failed(result), f"initialize failed: {_logs(result)}"
    data = harness.read()
    assert len(data) == _SIZE
    assert _amount(data) == (0, 0)
    assert _seen(data) == 0
    assert data[25] == harness.bump
    decoded = client.decode_note(data)
    assert decoded["amount"] == (0, 0)
    assert decoded["bump"] == harness.bump

    result = harness.take()
    assert _failed(result), "reading .value of a clear option must abort"
    assert _custom_code(result) == 1012
    logs = "\n".join(_logs(result))
    assert "note.py" in logs
    assert _amount(harness.read()) == (0, 0)
    assert _seen(harness.read()) == 0

    result = harness.set_amount(5)
    assert not _failed(result), f"set_amount(5) failed: {_logs(result)}"
    assert _amount(harness.read()) == (1, 5)

    result = harness.take()
    assert not _failed(result), f"take failed: {_logs(result)}"
    assert _seen(harness.read()) == 5
    assert _amount(harness.read()) == (1, 5)

    result = harness.set_amount(0)
    assert not _failed(result), f"set_amount(0) failed: {_logs(result)}"
    assert _amount(harness.read()) == (1, 0)

    result = harness.apply(None)
    assert not _failed(result), f"apply(None) failed: {_logs(result)}"
    assert _amount(harness.read()) == (0, 0)

    result = harness.apply(7)
    assert not _failed(result), f"apply(7) failed: {_logs(result)}"
    assert _amount(harness.read()) == (1, 7)
