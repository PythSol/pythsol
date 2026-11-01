# Project status

This is the hostable surface. A checked box is in the tree and covered by a test or a local build. An empty box is not done.

The next agent should read **`docs/HANDOFF.md`** (goal, built, left, traps).
A short pointer is `AGENTS.md` at the repo root.

## Working now

- [x] Typed Python subset, checked with `pythsol check`
- [x] Native SBF `.so`, IDL, and solders client from `pythsol build`
- [x] LiteSVM tests for counter, ledger, vault, escrow, and the purse fixture
- [x] `pythsol test`, build cache, wallet, faucet, deploy, port, verify, profile
- [x] `Vec[T, N]`, fixed-width data enums, PDA lamport moves
- [x] Local playground: check, emit, and compile on loopback
- [x] Public playground: `pythsol serve --public` checks and emits, and does not compile
- [x] Playground layout follows the TypeSol split (source, then compiler output) in a light Python and Solana palette. See `docs/comparison-typesol.md`
- [x] Docs site builds with `npm run build` in `web/docs` (static files in `dist/`)
- [x] Windows is a supported developer machine for the compiler and LiteSVM

## Not done

- [ ] Unbounded `Vec[T]` (a value with no capacity would move later account fields)
- [ ] In-browser SBF compile (no WASM clang in this tree)
- [ ] A second compiler IR
- [ ] Translated docs
- [ ] List comprehensions
- [ ] Twenty gallery examples (four programs are real: counter, ledger, vault, escrow)
- [ ] Published audit
- [ ] PyPI release (version is still 0.1.0)
- [ ] Lighthouse score for the docs site

## Hosting

Static docs: from `web/docs`, run `npm install` and `npm run build`. Serve the `dist/` directory.

Playground on a server: `pythsol serve --public --host 0.0.0.0 --port 8765`. That process parses source. It does not run user code and it does not call clang. Compile stays on a machine where you run `pythsol serve` without `--public`.
