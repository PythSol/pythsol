"""Cluster names and RPC URLs shared by deploy, faucet, and wallet."""

from __future__ import annotations

import os

__all__ = ["DEVNET_URL", "is_mainnet", "resolve_url"]

DEVNET_URL = "https://api.devnet.solana.com"
MAINNET_URL = "https://api.mainnet-beta.solana.com"
LOCALHOST_URL = "http://127.0.0.1:8899"
TESTNET_URL = "https://api.testnet.solana.com"

_ALIASES = {
    "devnet": DEVNET_URL,
    "localhost": LOCALHOST_URL,
    "localnet": LOCALHOST_URL,
    "mainnet": MAINNET_URL,
    "mainnet-beta": MAINNET_URL,
    "testnet": TESTNET_URL,
}

_MAINNET = {
    MAINNET_URL.rstrip("/").lower(),
    "https://api.mainnet.solana.com",
}


def resolve_url(value: str | None) -> str:
    """Turn a cluster name or URL into an RPC URL.

    An empty value uses ``PYSOL_RPC_URL`` or ``PYTHSOL_RPC_URL``, then devnet.
    """
    if value is None or value.strip() == "":
        env = os.environ.get("PYSOL_RPC_URL") or os.environ.get("PYTHSOL_RPC_URL")
        if env:
            return resolve_url(env)
        return DEVNET_URL
    key = value.strip()
    return _ALIASES.get(key.lower(), key)


def is_mainnet(value: str) -> bool:
    """True for mainnet aliases and the public mainnet RPC URL."""
    return resolve_url(value).rstrip("/").lower() in _MAINNET
