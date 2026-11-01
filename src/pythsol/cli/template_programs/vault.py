"""Vault: a PDA that holds lamports for one authority.

``deposit`` moves lamports in with ``system_transfer``. ``close`` checks the
authority, then returns every lamport on the account. The PDA seed is the
literal ``vault`` (one seed, plus the bump).
"""

from pythsol import (
    CloseTo,
    HasOne,
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
class Vault:
    authority: Pubkey
    balance: u64
    bump: u8


@error
class VaultError(ProgramError):
    """Errors returned by this program (6000 + index)."""

    Unauthorized = 100


@instruction
def initialize(
    authority: Signer,
    vault: Seeds[Init[Vault], "vault"],  # type: ignore[name-defined]  # noqa: F821
    bump: u8,
) -> None:
    vault.authority = authority.key
    vault.balance = 0
    vault.bump = bump


@instruction
def deposit(
    authority: Signer,
    vault: HasOne[Mut[Vault], "authority"],  # type: ignore[name-defined]  # noqa: F821
    amount: u64,
) -> None:
    system_transfer(authority, vault, amount)
    vault.balance += amount


@instruction
def close(
    authority: Signer,
    vault: CloseTo[Mut[Vault], authority],  # type: ignore[name-defined]  # noqa: F821
) -> None:
    require(vault.authority == authority.key, VaultError.Unauthorized)
