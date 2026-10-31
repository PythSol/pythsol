"""Phase 4 acceptance: arithmetic property tests vs Python ``int`` semantics.

TRD §18 Phase 4 requires ≥ 10 000 cases per integer width with **zero
divergences** from Python ``int`` math. Every operation the language exposes
(``checked_add``/``sub``/``mul``, floor ``div``/``mod``, checked shifts,
casts) is asserted against an independently written formula here — the
reference runtime's *code* is never used as its own oracle.

The oracle rules (documented in ``pythsol.refrt``):

* any result outside the width's bounds  → ``(False, 1009)``  (on-chain abort);
* ``b == 0`` for div/mod                 → ``(False, 1010)``;
* signed ``min / -1`` and ``min % -1``   → ``(False, 1009)``;
* shift count ``s < 0 or s >= bits``     → ``(False, 1010)``;
* left shift dropping high bits          → ``(False, 1009)``;
* signed right shift is arithmetic, unsigned right shift logical;
* casts truncate raw bits then reinterpret in the target signedness.
"""

from __future__ import annotations

import os
from itertools import product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pythsol.refrt import (
    ERR_DIV_ZERO,
    ERR_OVERFLOW,
    INT_WIDTHS,
    SIGNED_WIDTHS,
    UNSIGNED_WIDTHS,
    bits_of,
    bounds,
    cast,
    checked_add,
    checked_div,
    checked_mod,
    checked_mul,
    checked_shl,
    checked_shr,
    checked_sub,
)

#: Examples per property test (TRD acceptance number). Override locally with
#: ``PYTHSOL_PROP_EXAMPLES=250 pytest tests/test_phase4_properties.py``.
EXAMPLES = int(os.environ.get("PYTHSOL_PROP_EXAMPLES", "10000"))

_W = pytest.mark.parametrize("width", INT_WIDTHS)

_FAIL_OVERFLOW = (False, ERR_OVERFLOW)
_FAIL_DIV_ZERO = (False, ERR_DIV_ZERO)


def _values(width: str):
    low, high = bounds(width)
    return st.integers(min_value=low, max_value=high)


def _mix(width: str):
    """Values biased toward the edges and zero (every division abort class)."""
    low, high = bounds(width)
    return st.one_of(
        st.just(low),
        st.just(high),
        st.just(0) if low <= 0 <= high else st.nothing(),
        st.integers(min_value=low, max_value=high),
    )


# ---------------------------------------------------------------------------
# add / sub / mul
# ---------------------------------------------------------------------------


@_W
@settings(max_examples=EXAMPLES, deadline=None)
@given(a=st.integers(), b=st.integers(), tweak=st.booleans())
def test_checked_add_matches_python_bounds(width: str, a: int, b: int, tweak: bool) -> None:
    """checked_add == (low <= a+b <= high ? (True, a+b) : (False, 1009))."""
    if tweak:  # exercise near-boundary values as well as arbitrary ones
        lo, hi = bounds(width)
        a = _clamp(a, lo, hi)
        b = _clamp(b, lo, hi)
    expected = _binop(width, a + b)
    assert checked_add(width, a, b) == expected


@_W
@settings(max_examples=EXAMPLES, deadline=None)
@given(a=st.integers(), b=st.integers(), tweak=st.booleans())
def test_checked_sub_matches_python_bounds(width: str, a: int, b: int, tweak: bool) -> None:
    if tweak:
        lo, hi = bounds(width)
        a = _clamp(a, lo, hi)
        b = _clamp(b, lo, hi)
    assert checked_sub(width, a, b) == _binop(width, a - b)


@_W
@settings(max_examples=EXAMPLES, deadline=None)
@given(a=st.integers(), b=st.integers(), tweak=st.booleans())
def test_checked_mul_matches_python_bounds(width: str, a: int, b: int, tweak: bool) -> None:
    if tweak:
        lo, hi = bounds(width)
        a = _clamp(a, lo, hi)
        b = _clamp(b, lo, hi)
    assert checked_mul(width, a, b) == _binop(width, a * b)


def _clamp(value: int, low: int, high: int) -> int:
    """Fold an arbitrary int into [low, high] to hit boundary neighborhoods."""
    span = high - low + 1
    return ((value - low) % span) + low


def _binop(width: str, value: int) -> tuple[bool, int]:
    low, high = bounds(width)
    if not low <= value <= high:
        return _FAIL_OVERFLOW
    return True, value


# ---------------------------------------------------------------------------
# floor div / mod
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width", INT_WIDTHS)
@settings(max_examples=EXAMPLES, deadline=None)
@given(data=st.data())
def test_floor_div_is_python_semantics(width: str, data) -> None:
    low, high = bounds(width)
    a = data.draw(_values(width))
    b = data.draw(_mix(width))
    if b == 0:
        assert checked_div(width, a, b) == _FAIL_DIV_ZERO
    elif width in SIGNED_WIDTHS and a == -(1 << (bits_of(width) - 1)) and b == -1:
        assert checked_div(width, a, b) == _FAIL_OVERFLOW
    else:
        q = a // b  # independent Python floor oracle
        expected = (False, ERR_OVERFLOW) if not low <= q <= high else (True, q)
        assert checked_div(width, a, b) == expected


@pytest.mark.parametrize("width", INT_WIDTHS)
@settings(max_examples=EXAMPLES, deadline=None)
@given(data=st.data())
def test_floor_mod_is_python_semantics(width: str, data) -> None:
    a = data.draw(_values(width))
    b = data.draw(_mix(width))
    if b == 0:
        assert checked_mod(width, a, b) == _FAIL_DIV_ZERO
    elif width in SIGNED_WIDTHS and a == bounds(width)[0] and b == -1:
        assert checked_mod(width, a, b) == _FAIL_OVERFLOW
    else:
        assert checked_mod(width, a, b) == (True, a % b)


# ---------------------------------------------------------------------------
# signed overflow edge class
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width", SIGNED_WIDTHS)
def test_min_div_minus_one_is_an_abort(width: str) -> None:
    """The classic signed-division overflow class: min(iN) / -1."""
    floor_min, _ = bounds(width)
    assert checked_div(width, floor_min, -1) == _FAIL_OVERFLOW
    assert checked_mod(width, floor_min, -1) == _FAIL_OVERFLOW
    # One below/above is fine.
    assert checked_div(width, floor_min + 1, -1) == (True, -(floor_min + 1))


# ---------------------------------------------------------------------------
# shifts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width", INT_WIDTHS)
@settings(max_examples=EXAMPLES, deadline=None)
@given(data=st.data())
def test_checked_shl_matches_python_and_aborts(width: str, data) -> None:
    bits = bits_of(width)
    a = data.draw(_values(width))
    s = data.draw(st.one_of(st.just(bits), st.just(-1), st.integers(0, bits * 2)))
    if s < 0 or s >= bits:
        assert checked_shl(width, a, s) == _FAIL_DIV_ZERO
    else:
        expected = _binop(width, a << s)
        assert checked_shl(width, a, s) == expected


@pytest.mark.parametrize("width", INT_WIDTHS)
@settings(max_examples=EXAMPLES, deadline=None)
@given(data=st.data())
def test_checked_shr_matches_python_arithmetic(width: str, data) -> None:
    bits = bits_of(width)
    a = data.draw(_values(width))
    s = data.draw(st.one_of(st.just(bits), st.just(-1), st.integers(0, bits * 2)))
    if s < 0 or s >= bits:
        assert checked_shr(width, a, s) == _FAIL_DIV_ZERO
    elif width in SIGNED_WIDTHS:
        assert checked_shr(width, a, s) == (True, a >> s)  # arithmetic on values
    else:
        assert checked_shr(width, a, s) == (True, a >> s)


def test_shr_sign_extension_is_arithmetic() -> None:
    """-1 >> anything (i64) stays -1; unsigned shr is logical."""
    assert checked_shr("i64", -1, 31) == (True, -1)
    assert checked_shr("i64", -16, 2) == (True, -4)
    assert checked_shr("u64", 2**64 - 16, 2) == (True, (2**64 - 16) >> 2)


# ---------------------------------------------------------------------------
# casts
# ---------------------------------------------------------------------------


_CAST_PAIRS = list(product(INT_WIDTHS, INT_WIDTHS))


@settings(max_examples=EXAMPLES, deadline=None)
@given(data=st.data())
def test_cast_truncates_then_reinterprets(data) -> None:
    """All 100 source→target pairs equal truncation of the *value*.

    Independent oracle: modulo-shift the mathematical value into the target's
    unsigned range, then subtract 2**bits when the sign bit is set — no
    reference-runtime helpers involved.
    """
    target, source = data.draw(st.sampled_from(_CAST_PAIRS))
    value = data.draw(_values(source))

    bits_t = bits_of(target)
    unsigned = value % (2**bits_t)
    if target in SIGNED_WIDTHS and unsigned >= 2 ** (bits_t - 1):
        unsigned -= 2**bits_t
    assert cast(target, source, value) == unsigned


@settings(max_examples=max(128, EXAMPLES // 10), deadline=None)
@given(data=st.data())
def test_cast_is_lossless_when_target_fits(data) -> None:
    """When the target width can hold the value, a cast must be identity."""
    for source, target in _CAST_PAIRS:
        low_s, high_s = bounds(source)
        low_t, high_t = bounds(target)
        shared_low, shared_high = max(low_s, low_t), min(high_s, high_t)
        if shared_low > shared_high:
            continue
        middle = st.integers(min_value=shared_low, max_value=shared_high)
        value = data.draw(middle)
        assert cast(target, source, value) == value


def test_cast_examples_match_c_semantics() -> None:
    """Pinned examples mirroring (T)x in C, including sign reinterpretation."""
    assert cast("i8", "i32", 321) == 65  # 321 & 0xFF -> 65
    assert cast("u8", "i32", -1) == 255
    assert cast("i64", "u64", 2**63) == -(2**63)  # reinterpretation
    assert cast("u128", "i128", -1) == 2**128 - 1
    assert cast("u64", "u16", 7) == 7  # widening is zero-extend
    assert cast("i8", "i64", -130) == 126  # two's complement wrap


def test_bounds_and_bits_tables() -> None:
    assert bounds("u8") == (0, 255)
    assert bounds("i8") == (-128, 127)
    assert bounds("u128")[1] == 2**128 - 1
    assert bounds("i128") == (-(2**127), 2**127 - 1)
    assert bits_of("i64") == 64
    assert set(UNSIGNED_WIDTHS) | set(SIGNED_WIDTHS) == set(INT_WIDTHS)
