"""`pythsol faucet` — request devnet SOL. Mainnet is refused."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from pythsol.cli.cluster import is_mainnet, resolve_url
from pythsol.cli.rpc import RpcError, post_json
from pythsol.compiler.toolchain import default_solana_keypair

_LAMPORTS = 1_000_000_000
_MAX_SOL = 5.0


def _pubkey_from_file(path: Path) -> str:
    try:
        from solders.keypair import Keypair
    except ImportError:
        click.echo(
            "error: solders is required to read a keypair. pip install 'pythsol[test]'",
            err=True,
        )
        sys.exit(1)
    return str(Keypair.from_json(path.read_text(encoding="utf-8")).pubkey())


@click.command(name="faucet")
@click.option("--amount", default=1.0, show_default=True, help="SOL to request (max 5).")
@click.option("--url", default=None, help="Cluster name or RPC URL. Default: devnet.")
@click.option("--pubkey", default=None, help="Base58 address. Default: the local keypair.")
@click.option(
    "--keypair",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Keypair file whose address receives the airdrop.",
)
def faucet(amount: float, url: str | None, pubkey: str | None, keypair: Path | None) -> None:
    """Request an airdrop. Devnet rate limits return a faucet link."""
    cluster = resolve_url(url)
    if is_mainnet(cluster):
        click.echo("error: faucet refuses mainnet", err=True)
        sys.exit(1)
    if amount <= 0 or amount > _MAX_SOL:
        click.echo(f"error: --amount must be between 0 and {_MAX_SOL:g} SOL", err=True)
        sys.exit(2)
    if pubkey is None:
        path = keypair or default_solana_keypair()
        if not path.is_file():
            click.echo(f"error: keypair not found at {path}", err=True)
            sys.exit(1)
        pubkey = _pubkey_from_file(path)
    lamports = round(amount * _LAMPORTS)
    try:
        body = post_json(cluster, "requestAirdrop", [pubkey, lamports])
    except RpcError as exc:
        message = str(exc)
        click.echo(f"error: {message}", err=True)
        if "rate" in message.lower() or "429" in message or "limit" in message.lower():
            click.echo("Rate-limited. Use https://faucet.solana.com", err=True)
        sys.exit(1)
    signature = body.get("result")
    click.echo(f"Airdropped {amount:g} SOL (sig {signature}).")
    sys.exit(0)
