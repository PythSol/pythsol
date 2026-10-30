# SPDX-License-Identifier: MIT
"""A minimal PythSol program: an owned counter.

`pythsol check programs/counter.py` must pass `mypy --strict` *and* the
PythSol front-end. `pythsol build` (Phase 3) compiles it to native SBF.
"""

from pythsol import (
    Init,
    Mut,
    ProgramError,
    Pubkey,
    Signer,
    account,
    error,
    instruction,
    require,
    u8,
    u64,
)


@account
class Counter:
    """The on-chain counter account layout."""

    authority: Pubkey
    count: u64
    bump: u8


@error
class CounterError(ProgramError):
    """Errors returned by this program (u32 codes)."""

    Unauthorized = 100
    Overflow = 101


@instruction
def initialize(authority: Signer, counter: Init[Counter], bump: u8) -> None:
    """Create and initialize the counter authority fields."""
    counter.authority = authority.key
    counter.count = 0
    counter.bump = bump


@instruction
def increment(authority: Signer, counter: Mut[Counter], by: u64) -> None:
    """Add `by` to the count; only the stored authority may call this."""
    require(counter.authority == authority.key, CounterError.Unauthorized)
    counter.count += by
