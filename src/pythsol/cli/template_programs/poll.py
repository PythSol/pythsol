"""A four-voter poll. Each allowlisted key votes once; the tally lives on chain."""

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
    u32,
)


@account
class Poll:
    authority: Pubkey
    voters: FixedArray[Pubkey, 4]
    voted: u8
    yes: u32
    no: u32
    bump: u8


@error
class PollError(ProgramError):
    """Errors returned by this program (6000 + index)."""

    BadSlot = 100
    Unauthorized = 101
    AlreadyVoted = 102


@instruction
def initialize(
    authority: Signer,
    poll: Seeds[Init[Poll], "poll"],  # type: ignore[name-defined]  # noqa: F821
    first: Pubkey,
    second: Pubkey,
    third: Pubkey,
    fourth: Pubkey,
    bump: u8,
) -> None:
    poll.authority = authority.key
    poll.voters[0] = first
    poll.voters[1] = second
    poll.voters[2] = third
    poll.voters[3] = fourth
    poll.voted = 0
    poll.yes = 0
    poll.no = 0
    poll.bump = bump


@instruction
def vote(voter: Signer, poll: Mut[Poll], slot: u8, choice: bool) -> None:
    require(slot < 4, PollError.BadSlot)
    require(poll.voters[slot] == voter.key, PollError.Unauthorized)
    mask: u8 = 1 << slot
    require((poll.voted & mask) == 0, PollError.AlreadyVoted)
    poll.voted = poll.voted | mask
    if choice:
        poll.yes = poll.yes + 1
    else:
        poll.no = poll.no + 1
