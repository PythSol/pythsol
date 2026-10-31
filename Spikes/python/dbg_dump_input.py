"""Debug helper: run the input hex-dump spike in LiteSVM with 2 accounts."""
from __future__ import annotations

import os
from pathlib import Path

from pythsol.compiler import toolchain
from pythsol.runtime import RUNTIME_INCLUDE_DIR

ROOT = Path(r"C:\Users\monkey\Desktop\Project Launch\PythSol")
PROGRAM_ID = "F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU"

os.environ.setdefault("PYTHSOL_SBF_SDK", str(ROOT / "Spikes" / "tools" / "platform-tools-1.58"))

tc = toolchain.locate_platform_tools(None)
out = ROOT / "target" / "pythsol" / "dump"
out.mkdir(parents=True, exist_ok=True)
so = toolchain.compile_to_sbf(tc, ROOT / "Spikes" / "c" / "dump_input.c", out)

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.litesvm import LiteSVM
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

svm = LiteSVM()
pid = Pubkey.from_string(PROGRAM_ID)
svm.add_program(pid, so.read_bytes())
authority = Keypair()
svm.airdrop(authority.pubkey(), 50_000_000)
other = Pubkey.from_string("So11111111111111111111111111111111111111112")

ix = Instruction(
    program_id=pid,
    accounts=[
        AccountMeta(authority.pubkey(), is_signer=True, is_writable=True),
        AccountMeta(other, is_signer=False, is_writable=False),
    ],
    data=b"\x01\x02\x03",
)
res = svm.send_transaction(Transaction([authority], Message.new_with_blockhash([ix], authority.pubkey(), (bh := svm.latest_blockhash())), bh))
def _logs_of(res: object) -> list:
    try:
        logs = getattr(res, "logs", None)
        if callable(logs):
            return list(logs())
        if logs is not None:
            return list(logs)
        meta = getattr(res, "meta", None)
        meta = meta() if callable(meta) else meta
        logs = getattr(meta, "logs", None)
        if callable(logs):
            logs = logs()
        return [str(x) for x in (logs or [])]
    except Exception:
        return [f"LOG DUMP FAILED: {type(res).__name__} {res!r}"]


print("type:", type(res).__name__)
for line in _logs_of(res):
    print("   ", line)
