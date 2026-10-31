# Changelog

PythSol follows Keep a Changelog; before 1.0 every breaking change is listed under **Breaking**.

## [0.1.0] — 2026-10-30
### Added
- Phase 3 — compiler back-end: `compiler/model.py` (IR-free `ProgramModel` with Anchor discriminators/packed Borsh layouts/`6000 + index` error codes), `compiler/emit.py` (C emitter lowering role checks, PDAs, System CPIs, `require`, checked arithmetic, dispatch table), `compiler/pipeline.py` (`emit_program`, `PS4xxx`/`PS5xxx` diagnostics), and `compiler/idl.py` (deterministic Anchor-legacy IDL + structural validator).
- Phase 3 — `pythsol build PROGRAM.py`: native SBF `.so` + generated C + IDL + `manifest.json` (sha256 hashes, toolchain info); byte-deterministic output verified by two-build tests.
- Phase 3 — the SBF runtime `src/pythsol/runtime/pythsol_rt.h`: zero-copy input decoder, Borsh readers/writers, checked arithmetic, PDA verification with the `ProgramDerivedAddress` domain suffix, C-ABI `sol_invoke_signed_c` CPI wrappers, and `rt_fail_log` `(file:line)` attribution — all pinned by ADR-0010 after empirical verification (LiteSVM + agave 1.18.26 sources).
- Phase 3 — acceptance harness `tests/test_phase3_litesvm.py`: counter initialize → increment(5) = 5; unauthorized increment fails `Custom(6000)` with `(counter.py:51)` log; overflow increment aborts at `(counter.py:52)` with no side effects. Plus model/IDL/emit/build unit and negative suites (PS4001/PS5003).
- Phase 0 — repository skeleton, Apache-2.0 license, contributing/code of conduct/security docs, [ADRs](docs/decisions/), `pyproject.toml` with hatchling/ruff/mypy, GitHub Actions `lint` + `unit` CI.
- Phase 1 — `pythsol.compiler.toolchain`: Agave/Anza platform-tools discovery (`PYTHSOL_SBF_SDK`, default cache path), sbpf compile/link flag helpers derived from `anza-xyz/rust@3175de2636 sbf_base.rs`, `compile_to_sbf` helper, plus `pythsol doctor` (Python, platform-tools, clang/lld sanity, `solana` CLI, `cargo-build-sbf`, keypair presence, optional RPC check) with `--json` and fix commands.
- Phase 1 — SBF spike C source at `Spikes/c/hello.c` and LiteSVM runner `Spikes/python/cn_litesvm_hello.py` gated behind the `toolchain` pytest marker.
- Phase 2 — compiler front-end pipeline `parse → subset → resolve → typecheck` in `src/pythsol/compiler/`, each stage emitting positioned `PSxxxx` diagnostics (`PS1000`–`PS3001`, `PS9000` internal-error guard). Random-AST fuzzing (`tests/test_phase2_fuzz.py`) proves stages answer every malformed input with diagnostics, never exceptions.
- Phase 2 — `pythsol check PROGRAM.py` CLI (exit codes 0/1/2) with `--json` machine payload; typed DSL surface (`Mut/Init/Account`, `FixedArray/Vec/Option`, `require`, `@instruction/@account/@error`) checked clean under `mypy --strict`.
- Phase 2 — the `examples/counter` program and a negative-fixture suite (`tests/test_phase2.py`) with ~60 rejected programs pinned to exact `code:line:col`.
- Docs — `docs/architecture.md`, starter ADRs under `docs/decisions/`.
