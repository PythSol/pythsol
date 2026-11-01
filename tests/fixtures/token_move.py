"""Move SPL tokens, Token-2022 tokens, or create an associated token account."""

from pythsol import (
    Signer,
    TokenAccount,
    TokenMint,
    ata_create,
    instruction,
    token2022_transfer,
    token_transfer,
    u64,
)


@instruction
def send(authority: Signer, src: TokenAccount, dest: TokenAccount, amount: u64) -> None:
    token_transfer(src, dest, authority, amount)


@instruction
def send2022(authority: Signer, src: TokenAccount, dest: TokenAccount, amount: u64) -> None:
    token2022_transfer(src, dest, authority, amount)


@instruction
def open_ata(payer: Signer, ata: TokenAccount, owner: Signer, mint: TokenMint) -> None:
    ata_create(payer, ata, owner, mint)
