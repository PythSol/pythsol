"""Escrow: one PDA deal funded in lamports.

The seed is the literal ``escrow``, so a program has one open deal. ``make``
creates it and transfers ``amount`` in. ``take`` pays the maker, then closes
the account to the taker. ``cancel`` closes it back to the maker. A
PDA-signed transfer is not available; closing the account is what returns
the escrowed lamports.
"""

from pythsol import (
    CloseTo,
    Init,
    Mut,
    ProgramError,
    Pubkey,
    Seeds,
    Signer,
    account,
    error,
    instruction,
    require,
    system_transfer,
    u8,
    u64,
)


@account
class Escrow:
    maker: Pubkey
    taker: Pubkey
    amount: u64
    bump: u8


@error
class EscrowError(ProgramError):
    """Errors returned by this program (6000 + index)."""

    Unauthorized = 100


@instruction
def make(
    maker: Signer,
    escrow: Seeds[Init[Escrow], "escrow"],  # type: ignore[name-defined]  # noqa: F821
    taker: Pubkey,
    bump: u8,
    amount: u64,
) -> None:
    escrow.maker = maker.key
    escrow.taker = taker
    escrow.amount = amount
    escrow.bump = bump
    system_transfer(maker, escrow, amount)


@instruction
def take(
    taker: Signer,
    maker: Signer,
    escrow: CloseTo[Mut[Escrow], taker],  # type: ignore[name-defined]  # noqa: F821
    price: u64,
) -> None:
    require(escrow.taker == taker.key, EscrowError.Unauthorized)
    require(escrow.maker == maker.key, EscrowError.Unauthorized)
    system_transfer(taker, maker, price)


@instruction
def cancel(
    maker: Signer,
    escrow: CloseTo[Mut[Escrow], maker],  # type: ignore[name-defined]  # noqa: F821
) -> None:
    require(escrow.maker == maker.key, EscrowError.Unauthorized)
