"""`pythsol wallet` — new keypair, address, and balance.

The keypair file is the Solana JSON array (64 bytes). It is written mode
``0600``. The secret is not printed unless ``--show-secret`` is set.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import click

from pythsol.cli.cluster import resolve_url
from pythsol.cli.rpc import RpcError, post_json
from pythsol.compiler.toolchain import default_solana_keypair


def restrict_private_file(path: Path) -> None:
    """Owner read/write only. On Windows, chmod is the best the CRT offers."""
    os.chmod(path, 0o600)


def _keypair_type() -> Any:
    try:
        from solders.keypair import Keypair
    except ImportError:
        click.echo("error: solders is required. pip install 'pythsol[test]'", err=True)
        sys.exit(1)
    return Keypair


def _load(path: Path) -> Any:
    return _keypair_type().from_json(path.read_text(encoding="utf-8"))


def _lamports(body: dict[str, object]) -> int:
    result = body.get("result")
    if isinstance(result, dict) and "value" in result:
        return int(result["value"])
    if isinstance(result, int):
        return result
    raise RpcError("balance response had no value")


@click.group(name="wallet")
def wallet() -> None:
    """Create a keypair, print its address, or read a balance."""


@wallet.command("new")
@click.option(
    "--outfile",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Where to write the keypair JSON.",
)
@click.option("--force", is_flag=True, help="Overwrite an existing file.")
@click.option("--show-secret", is_flag=True, help="Print the keypair JSON. Off by default.")
def wallet_new(outfile: Path, force: bool, show_secret: bool) -> None:
    """Write a new keypair file."""
    if outfile.exists() and not force:
        click.echo(f"error: {outfile} already exists (pass --force to overwrite)", err=True)
        sys.exit(1)
    outfile.parent.mkdir(parents=True, exist_ok=True)
    keypair = _keypair_type()()
    text = keypair.to_json()
    if not text.endswith("\n"):
        text += "\n"
    outfile.write_text(text, encoding="utf-8", newline="\n")
    restrict_private_file(outfile)
    click.echo(f"wrote {outfile}")
    click.echo(str(keypair.pubkey()))
    if show_secret:
        click.echo(text, nl=False)
    sys.exit(0)


@wallet.command("address")
@click.option(
    "--keypair",
    "keypair_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
@click.option("--show-secret", is_flag=True, help="Print the keypair JSON. Off by default.")
def wallet_address(keypair_path: Path | None, show_secret: bool) -> None:
    """Print the public key. The secret stays in the file."""
    path = keypair_path or default_solana_keypair()
    if not path.is_file():
        click.echo(f"error: keypair not found at {path}", err=True)
        sys.exit(1)
    keypair = _load(path)
    click.echo(str(keypair.pubkey()))
    if show_secret:
        click.echo(keypair.to_json())
    sys.exit(0)


@wallet.command("balance")
@click.option("--url", default=None, help="Cluster name or RPC URL. Default: devnet.")
@click.option("--pubkey", default=None, help="Base58 address. Default: the local keypair.")
@click.option(
    "--keypair",
    "keypair_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
def wallet_balance(url: str | None, pubkey: str | None, keypair_path: Path | None) -> None:
    """Print the SOL balance of a public key."""
    if pubkey is None:
        path = keypair_path or default_solana_keypair()
        if not path.is_file():
            click.echo(f"error: keypair not found at {path}", err=True)
            sys.exit(1)
        pubkey = str(_load(path).pubkey())
    cluster = resolve_url(url)
    try:
        body = post_json(cluster, "getBalance", [pubkey])
        lamports = _lamports(body)
    except RpcError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    sol = lamports / 1_000_000_000
    click.echo(f"{sol:.4f} SOL ({lamports} lamports)")
    sys.exit(0)
