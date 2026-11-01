"""Run the label program: FixedString[8] round-trips, and a long length is 1013."""

from __future__ import annotations

import importlib.util
import os
import re
import struct
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("solders")
from solders.instruction import Instruction
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
LABEL_PATH = Path(__file__).parent / "fixtures" / "label.py"
FAUCET_LAMPORTS = 50_000_000
SEED0 = b"label"
_SIZE = 29  # disc + FixedString[8] (12) + nchars 8 + bump 1


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
    gen = emit_program(source, LABEL_PATH)
    assert gen.ok and gen.generated is not None
    path = tmp / "label_client.py"
    path.write_text(render_client(gen.generated), encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location("label_client_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def label_build(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    tc = _tc()
    if tc is None:
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    source = LABEL_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, LABEL_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    out = tmp_path_factory.mktemp("label_build")
    c_path = out / "label.c"
    c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
    from pythsol.compiler import toolchain

    so_path = toolchain.compile_to_sbf(tc, c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,))
    return so_path, _load_client(out, source)


class _Label:
    def __init__(self, so_path: Path, client: Any) -> None:
        self.client = client
        self.svm = LiteSVM()
        self.prog_id = Pubkey.from_string(PROGRAM_ID)
        self.svm.add_program(self.prog_id, so_path.read_bytes())
        self.authority = Keypair()
        self.svm.airdrop(self.authority.pubkey(), FAUCET_LAMPORTS)
        self.pda, self.bump = Pubkey.find_program_address([SEED0], self.prog_id)

    def _send(self, ix: Any) -> Any:
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

    def set_text(self, text: str) -> Any:
        ix = self.client.set_text(self.prog_id, self.authority.pubkey(), self.pda, text)
        return self._send(ix)

    def clear(self) -> Any:
        ix = self.client.clear(self.prog_id, self.authority.pubkey(), self.pda)
        return self._send(ix)

    def stamp(self) -> Any:
        ix = self.client.stamp(self.prog_id, self.authority.pubkey(), self.pda)
        return self._send(ix)

    def poke(self, index: int, byte: int) -> Any:
        ix = self.client.poke(
            self.prog_id, self.authority.pubkey(), self.pda, index, byte
        )
        return self._send(ix)

    def echo(self, index: int) -> Any:
        ix = self.client.echo(self.prog_id, self.authority.pubkey(), self.pda, index)
        return self._send(ix)

    def choose(self, text: str, use_arg: int) -> Any:
        ix = self.client.choose(
            self.prog_id, self.authority.pubkey(), self.pda, text, use_arg
        )
        return self._send(ix)

    def read(self) -> bytes:
        account = self.svm.get_account(self.pda)
        assert account is not None, "label account missing"
        return bytes(account.data)


def _text(data: bytes) -> tuple[int, bytes]:
    length = struct.unpack_from("<I", data, 8)[0]
    return length, data[12:20]


def _nchars(data: bytes) -> int:
    return struct.unpack_from("<Q", data, 20)[0]


@pytest.mark.smoke
def test_label_fixed_string_round_trip(label_build: tuple[Path, Any]) -> None:
    so_path, client = label_build
    harness = _Label(so_path, client)
    result = harness.initialize()
    assert not _failed(result), f"initialize failed: {_logs(result)}"
    data = harness.read()
    assert len(data) == _SIZE
    assert _text(data) == (2, b"hi" + bytes(6))
    assert _nchars(data) == 2
    assert data[28] == harness.bump
    decoded = client.decode_label(data)
    assert decoded["text"] == "hi"
    assert decoded["nchars"] == 2

    result = harness.echo(1)
    assert not _failed(result), f"echo failed: {_logs(result)}"
    data = harness.read()
    assert _nchars(data) == ord("i")
    assert _text(data) == (2, b"hi" + bytes(6))

    result = harness.clear()
    assert not _failed(result), f"clear failed: {_logs(result)}"
    data = harness.read()
    assert _text(data) == (0, bytes(8))
    assert _nchars(data) == 0

    result = harness.set_text("yo")
    assert not _failed(result), f"set_text failed: {_logs(result)}"
    assert _text(harness.read()) == (2, b"yo" + bytes(6))

    result = harness.set_text("é")
    assert not _failed(result), f"set_text utf-8 failed: {_logs(result)}"
    assert _text(harness.read()) == (2, "é".encode() + bytes(6))
    assert client.decode_label(harness.read())["text"] == "é"

    result = harness.stamp()
    assert not _failed(result), f"stamp failed: {_logs(result)}"
    data = harness.read()
    assert _text(data) == (2, b"ok" + bytes(6))
    assert _nchars(data) == 2

    result = harness.poke(0, ord("Z"))
    assert not _failed(result), f"poke failed: {_logs(result)}"
    data = harness.read()
    assert _text(data) == (2, b"Zk" + bytes(6))

    result = harness.echo(0)
    assert not _failed(result), f"echo byte failed: {_logs(result)}"
    assert _nchars(harness.read()) == ord("Z")

    result = harness.choose("ab", 1)
    assert not _failed(result), f"choose failed: {_logs(result)}"
    data = harness.read()
    assert _text(data) == (2, b"ab" + bytes(6))
    assert _nchars(data) == 2

    result = harness.choose("zz", 0)
    assert not _failed(result), f"choose keep failed: {_logs(result)}"
    assert _text(harness.read()) == (2, b"ab" + bytes(6))

    try:
        client.set_text(harness.prog_id, harness.authority.pubkey(), harness.pda, "123456789")
    except ValueError as err:
        assert "FixedString[8]" in str(err)
    else:
        raise AssertionError("client accepted a 9-byte string")

    good = client.set_text(harness.prog_id, harness.authority.pubkey(), harness.pda, "ab")
    bad = Instruction(
        good.program_id,
        bytes(client._DISC_SET_TEXT) + struct.pack("<I", 9) + bytes(8),
        good.accounts,
    )
    result = harness._send(bad)
    assert _failed(result), f"over-long length should fail: {_logs(result)}"
    assert _custom_code(result) == 1013
    assert _text(harness.read()) == (2, b"ab" + bytes(6))
