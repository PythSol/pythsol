---
title: Troubleshooting
description: Toolchain, cache, and cluster mistakes.
---

`PS4010` means clang for SBF was not found. Set `PYTHSOL_SBF_SDK` to a
platform-tools directory, or install the Agave tools. `pythsol doctor`
prints the check.

`pythsol test` exits 1 with `pip install 'pythsol[test]'` when pytest is
missing, and exits 2 when there is no `pysol.toml` and no `--program`.

A cache hit that you do not want: `PYTHSOL_NO_CACHE=1`. The cache key
includes the generated C, so a source change is a miss.

Faucet errors that mention a rate limit point at `https://faucet.solana.com`.
The command refuses mainnet before any HTTP call. Deploy on mainnet without
`--yes` exits 1 before the build.

`pythsol serve --host 0.0.0.0` exits 2. The playground is loopback only.
