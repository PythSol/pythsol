"""PythSol reference runtime (``refrt``) — the CPython mirror of the SBF C.

Every integer operation the language exposes has exactly one semantic
definition. The C runtime (``src/pythsol/runtime/pythsol_rt.h``) implements it
in C; this package implements the identical rules in pure Python so:

* property tests can compare every operation against plain ``int`` math
  (10 000+ cases per width, TRD §18 Phase 4);
* ``pythsol.testing`` can execute instruction logic as a CPython-equivalent
  oracle during differential testing.

Semantics (pinned; do not change without a spec note *and* the same change in
pythsol_rt.h — the phase 4 conformance tests hold both sides together):

* integers have fixed widths (``u8…u128``, ``i8…i128``) and always behave as
  two's-complement limbs of that width — no promotion, no bignum leakage;
* ``checked_add/sub/mul`` abort (return ``(False, 0)``) on any result outside
  the width's bounds — on-chain that is error ``1009``;
* division is **floor** division for every signedness (Python semantics);
  division by zero and signed ``min / -1`` abort (error ``1009``/``1010``);
* ``checked_mod`` is Python's ``%`` (sign of the divisor's *negation*, i.e.
  always in ``0 <= r < |b|`` for ``b != 0``), aborting on ``b == 0`` and
  signed ``min % -1``;
* shifts abort when the shift count is ``>= width`` or (left shifts only)
  the result leaves the width's bounds; right shifts are arithmetic for
  signed widths and logical for unsigned widths;
* casts truncate to the target raw width then reinterpret it in the target
  signedness (a value-preserving conversion whenever the target can hold it).
"""

from __future__ import annotations

import re

__all__ = [
    "INT_WIDTHS",
    "SIGNED_WIDTHS",
    "UNSIGNED_WIDTHS",
    "bits_of",
    "bounds",
    "cast",
    "checked_add",
    "checked_div",
    "checked_mod",
    "checked_mul",
    "checked_shl",
    "checked_shr",
    "checked_sub",
    "from_c_bits",
    "is_signed",
    "to_c_bits",
]

#: All integer type widths in declaration order.
INT_WIDTHS: tuple[str, ...] = (
    "u8",
    "u16",
    "u32",
    "u64",
    "u128",
    "i8",
    "i16",
    "i32",
    "i64",
    "i128",
)

UNSIGNED_WIDTHS: tuple[str, ...] = ("u8", "u16", "u32", "u64", "u128")
SIGNED_WIDTHS: tuple[str, ...] = ("i8", "i16", "i32", "i64", "i128")

_WIDTH_RE = re.compile(r"^([ui])(8|16|32|64|128)$")

#: RT_ERR_* code the C runtime aborts with for arithmetic (pythsol_rt.h).
ERR_OVERFLOW = 1009
ERR_DIV_ZERO = 1010

_BITS = (8, 16, 32, 64, 128)


def is_signed(width: str) -> bool:
    """``i64`` → True (any ``i``-width is signed)."""
    return width.startswith("i")


def bits_of(width: str) -> int:
    """Bit count of a width name (``u64`` → 64)."""
    match = _WIDTH_RE.match(width)
    if match is None:
        raise ValueError(f"unknown width `{width}` (u*/i* with 8|16|32|64|128)")
    return int(match.group(2))


def bounds(width: str) -> tuple[int, int]:
    """Inclusive (min, max) of a width (``i8`` → (-128, 127); ``u8`` → (0, 255))."""
    n = bits_of(width)
    if is_signed(width):
        return -(1 << (n - 1)), (1 << (n - 1)) - 1
    return 0, (1 << n) - 1


def to_c_bits(width: str, value: int) -> int:
    """Value → raw limb in the width's two's-complement representation."""
    low, high = bounds(width)
    if not low <= value <= high:
        raise ValueError(f"{value} does not fit in `{width}`")
    bits = bits_of(width)
    return value & ((1 << bits) - 1)


def from_c_bits(width: str, raw: int) -> int:
    """Raw limb → value, reinterpreting the bits in the width's signedness."""
    bits = bits_of(width)
    raw &= (1 << bits) - 1
    if is_signed(width) and raw >> (bits - 1):
        raw -= 1 << bits
    return raw


def checked_add(width: str, a: int, b: int) -> tuple[bool, int]:
    """``a + b`` inside the width; ``(False, 0)`` = on-chain abort 1009."""
    return _checked_binop(width, a + b)


def checked_sub(width: str, a: int, b: int) -> tuple[bool, int]:
    """``a - b`` inside the width; ``(False, 0)`` = on-chain abort 1009."""
    return _checked_binop(width, a - b)


def checked_mul(width: str, a: int, b: int) -> tuple[bool, int]:
    """``a * b`` inside the width; ``(False, 0)`` = on-chain abort 1009."""
    return _checked_binop(width, a * b)


def checked_div(width: str, a: int, b: int) -> tuple[bool, int]:
    """Floor ``a / b`` (Python ``//``); abort 1010 for ``b == 0``/``min / -1``."""
    if b == 0:
        return False, ERR_DIV_ZERO
    low, high = bounds(width)
    if is_signed(width) and a == low and b == -1:
        return False, ERR_OVERFLOW
    q = a // b  # Python floor semantics
    if not low <= q <= high:
        return False, ERR_OVERFLOW
    return True, q


def checked_mod(width: str, a: int, b: int) -> tuple[bool, int]:
    """Floor ``a % b`` (Python ``%``); abort 1010 for ``b == 0``/``min % -1``."""
    if b == 0:
        return False, ERR_DIV_ZERO
    if is_signed(width):
        low, _high = bounds(width)
        if a == low and b == -1:
            # C convention: remainder of the overflow division; we abort like
            # div to keep '%'' harmless under fuzzing (mirrors rt_checked_mod).
            return False, ERR_OVERFLOW
    return True, a % b  # Python % is already floor (0 <= r < |b| when b != 0)


def checked_shl(width: str, a: int, s: int) -> tuple[bool, int]:
    """``a << s`` checked: abort 1010 when ``s >= bits``; 1009 on overflow."""
    bits = bits_of(width)
    if s < 0 or s >= bits:
        return False, ERR_DIV_ZERO  # shift-count abuse shares the 1010 path
    return _checked_binop(width, a << s)


def checked_shr(width: str, a: int, s: int) -> tuple[bool, int]:
    """``a >> s`` (arithmetic for ``i*``, logical for ``u*``); abort at ``s >= bits``."""
    bits = bits_of(width)
    if s < 0 or s >= bits:
        return False, ERR_DIV_ZERO
    if is_signed(width):
        # Python's >> on a signed value *is* arithmetic shift.
        low, high = bounds(width)
        if not low <= a <= high:
            return False, ERR_OVERFLOW
        return True, a >> s
    return True, (a >> s) & ((1 << bits) - 1)


def cast(target: str, source: str, value: int) -> int:
    """Cast ``value`` from ``source`` width to ``target`` width.

    Semantics are exactly ``(T)(x)`` in the generated C: the operand is a
    valid ``source`` value; its **mathematical** two's-complement bit pattern
    is truncated to the target width and reinterpreted in the target's
    signedness — e.g. ``(i64)(i8 -1) == -1`` while ``(u8)(i32 -1) == 255``.
    The source width only gate-keeps validity, it never re-truncates.
    """
    if not bounds(source)[0] <= value <= bounds(source)[1]:
        raise ValueError(f"{value} does not fit in `{source}`")
    return from_c_bits(target, value & ((1 << bits_of(target)) - 1))


def _checked_binop(width: str, value: int) -> tuple[bool, int]:
    low, high = bounds(width)
    if not low <= value <= high:
        return False, ERR_OVERFLOW
    return True, value
