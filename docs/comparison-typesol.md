# PythSol and TypeSol

TypeSol (https://typesol.com/) compiles a TypeScript subset to native Solana SBF.
PythSol does the same job for a typed Python subset. The pipeline is the same
shape: typecheck, reject anything outside the subset, lower to C, clang
`-target sbf`, Anchor-style IDL, solders or TypeScript client.

This note is the gap list. It does not copy TypeSol's benchmark numbers.
Those figures are theirs, measured on their programs.

## What already matches

| Surface | TypeSol | PythSol |
|---|---|---|
| Language | TypeScript subset | Python subset |
| On-chain result | Native `.so`, no Rust | Native `.so`, no Rust |
| Checks | Signer, owner, discriminator, size, aliasing | Same, from the parameter types |
| Arithmetic | Checked, overflow aborts | Checked, codes 1009 and 1010 |
| Errors | `require` points at `file:line` | `require` points at `file:line` |
| IDL | Anchor-compatible | Anchor legacy spec 0.1.0 |
| Tests | LiteSVM, accounts by name | `pythsol test` and the pytest plugin |
| Build | `.so`, IDL, client, manifest | Same, plus a clang cache |
| Toolchain | Agave platform-tools clang | Same clang and `ld.lld` |

## Where PythSol is behind

Language and accounts:

- TypeSol accepts more account roles: `InitIfNeeded`, optional accounts, mints and token accounts as types, sysvars, and account groups. PythSol has `Signer`, `Mut`, `Init`, `Account`, and the constraint wrappers.
- TypeSol seeds can come from account fields and from another program. PythSol uses one literal seed plus the bump.
- TypeSol can return instruction data (up to 1024 bytes). PythSol instructions return `None`.
- TypeSol has `u256` for locals, plus `mulDiv` and `isqrt`. PythSol stops at `u128` / `i128` in accounts and arguments.
- TypeSol has variable Borsh strings. PythSol has `FixedString[N]` and `Vec[T, N]`. A `Vec` with no capacity is rejected so later fields stay at fixed offsets.
- TypeSol's escrow example moves SPL tokens. PythSol's escrow example moves lamports. Token transfer exists as `token_transfer`, not as that example.
- List comprehensions are rejected. TypeSol lowers more expression forms, including some callbacks in its later versions.

Product:

- TypeSol publishes `@typesol/cli` and a hosted docs site. PythSol is version 0.1.0 and is not on PyPI. The docs site builds locally (`web/docs/dist`).
- TypeSol shows compute units and binary size against Anchor, native Rust, and Pinocchio for the same instructions. PythSol does not have that comparison suite, so this page does not claim those ratios.
- TypeSol ports a set of official Solana example programs. PythSol ships four programs: counter, ledger, vault, and escrow.
- TypeSol's site explains one instruction as six generated checks beside the C. The PythSol playground was a bare editor. The playground layout now follows that split, in a light theme.

## UI

TypeSol's page is light-on-content and product-shaped: a headline, the program you write, the C the compiler writes, then benchmarks. The PythSol playground uses that split.

Colors stay light. Python blue `#306998` and yellow `#FFD43B` are the main colors. Solana purple `#9945FF` and mint `#14F195` are small accents. There is no dark theme.

## What we will not copy

- TypeSol's published compute-unit table. Measuring it is a separate benchmark project.
- A token or a mainnet claim. PythSol does not ship a token.
- In-browser SBF compile. Check and emit can run on a server. Clang stays on a machine with the platform tools.
