---
title: Testing
description: pythsol test and the pytest fixtures.
---

See `docs/guides/testing.md` in the repository for the full note. Short form:

- Fixtures: `svm`, `program`, `payer`, `accounts`, `send`.
- `program.initialize(authority=payer)` derives the PDA and the bump.
- `program.fetch("Counter", pubkey)` uses the generated decoder.
- `expect_error` asserts a custom error and lets other exceptions through.
- `--localnet` deploys when the Solana CLI exists. Tests still use LiteSVM.

Template tests for counter, ledger, vault, and escrow live in
`src/pythsol/cli/templates.py` and are copied by `pythsol init`.
