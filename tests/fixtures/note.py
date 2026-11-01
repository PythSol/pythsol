"""Note program: fixed-width Option[u64] (tag byte plus a reserved value)."""

from pythsol import Init, Mut, Option, Signer, account, instruction, u8, u64


@account
class Note:
    amount: Option[u64]
    seen: u64
    bump: u8


@instruction
def initialize(authority: Signer, note: Init[Note], bump: u8) -> None:
    note.amount = None
    note.seen = 0
    note.bump = bump


@instruction
def set_amount(authority: Signer, note: Mut[Note], amount: Option[u64]) -> None:
    note.amount = amount


@instruction
def apply(authority: Signer, note: Mut[Note], amount: Option[u64]) -> None:
    if amount.is_some:
        note.amount = amount.value
    else:
        note.amount = None


@instruction
def take(authority: Signer, note: Mut[Note]) -> None:
    note.seen = note.amount.value
