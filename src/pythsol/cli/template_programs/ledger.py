"""Ledger program: fixed slots, deposits, and a checked running total."""

from pythsol import (
    FixedArray,
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
class Ledger:
    authority: Pubkey
    total: u64
    slots: FixedArray[u64, 4]  # type: ignore[valid-type]
    bump: u8


@error
class LedgerError(ProgramError):
    """Errors returned by this program (6000 + index)."""

    Unauthorized = 100
    BadSlot = 101
    Insufficient = 102


@instruction
def initialize(authority: Signer, ledger: Init[Ledger], bump: u8) -> None:
    ledger.authority = authority.key
    ledger.total = 0
    ledger.bump = bump


@instruction
def deposit(authority: Signer, ledger: Mut[Ledger], slot: u8, amount: u64) -> None:
    require(ledger.authority == authority.key, LedgerError.Unauthorized)
    require(slot < 4, LedgerError.BadSlot)
    ledger.slots[slot] = ledger.slots[slot] + amount
    ledger.total = ledger.total + amount


@instruction
def apply(authority: Signer, ledger: Mut[Ledger], amount: u64, mode: u8) -> None:
    require(ledger.authority == authority.key, LedgerError.Unauthorized)
    if mode == 0:
        ledger.total = ledger.total + amount
    else:
        require(ledger.total >= amount, LedgerError.Insufficient)
        ledger.total = ledger.total - amount


@instruction
def fill(authority: Signer, ledger: Mut[Ledger], value: u64) -> None:
    require(ledger.authority == authority.key, LedgerError.Unauthorized)
    total: u64 = 0
    for i in range(4):
        ledger.slots[i] = value
        total = total + value
    ledger.total = total
