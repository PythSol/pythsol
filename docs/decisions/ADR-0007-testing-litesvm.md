# ADR-0007 — Testing stack: LiteSVM through `solders`

- **Status:** accepted
- **Date:** 2026-10-30
- **Deciders:** PythSol contributors

## Context

TRD §3 assumed a standalone PyPI package `litesvm` for in-process testing.
PRD §8.2 marks the assumption [ASSUMPTION]. Phase 1 needs to **verify** whether it
actually exists and is maintained.

## Decision

**Use `solders.litesvm`** (the LiteSVM Python bindings that ship inside
`solders`), not a separate package.

- `solders` 0.29.0 is the current release and *does* expose
  `from solders.litesvm import LiteSVM`, `add_program(pubkey, bytes)`,
  `airdrop`, `send_transaction`, `get_account`.
- The `litesvm` PyPI name is a 1 KB placeholder from 2024 that is **not**
  the maintained binding — do not depend on it.
- Runtime deps for the `pythsol` wheel stay minimal: `click`.
  Testing extra `pythsol[test]` brings `pytest`, `pytest-cov`, `solders`, `solana`.

Fix commands are reported through ADR-0006 doctor; the test harness itself is
pure Python and needs no extra tool.

## Verification

- `pip install solders==0.29.0` (via `uv pip install --python .venv/Scripts/python -e . test/dev`)
  and `from solders.litesvm import LiteSVM` succeeds in `.venv/Scripts/python`.
- `NotFoundError: ModuleNotFoundError: No module 'litesvm'` is resolved by using
  `solders`'s bindings, which the unit tests prove.
- `LiteSVM()` object supports `latest_blockhash()` and `send_transaction(tx)`,
  used by `Spikes/python/cn_litesvm_hello.py`.

## Consequences

- Phases 3–5 build on this import path with no change.
- If `solders` later renames, `pythsol/testing` is the only layer to adjust.
- `solana` (RPC) is still needed for Phase 6 deploy/faucet helpers.
