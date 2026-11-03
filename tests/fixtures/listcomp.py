"""A comprehension fills a FixedArray, then the array is stored and summed."""

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
    u8,
    u64,
)


@account
class Board:
    authority: Pubkey
    values: FixedArray[u64, 4]
    total: u64
    bump: u8


@error
class BoardError(ProgramError):
    """Errors returned by this program (6000 + index)."""

    Unauthorized = 100


@instruction
def initialize(
    authority: Signer,
    board: Seeds[Init[Board], "board"],  # type: ignore[name-defined]  # noqa: F821
    bump: u8,
) -> None:
    board.authority = authority.key
    board.bump = bump
    board.total = 0


@instruction
def fill(authority: Signer, board: Mut[Board], base: u64) -> None:
    require(board.authority == authority.key, BoardError.Unauthorized)
    values: FixedArray[u64, 4] = [base + i for i in range(4)]
    total: u64 = 0
    for i in range(4):
        board.values[i] = values[i]
        total = total + values[i]
    board.total = total
