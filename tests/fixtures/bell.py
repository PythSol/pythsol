"""Bell: ring logs a Bumped event and stores the amount."""

from pythsol import Init, Mut, Signer, account, emit, event, instruction, u8, u64


@event
class Bumped:
    amount: u64


@account
class Bell:
    count: u64
    bump: u8


@instruction
def initialize(payer: Signer, bell: Init[Bell], bump: u8) -> None:
    bell.count = 0
    bell.bump = bump


@instruction
def ring(bell: Mut[Bell], amount: u64) -> None:
    bell.count = bell.count + amount
    emit(Bumped(amount))
