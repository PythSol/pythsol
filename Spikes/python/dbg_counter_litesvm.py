"""Debug helper: run counter initialize in LiteSVM and dump everything."""
from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

from pythsol.compiler import toolchain
from pythsol.compiler.pipeline import emit_program
from pythsol.runtime import RUNTIME_INCLUDE_DIR

ROOT = Path(r"C:\Users\monkey\Desktop\Project Launch\PythSol")
SOURCE = ROOT / "examples" / "counter" / "programs" / "counter.py"
PROGRAM_ID = "F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU"

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.litesvm import LiteSVM
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

os.environ.setdefault("PYTHSOL_SBF_SDK", str(ROOT / "Spikes" / "tools" / "platform-tools-1.58"))

tc = toolchain.locate_platform_tools(None)
gen = emit_program(SOURCE.read_text(encoding="utf-8"), SOURCE)
assert gen.ok, [d.render() for d in gen.diagnostics]
out = ROOT / "target" / "pythsol" / "counter"
out.mkdir(parents=True, exist_ok=True)
c_path = out / "counter.c"
c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
so = toolchain.compile_to_sbf(tc, c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,))
print("so:", so)

svm = LiteSVM()
pid = Pubkey.from_string(PROGRAM_ID)
svm.add_program(pid, so.read_bytes())
authority = Keypair()
svm.airdrop(authority.pubkey(), 50_000_000)
pda, bump = Pubkey.find_program_address([b"counter"], pid)
system_id = Pubkey.from_string("11111111111111111111111111111111")
print("pda:", pda, "bump:", bump)

disc = hashlib.sha256(b"global:initialize").digest()[:8]
ix = Instruction(
    program_id=pid,
    accounts=[
        AccountMeta(authority.pubkey(), is_signer=True, is_writable=True),
        AccountMeta(pda, is_signer=False, is_writable=True),
        AccountMeta(system_id, is_signer=False, is_writable=False),
    ],
    data=disc + struct.pack("B", bump),
)
blockhash = svm.latest_blockhash()
blockhash = svm.latest_blockhash()
res = svm.send_transaction(Transaction([authority], Message.new_with_blockhash([ix], authority.pubkey(), blockhash), blockhash))
print("init type:", type(res).__name__)
try:
    print("LOGS:")
    for line in res.logs():
        print("   ", line)
except Exception as err:
    print("log dump failed:", err)

acct = svm.get_account(pda)
print("acct type:", type(acct).__name__)
data = bytes(acct.data)
print("data len:", len(data))
print("disc:", data[:8].hex())
print("authority:", data[8:40].hex())
print("count:", int.from_bytes(data[40:48], "little"))
print("bump:", data[48])

disc_inc = hashlib.sha256(b"global:increment").digest()[:8]
ix2 = Instruction(
    program_id=pid,
    accounts=[
        AccountMeta(authority.pubkey(), is_signer=True, is_writable=False),
        AccountMeta(pda, is_signer=False, is_writable=True),
    ],
    data=disc_inc + struct.pack("<Q", 5),
)
blockhash = svm.latest_blockhash()
res2 = svm.send_transaction(Transaction([authority], Message.new_with_blockhash([ix2], authority.pubkey(), blockhash), blockhash))
print("increment type:", type(res2).__name__)
try:
    for line in res2.logs():
        print("   ", line)
except Exception as err:
    print("log dump failed:", err)
data = bytes(svm.get_account(pda).data)
print("count after increment(5):", int.from_bytes(data[40:48], "little"))

