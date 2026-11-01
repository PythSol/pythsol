---
title: Introduction
description: PythSol compiles a typed Python subset to a native Solana SBF program.
---

PythSol compiles a typed Python subset to a native SBF shared object. The
compiler parses the source with `ast`. It does not run it.

```bash
pip install -e ".[test]"
pythsol init app --template counter
cd app
pythsol check programs/app.py
pythsol test
pythsol build
```

`pythsol check` reports `PSxxxx` diagnostics. `pythsol build` writes C, an
`.so`, an Anchor-style IDL, a solders client, and a manifest. `pythsol test`
runs that program in LiteSVM.

The programs in `examples/` are counter, ledger, vault, and escrow.
`Vec[T, N]` is a fixed-capacity list. A data enum is a tag plus one reserved
scalar. `Vec` without a capacity is rejected. Compile to `.so` needs the SBF
tools on that machine. `pythsol serve` on loopback can compile.
`pythsol serve --public` checks and emits only.

The package version is `0.1.0`. This site is the static build in `dist/`.
It is not a PyPI release.
