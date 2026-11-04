---
title: Quickstart
description: Install PythSol, scaffold a counter, and run it in LiteSVM.
---

## Prerequisites

- Python **3.11+**. `pip install "pythsol[test]"` installs the compiler, CLI, and the `test` extra (pytest, LiteSVM, solders). A Git checkout is only needed to work on PythSol itself.
- For `pythsol build` only: the Solana SBF toolchain (`clang` targeting SBF). `pythsol doctor` prints exactly what is missing on your machine.

## Five commands

```bash
pip install "pythsol[test]"
pythsol init app --template counter
cd app
pythsol check programs/app.py
pythsol test
pythsol build
```

What each does:

1. **`pythsol init`** scaffolds `programs/app.py` (a full counter example)
   and `tests/test_program.py` — a LiteSVM pytest suite that uses only the
   PythSol test plugin helpers.
2. **`pythsol check`** is the parser/typechecker front door. Problems come
   back as stable codes with file, line, and column, for example
   `PS2004 ("hi" as a bare string value)` or
   `PS1003 (async/nested functions are not in the subset)`. Exit code is
   non-zero on diagnostics, so it fits CI.
3. **`pythsol test`** builds and runs the real bytecode in LiteSVM,
   in-process — no validator, no network, no RPC cost.
4. **`pythsol build`** runs the C emit and the Solana clang pipeline and
   writes `counter.c`, the `.so`, an Anchor-style IDL, a solders client,
   and a `manifest.json` next to your program.
5. **`pythsol doctor`** names the SBF platform tools required for step 4 —
   run it when clang cannot be found.

## What "cached" means

A second build of the same program prints `cache hit (skipped clang)` —
the build cache keys on the program source hash, so identical sources are
byte-identical artifacts and the compile is skipped. Source changes miss
the cache and rebuild.

## Deploying and money-safety moves

`pysol` is the same CLI. `pythsol deploy` defaults `--url` to `devnet` for
first deploys. Mainnet deploy and the faucet both refuse mainnet unless
you pass `--yes` to deploy. The faucet never runs on mainnet. After your
first deploy the CLI prints the program id and can `pythsol verify` the
on-chain bytecode against your local `.so`.

Next: read [Language](/docs/language) for the subset, or open the
[playground](/playground) to check and emit before installing anything.
