"""Spike driver: run the u128/i128 probe in LiteSVM."""
from __future__ import annotations

import os
from pathlib import Path

from pythsol.compiler import toolchain

ROOT = Path(r"C:\Users\monkey\Desktop\Project Launch\PythSol")
PROGRAM_ID = "F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU"

os.environ.setdefault("PYTHSOL_SBF_SDK", str(ROOT / "Spikes" / "tools" / "platform-tools-1.58"))
tc = toolchain.locate_platform_tools(None)
print("toolchain:", tc)

out = ROOT / "target" / "pythsol" / "u128_spike"
out.mkdir(parents=True, exist_ok=True)
try:
    so = toolchain.compile_to_sbf(tc, ROOT / "Spikes" / "c" / "u128.c", out)
    print("compiled:", so)
except Exception as err:
    print("COMPILE FAILED:", err)
    raise SystemExit(0)

from solders.litesvm import LiteSVM
from solders.message import Message
from solders.transaction import Transaction
from solders.instruction import AccountMeta, Instruction

svm = LiteSVM()
pid = __import__("solders.pubkey", fromlist=["Pubkey"]).Pubkey.from_string(PROGRAM_ID)
svm.add_program(pid, so.read_bytes())
payer = __import__("solders.keypair", fromlist=["Keypair"]).Keypair()
svm.airdrop(payer.pubkey(), 50_000_000)
ix = Instruction(program_id=pid, accounts=[AccountMeta(payer.pubkey(), False, False)], data=b"")
res = svm.send_transaction(
    Transaction(
        [payer],
        Message.new_with_blockhash([ix], payer.pubkey(), (bh := svm.latest_blockhash())),
        bh,
    )
)
print("result:", type(res).__name__)
try:
    for line in res.logs():
        print("   ", line)
except Exception as err:
    print("logs unavailable:", err, "|", getattr(res, "err", lambda: None)())

