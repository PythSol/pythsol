"""A 2-of-3 treasury. Owners approve a payout; the PDA signs the transfer."""

from pythsol import (
    FixedArray,
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
class Treasury:
    creator: Pubkey
    owners: FixedArray[Pubkey, 3]
    approvals: u8
    threshold: u8
    paid: u64
    bump: u8


@error
class TreasuryError(ProgramError):
    """Errors returned by this program (6000 + index)."""

    Unauthorized = 100
    BadSlot = 101
    AlreadyApproved = 102
    NotApproved = 103
    Threshold = 104


@instruction
def initialize(
    authority: Signer,
    treasury: Seeds[Init[Treasury], "treasury"],  # type: ignore[name-defined]  # noqa: F821
    first: Pubkey,
    second: Pubkey,
    third: Pubkey,
    threshold: u8,
    bump: u8,
) -> None:
    require(threshold >= 1, TreasuryError.Threshold)
    require(threshold <= 3, TreasuryError.Threshold)
    treasury.creator = authority.key
    treasury.owners[0] = first
    treasury.owners[1] = second
    treasury.owners[2] = third
    treasury.approvals = 0
    treasury.threshold = threshold
    treasury.paid = 0
    treasury.bump = bump


@instruction
def fund(donor: Signer, treasury: Mut[Treasury], amount: u64) -> None:
    system_transfer(donor, treasury, amount)


@instruction
def approve(owner: Signer, treasury: Mut[Treasury], slot: u8) -> None:
    require(slot < 3, TreasuryError.BadSlot)
    require(treasury.owners[slot] == owner.key, TreasuryError.Unauthorized)
    mask: u8 = 1 << slot
    require((treasury.approvals & mask) == 0, TreasuryError.AlreadyApproved)
    treasury.approvals = treasury.approvals | mask


@instruction
def release(owner: Signer, treasury: Mut[Treasury], dest: Signer, slot: u8, amount: u64) -> None:
    require(slot < 3, TreasuryError.BadSlot)
    require(treasury.owners[slot] == owner.key, TreasuryError.Unauthorized)
    mask: u8 = 1 << slot
    require((treasury.approvals & mask) != 0, TreasuryError.NotApproved)
    count: u8 = 0
    for i in range(3):
        if ((treasury.approvals >> i) & 1) == 1:
            count = count + 1
    require(count >= treasury.threshold, TreasuryError.Threshold)
    treasury.approvals = 0
    system_transfer(treasury, dest, amount)
    treasury.paid = treasury.paid + amount
