"""Bisect which step augop triggers 'unsupported BPF instruction' in SBF."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\monkey\Desktop\Project Launch\PythSol")
PROGRAM_ID = "F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU"

os.environ.setdefault("PYTHSOL_SBF_SDK", str(ROOT / "Spikes" / "tools" / "platform-tools-1.58"))

from pythsol.compiler import toolchain
from pythsol.compiler.pipeline import emit_program
from pythsol.runtime import RUNTIME_INCLUDE_DIR

FIELDS = ("w8", "w16", "w32", "w64", "w128", "i8v", "i16v", "i32v", "i64v", "i128v")
OPS = {
    "w8 += 2": "    a.w8 += 2",
    "w16 += 1": "    a.w16 += 1",
    "w32 *= 2": "    a.w32 *= 2",
    "w64 += 5": "    a.w64 += 5",
    "w128 -= 1": "    a.w128 -= 1",
    "i8v += 1": "    a.i8v += 1",
    "i16v += 100": "    a.i16v += 100",
    "i32v //= 2": "    a.i32v //= 2",
    "i64v %= 7": "    a.i64v %= 7",
    "i128v += 1": "    a.i128v += 1",
}


def program(op_code: str) -> str:
    return (
        "from pythsol import Mut, account, instruction\n"
        "from pythsol import u8, u16, u32, u64, u128, i8, i16, i32, i64, i128\n"
        "\n"
        "@account\n"
        "class Arith:\n"
        + "".join(f"    {name}: {ty}\n" for name, ty in zip(FIELDS, ("u8", "u16", "u32", "u64", "u128", "i8", "i16", "i32", "i64", "i128")))
        + "\n"
        "@instruction\n"
        "def fill(a: Mut[Arith]) -> None:\n"
        "    a.w8 = 3\n"
        "    a.w16 = 65534\n"
        "    a.w32 = 2147483646\n"
        "    a.w64 = 18446744073709551610\n"
        "    a.w128 = 340282366920938463463374607431768211454\n"
        "    a.i8v = -128\n"
        "    a.i16v = -32768\n"
        "    a.i32v = -2147483648\n"
        "    a.i64v = -9223372036854775808\n"
        "    a.i128v = -170141183460469231731687303715884105728\n"
        "\n"
        "@instruction\n"
        f"def step(a: Mut[Arith]) -> None:\n{op_code}\n"
    )


def main() -> int:
    from solders.account import Account
    from solders.instruction import AccountMeta, Instruction
    from solders.keypair import Keypair
    from solders.litesvm import LiteSVM
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction

    tc = toolchain.locate_platform_tools(None)
    out = ROOT / "target" / "pythsol" / "arith_bisect"
    out.mkdir(parents=True, exist_ok=True)
    svm = LiteSVM()
    pid = Pubkey.from_string(PROGRAM_ID)
    payer = Keypair()
    svm.airdrop(payer.pubkey(), 50_000_000)

    for idx, (label, op_code) in enumerate(OPS.items()):
        src_text = program(op_code)
        src = out / f"bisect_{idx}.py"
        src.write_text(src_text, encoding="utf-8", newline="\n")
        gen = emit_program(src_text, src)
        if not gen.ok:
            print(f"[{label}] EMIT FAILED: {[d.render() for d in gen.diagnostics]}")
            continue
        c_path = out / f"bisect_{idx}.c"
        c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
        so = toolchain.compile_to_sbf(tc, c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,))

        svm = LiteSVM()
        svm.add_program(pid, so.read_bytes())
        acct_addr = Keypair().pubkey()
        svm.set_account(acct_addr, Account(
            lamports=1_000_000,
            data=bytes(70),
            owner=pid,
            executable=False,
            rent_epoch=0,
        ))

        def send(name: str) -> object:
            disc = hashlib.sha256(b"global:" + name.encode()).digest()[:8]
            ix = Instruction(
                program_id=pid,
                accounts=[AccountMeta(acct_addr, is_signer=False, is_writable=True)],
                data=disc,
            )
            blockhash = svm.latest_blockhash()
            return svm.send_transaction(Transaction(
                [payer],
                Message.new_with_blockhash([ix], payer.pubkey(), blockhash),
                blockhash,
            ))

        status = type(send("fill")).__name__
        ok_fill = "Failed" not in status
        status2 = type(send("step")).__name__
        ok_step = "Failed" not in status2
        verdict = "OK" if ok_step else "UNSUPPORTED"
        print(f"[{label:14s}] fill={'ok' if ok_fill else 'FAIL'} step={'ok' if ok_step else 'FAIL'} -> {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
