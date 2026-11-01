"""Run the gate program: unit-enum tags round-trip, and a bad tag is 1011."""

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
GATE_PATH = Path(__file__).parent / "fixtures" / "gate.py"
FAUCET_LAMPORTS = 50_000_000
SEED0 = b"gate"
_SIZE = 10  # disc + status 1 + bump 1


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
    gen = emit_program(source, GATE_PATH)
    assert gen.ok and gen.generated is not None
    path = tmp / "gate_client.py"
    path.write_text(render_client(gen.generated), encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location("gate_client_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate_build(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    tc = _tc()
    if tc is None:
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    source = GATE_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, GATE_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    out = tmp_path_factory.mktemp("gate_build")
    c_path = out / "gate.c"
    c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
    from pythsol.compiler import toolchain

    so_path = toolchain.compile_to_sbf(tc, c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,))
    return so_path, _load_client(out, source)


class _Gate:
    def __init__(self, so_path: Path, client: Any) -> None:
        self.client = client
        self.svm = LiteSVM()
        self.prog_id = Pubkey.from_string(PROGRAM_ID)
        self.svm.add_program(self.prog_id, so_path.read_bytes())
        self.authority = Keypair()
        self.svm.airdrop(self.authority.pubkey(), FAUCET_LAMPORTS)
        self.pda, self.bump = Pubkey.find_program_address([SEED0], self.prog_id)

    def _send(self, ix: Any) -> Any:
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

    def apply(self, status: int) -> Any:
        ix = self.client.apply(self.prog_id, self.authority.pubkey(), self.pda, status)
        return self._send(ix)

    def read(self) -> bytes:
        account = self.svm.get_account(self.pda)
        assert account is not None, "gate account missing"
        return bytes(account.data)


@pytest.mark.smoke
def test_gate_enum_round_trip_and_bad_tag(gate_build: tuple[Path, Any]) -> None:
    so_path, client = gate_build
    harness = _Gate(so_path, client)
    result = harness.initialize()
    assert not _failed(result), f"initialize failed: {_logs(result)}"
    data = harness.read()
    assert len(data) == _SIZE
    assert data[8] == client.STATUS_OPEN
    assert data[9] == harness.bump

    result = harness.apply(client.STATUS_CLOSED)
    assert not _failed(result), f"apply(Closed) failed: {_logs(result)}"
    assert harness.read()[8] == client.STATUS_CLOSED

    result = harness.apply(client.STATUS_OPEN)
    assert not _failed(result), f"apply(Open) failed: {_logs(result)}"
    assert harness.read()[8] == client.STATUS_OPEN

    result = harness.apply(5)
    assert _failed(result), "a tag past the variants must abort"
    assert _custom_code(result) == 1011
    logs = "\n".join(_logs(result))
    assert "gate.py" in logs
    assert harness.read()[8] == client.STATUS_OPEN
