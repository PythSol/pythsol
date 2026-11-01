---
title: CLI
description: Commands shipped with the pythsol and pysol scripts.
---

| Command | What it does |
|---|---|
| `doctor` | Python, platform-tools, Solana CLI |
| `check` | Front-end diagnostics. `--json` prints `ok` and `diagnostics` |
| `build` | `.so`, IDL, client, manifest. Cache hit skips clang |
| `test` | Build, then pytest on LiteSVM |
| `init` | `pysol.toml`, program, and `tests/test_program.py` |
| `idl` | IDL JSON, no clang |
| `idl-publish` | Writes the IDL and prints `anchor idl init` |
| `client` | Solders builders from `.py` or `.json` |
| `cpi` | Same builders. Not an on-chain invoke |
| `port` | Skeleton from an IDL. Bodies are `pass` |
| `deploy` | `solana program deploy`. `--dry-run` only prints |
| `faucet` | Devnet `requestAirdrop`, at most 5 SOL |
| `wallet` | New keypair, address, or balance |
| `verify` | Exit 0 on a sha256 match, 3 on a mismatch |
| `profile` | Parses `consumed N of` lines from a log |
| `serve` | Loopback check and emit |
| `docs` | Offline command list |

`idl` stays a command that takes a program path. `idl-publish` is separate.
Deploy refuses mainnet without `--yes`, including a dry run.
