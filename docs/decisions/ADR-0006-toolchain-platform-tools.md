# ADR-0006 — SBF backend: Agave/Anza platform-tools clang + lld

- **Status:** accepted
- **Date:** 2026-10-30
- **Deciders:** PythSol contributors

## Context

TRD §4 recommends Option B: Python subset → C → clang (Agave platform-tools) → SBF.
Phase 1 must answer **how** we locate and call that toolchain, and what to do when
it is not runnable on the developer's box.

## Decision

1. **Use the official `platform-tools` distribution** from
   https://github.com/anza-xyz/platform-tools/releases (tag ≥ `v1.58` implies
   LLVM 22 and the `sbfv3` target).
2. Discover it in this order:
   1. `--sdk DIR` argument (Phase 2),
   2. `PYTHSOL_SBF_SDK` env var (accepted: `PYTHSOL_SBF_SDK`, legacy `PYSOL_SBF_SDK`),
   3. default install path (`~/.cache/solana/**`).
3. Call **clang** for `compile` and **ld.lld** for `link`, with flags derived
   verbatim from `rustc_target/src/spec/base/sbf_base.rs` in the `anza-xyz/rust`
   source (linker script is pinned inline in `toolchain.py`).
4. Local Windows performance: `platform-tools-windows-x86_64` ships **unsigned**
   `clang.exe`, and enterprise Windows setups (WDAC) refuse to execute it.
   **Consequence:** local SBF compilation is CI-authoritative (Linux runner).
   `pythsol doctor` reports this instead of silently "succeeding".

## Verification

- `platform-tools v1.58` release asset exists for Linux/macOS/Windows (checked via
  GitHub API on 2026-10-30).
- `ld.lld.exe` and `llvm-objdump.exe` from that bundle run on Windows in this
  workspace; `clang.exe` does **not** (blocked by WDAC). Tracked as a local-only
  limitation, not a product limitation.
- Linker scripts and flag set are the exact strings from
  `anza-xyz/rust@3175de2636` `compiler/rustc_target/src/spec/base/sbf_base.rs`
  (fetched, then trimmed into `toolchain.py`).

## Consequences

- Phase 1 acceptance that "CI compiles the spike .so and runs it in LiteSVM"
  is enforced in the `toolchain` GitHub Actions job; local Windows dev still gets
  `doctor` and all pure-Python units tests.
- Reproducibility is a Phase 3/4 concern (pinned `SOURCE_DATE_EPOCH`).
- The same `toolchain.py` is a port-forwarding free isomorphism between the OS
  shapes so Phase 3 `pythsol emit-c` keeps working both ways.
