"""Till: a helper adds one before the count is stored."""

from pythsol import Init, Mut, Signer, account, instruction, u8, u64


@account
class Till:
    count: u64
    bump: u8


def fee(amount: u64) -> u64:
    extra: u64 = 1
    return amount + extra


def add_one(till: Mut[Till]) -> None:
    till.count = till.count + 1


@instruction
def initialize(payer: Signer, till: Init[Till], bump: u8) -> None:
    till.count = 0
    till.bump = bump


@instruction
def apply(till: Mut[Till], by: u64) -> None:
    till.count = fee(by)


@instruction
def step(till: Mut[Till]) -> None:
    add_one(till)
