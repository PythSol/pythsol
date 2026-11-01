"""Phase 4 chunk-2 conformance: full-width fields + augops in LiteSVM.

Fills an account holding one field per integer width, mutates every field
with a checked augop, then compares all 70 on-chain bytes against
expectations computed here with pure-Python ints (the refrt oracle) and the
emitter's own account layout. Any byte divergence = the C runtime broke the
zero-divergence contract.

Run: .\\.venv\\Scripts\\python.exe Spikes\\python\\dbg_arith_litesvm.py
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from pythsol.compiler import toolchain
from pythsol.compiler.pipeline import emit_program
from pythsol.runtime import RUNTIME_INCLUDE_DIR

ROOT = Path(r"C:\Users\monkey\Desktop\Project Launch\PythSol")
PROGRAM_ID = "F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU"

os.environ.setdefault("PYTHSOL_SBF_SDK", str(ROOT / "Spikes" / "tools" / "platform-tools-1.58"))

# Every step op stays inside its type's range: an overflow would abort the
# whole transaction and revert it, hiding the per-field results.
ARITH = """\
from pythsol import Mut, account, instruction
from pythsol import u8, u16, u32, u64, u128, i8, i16, i32, i64, i128


@account
class Arith:
    w8: u8
    w16: u16
    w32: u32
    w64: u64
    w128: u128
    i8v: i8
    i16v: i16
    i32v: i32
    i64v: i64
    i128v: i128


@instruction
def fill(a: Mut[Arith]) -> None:
    a.w8 = 3
    a.w16 = 65534
    a.w32 = 2147483646
    a.w64 = 18446744073709551610
    a.w128 = 340282366920938463463374607431768211454
    a.i8v = -128
    a.i16v = -32768
    a.i32v = -2147483648
    a.i64v = -9223372036854775808
    a.i128v = -170141183460469231731687303715884105728


@instruction
def step(a: Mut[Arith]) -> None:
    a.w8 += 2
    a.w16 += 1
    a.w32 *= 2
    a.w64 += 5
    a.w128 -= 1
    a.i8v += 1
    a.i16v += 100
    a.i32v //= 2
    a.i64v %= 7
    a.i128v += 1
"""



def logs_of(res: object) -> list[str]:
    """Pull program logs whatever shape solders handed back."""
    for getter in ("logs", "meta"):
        try:
            val = getattr(res, getter)()
            if isinstance(val, list):
                return [str(line) for line in val]
            inner = getattr(val, "logs", None)
            if callable(inner):
                return [str(line) for line in inner()]
            if isinstance(inner, list):
                return [str(line) for line in inner]
        except Exception:
            continue
    return []


def pack(c_type: str, value: int) -> bytes:
    """Little-endian two's-complement bytes for one field value."""
    width = {
        "uint8_t": 1, "uint16_t": 2, "uint32_t": 4, "uint64_t": 8,
        "int8_t": 1, "int16_t": 2, "int32_t": 4, "int64_t": 8,
        "uint128_t": 16, "int128_t": 16,
    }[c_type]
    return (value & ((1 << (8 * width)) - 1)).to_bytes(width, "little")


def expected_bytes(model: object) -> bytes:
    """Recompute the final account image without the emitter or runtime."""
    acct = next(a for a in model.accounts if a.name == "Arith")
    out = bytearray(acct.discriminator)

    fields: dict[str, int] = {
        # pure-Python oracle: identical math to refrt
        "w8": 3 + 2,
        "w16": 65534 + 1,
        "w32": 2147483646 * 2,
        "w64": 18446744073709551610 + 5,
        "w128": 340282366920938463463374607431768211454 - 1,
        "i8v": -128 + 1,
        "i16v": -32768 + 100,
        "i32v": -2147483648 // 2,          # floor div
        "i64v": -9223372036854775808 % 7,  # floor mod
        "i128v": -170141183460469231731687303715884105728 + 1,
    }
    for f in acct.fields:
        end = 8 + f.offset
        while len(out) < end:
            out.append(0)
        out += pack(f.c_type, fields[f.name])
    return bytes(out)


def main() -> int:
    out = ROOT / "target" / "pythsol" / "arith_probe"
    out.mkdir(parents=True, exist_ok=True)
    src = out / "arith.py"
    src.write_text(ARITH, encoding="utf-8", newline="\n")

    gen = emit_program(ARITH, src)
    if not gen.ok:
        print("EMIT FAILED:")
        for d in gen.diagnostics:
            print("   ", d.render())
        return 1
    assert gen.generated is not None
    model = gen.generated

    c_path = out / "arith.c"
    c_path.write_text(gen.c_text, encoding="utf-8", newline="\n")
    tc = toolchain.locate_platform_tools(None)
    so = toolchain.compile_to_sbf(tc, c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,))
    print("compiled:", so.name)

    from solders.account import Account
    from solders.instruction import AccountMeta, Instruction
    from solders.keypair import Keypair
    from solders.litesvm import LiteSVM
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction

    svm = LiteSVM()
    pid = Pubkey.from_string(PROGRAM_ID)
    svm.add_program(pid, so.read_bytes())
    payer = Keypair()
    svm.airdrop(payer.pubkey(), 50_000_000)

    acct_addr = Keypair().pubkey()
    want = expected_bytes(model)
    svm.set_account(
        acct_addr,
        Account(
            lamports=1_000_000,
            # "initialized" header (correct discriminator) + zeroed payload
            data=bytes(want[:8]) + bytes(len(want) - 8),
            owner=pid,
            executable=False,
            rent_epoch=0,
        ),
    )

    def send(name: str) -> object:
        disc = hashlib.sha256(b"global:" + name.encode()).digest()[:8]
        ix = Instruction(
            program_id=pid,
            accounts=[AccountMeta(acct_addr, is_signer=False, is_writable=True)],
            data=disc,
        )
        blockhash = svm.latest_blockhash()
        return svm.send_transaction(
            Transaction(
                [payer],
                Message.new_with_blockhash([ix], payer.pubkey(), blockhash),
                blockhash,
            )
        )

    for name in ("fill", "step"):
        res = send(name)
        status = type(res).__name__
        print(f"{name}: {status}")
        if "Failed" in status:
            print("  err:", res.err())
            for line in logs_of(res):
                print("   ", line)
            return 1

    raw = bytes(svm.get_account(acct_addr).data)
    if len(raw) != len(want):
        print(f"LEN MISMATCH: on-chain {len(raw)} vs expected {len(want)}")
        return 1

    # map payload offsets -> field names for a readable diff
    acct_model = next(a for a in model.accounts if a.name == "Arith")
    names: dict[int, str] = {}
    for f in acct_model.fields:
        for off in range(8 + f.offset, 8 + f.offset + f.size):
            names[off] = f.name

    bad = [i for i in range(len(raw)) if raw[i] != want[i]]
    if not bad:
        print("DISC:", raw[:8].hex(), "(model:", acct_model.discriminator.hex(), ")")
        print("ALL", len(raw), "BYTES MATCH — zero divergence")
        for f in acct_model.fields:
            got = raw[8 + f.offset: 8 + f.offset + f.size]
            print(f"  {f.name:6s} @{f.offset:2d} = {got.hex()}")
        return 0

    print(f"DIVERGENCE in {len(bad)} byte(s):")
    for i in bad[:16]:
        print(f"  [{i:3d}] {names.get(i, '???'):6s} on-chain {raw[i]:02x} != expected {want[i]:02x}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
