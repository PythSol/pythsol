# Changelog

PythSol follows Keep a Changelog; before 1.0 every breaking change is listed under **Breaking**.

## [0.1.0] — 2026-10-30
### Added
- Phase 0 — repository skeleton, Apache-2.0 license, contributing/code of conduct/security docs, [ADRs](docs/decisions/), `pyproject.toml` with hatchling/ruff/mypy, GitHub Actions `lint` + `unit` CI.
- Phase 1 — `pythsol.compiler.toolchain`: Agave/Anza platform-tools discovery (`PYTHSOL_SBF_SDK`, default cache path), sbpf compile/link flag helpers derived from `anza-xyz/rust@3175de2636 sbf_base.rs`, `compile_to_sbf` helper, plus `pythsol doctor` (Python, platform-tools, clang/lld sanity, `solana` CLI, `cargo-build-sbf`, keypair presence, optional RPC check) with `--json` and fix commands.
- Phase 1 — SBF spike C source at `Spikes/c/hello.c` and LiteSVM runner `Spikes/python/cn_litesvm_hello.py` gated behind the `toolchain` pytest marker.
- Docs — `docs/architecture.md`, starter ADRs under `docs/decisions/`.
