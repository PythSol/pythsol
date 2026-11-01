---
title: Quickstart
description: Install PythSol, scaffold a counter, and run it in LiteSVM.
---

```bash
pip install -e ".[test]"
pythsol init app --template counter
cd app
pythsol check programs/app.py
pythsol test
pythsol build
```

`pythsol test` needs pytest and solders from the `test` extra, and the SBF
platform tools (`pythsol doctor` names them). A second build of the same
program prints `cache hit (skipped clang)`.

`pysol` is the same CLI. Mainnet deploy and the faucet both refuse mainnet
unless you pass `--yes` to deploy. The faucet never runs on mainnet.
