"""Spike: learn the real diagnostics for phase-4 types and Init negatives."""
from __future__ import annotations

from pathlib import Path

from pythsol.compiler.pipeline import emit_program

TMP = Path(r"C:\Users\monkey\AppData\Local\Temp\opencode\neg_probe")
TMP.mkdir(parents=True, exist_ok=True)

IMPORTS = "from pythsol import Init, Mut, Signer, Pubkey, account, error, instruction, require, u8, u16, u32, u64, u128, i64\n"

U128_ACCOUNT = IMPORTS + """

@account
class Big:
    big: u128
    small: u64


@instruction
def touch(acc: Mut[Big]) -> None:
    acc.small = 1
"""

U128_DATA_PARAM = IMPORTS + """

@account
class Small:
    n: u64


@instruction
def touch(acc: Mut[Small], big: u128) -> None:
    acc.n = 1
"""

INIT_NO_BUMP = IMPORTS + """

@account
class Cnt:
    n: u64


@instruction
def make(authority: Signer, cnt: Init[Cnt]) -> None:
    cnt.n = 0
"""

INIT_NO_PAYER = IMPORTS + """

@account
class Cnt:
    n: u64


@instruction
def make(cnt: Init[Cnt], bump: u8) -> None:
    cnt.n = 0
"""

for label, text in [
    ("U128_ACCOUNT", U128_ACCOUNT),
    ("U128_DATA_PARAM", U128_DATA_PARAM),
    ("INIT_NO_BUMP", INIT_NO_BUMP),
    ("INIT_NO_PAYER", INIT_NO_PAYER),
]:
    p = TMP / "probe.py"
    p.write_text(text, encoding="utf-8", newline="\n")
    gen = emit_program(text, p)
    print(label, "ok=", gen.ok)
    for d in gen.diagnostics:
        print("   ", d.code, d.line, d.col, d.message)
