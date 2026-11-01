"""`pythsol docs` — print the offline reference."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import click

_REFERENCE = """\
PythSol offline reference

  pythsol check PROGRAM.py     type-check (no clang)
  pythsol build PROGRAM.py     native SBF .so, IDL, client, manifest
  pythsol test                 build, then pytest on LiteSVM
  pythsol init DIR --template counter|ledger|vault|escrow
  pythsol idl PROGRAM.py       IDL only
  pythsol client PROGRAM.py -o client.py
  pythsol client program.json -o client.py
  pythsol port program.json -o sketch.py
  pythsol deploy --dry-run     print `solana program deploy` (mainnet needs --yes)
  pythsol faucet --amount 1    devnet airdrop (mainnet refused)
  pythsol wallet new --outfile id.json
  pythsol verify --left a.so --right b.so
  pythsol profile --logs run.log
  pythsol idl-publish --address <ID> --dry-run
  pythsol cpi PROGRAM.py -o cpi.py
  pythsol serve                local playground on 127.0.0.1:8765
                               check, emit, and compile (.so if clang is installed)

A second build of the same program prints `cache hit (skipped clang)`.
Tests use the fixtures svm, program, payer, accounts, and send.
Vec[T, N] is a fixed capacity. A data enum is `Name: u64` with the payload reserved.
Vec[T] without N is rejected. The hosted Pyodide playground is not in this
build; `pythsol serve` checks, emits, and compiles on your machine.
"""


def _repo_doc() -> Path | None:
    cwd = Path.cwd() / "docs" / "architecture.md"
    if cwd.is_file():
        return cwd
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "docs" / "architecture.md"
        if candidate.is_file():
            return candidate
    return None


@click.command(name="docs")
@click.option("--open", "open_browser", is_flag=True, help="Open architecture.md if it is on disk.")
def docs(open_browser: bool) -> None:
    """Print the offline command reference."""
    click.echo(_REFERENCE, nl=False)
    found = _repo_doc()
    if found is not None:
        click.echo(f"architecture: {found}")
        if open_browser:
            webbrowser.open(found.as_uri())
    sys.exit(0)
