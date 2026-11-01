"""Gate program: a one-byte unit enum on an account and in instruction data."""

from pythsol import Init, Mut, Signer, account, enum, instruction, u8


@enum
class Status:
    """Open or closed."""

    Open = 0
    Closed = 1


@account
class Gate:
    status: Status
    bump: u8


@instruction
def initialize(authority: Signer, gate: Init[Gate], bump: u8) -> None:
    gate.status = Status.Open
    gate.bump = bump


@instruction
def apply(authority: Signer, gate: Mut[Gate], status: Status) -> None:
    match status:
        case Status.Open:
            gate.status = Status.Open
        case Status.Closed:
            gate.status = Status.Closed
