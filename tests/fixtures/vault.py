"""Vault: custom PDA seed, has-one, address, owner, and close."""

from pythsol import (
    Address,
    CloseTo,
    HasOne,
    Init,
    Mut,
    Owner,
    Pubkey,
    Seeds,
    Signer,
    account,
    instruction,
    u8,
    u64,
)


@account
class Vault:
    authority: Pubkey
    balance: u64
    bump: u8


@instruction
def initialize(payer: Signer, vault: Seeds[Init[Vault], "box"], bump: u8) -> None:  # noqa: F821
    vault.authority = payer.key
    vault.balance = 0
    vault.bump = bump


@instruction
def note(
    authority: Signer, vault: HasOne[Mut[Vault], "authority"], amount: u64  # noqa: F821
) -> None:
    vault.balance = amount


@instruction
def retarget(vault: Mut[Vault], who: Pubkey) -> None:
    vault.authority = who


@instruction
def prove(vault: Address[Mut[Vault], expected], expected: Pubkey) -> None:  # noqa: F821
    vault.balance = vault.balance


@instruction
def own(authority: Signer, vault: Owner[Mut[Vault], authority]) -> None:  # noqa: F821
    vault.balance = vault.balance


@instruction
def close(authority: Signer, vault: CloseTo[Mut[Vault], authority]) -> None:  # noqa: F821
    vault.balance = vault.balance
