"""A PDA purse. ``fund`` takes lamports in. ``pay`` sends them out with a PDA signature."""

from pythsol import (
    Init,
    Mut,
    ProgramError,
    Pubkey,
    Seeds,
    Signer,
    Vec,
    account,
    error,
    instruction,
    require,
    system_transfer,
    u8,
    u64,
)


@account
class Purse:
    authority: Pubkey
    bump: u8
    paid: u64
    notes: Vec[u64, 4]


@error
class PurseError(ProgramError):
    Unauthorized = 100


@instruction
def initialize(
    authority: Signer,
    purse: Seeds[Init[Purse], "purse"],  # type: ignore[name-defined]  # noqa: F821
    bump: u8,
) -> None:
    purse.authority = authority.key
    purse.bump = bump
    purse.paid = 0


@instruction
def fund(authority: Signer, purse: Mut[Purse], amount: u64) -> None:
    system_transfer(authority, purse, amount)


@instruction
def pay(authority: Signer, purse: Mut[Purse], dest: Signer, amount: u64) -> None:
    require(purse.authority == authority.key, PurseError.Unauthorized)
    system_transfer(purse, dest, amount)
    purse.paid = purse.paid + amount
    n: u64 = len(purse.notes)
    purse.notes[n] = amount
