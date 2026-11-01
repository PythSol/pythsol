"""Spot: a fixed Point packed inline inside the account."""

from pythsol import Init, Mut, Signer, account, instruction, struct, u8, u64


@struct
class Point:
    x: u64
    y: u64


@account
class Spot:
    origin: Point
    bump: u8


@instruction
def initialize(payer: Signer, spot: Init[Spot], bump: u8) -> None:
    spot.origin.x = 0
    spot.origin.y = 0
    spot.bump = bump


@instruction
def place(spot: Mut[Spot], x: u64, y: u64) -> None:
    spot.origin.x = x
    spot.origin.y = y


@instruction
def nudge(spot: Mut[Spot], by: u64) -> None:
    spot.origin.x += by
