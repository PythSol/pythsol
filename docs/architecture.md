# Architecture

PythSol is a Python‑subset compiler + tooling for writing native SBF Solana programs.

```
program.py  ─▶ parse.py      (ast, never executed)
            ─▶ subset.py     (runner: allowed statements, wrappers, types)
            ─▶ resolve.py    (imports, @program / @instruction / @error)
            ─▶ typecheck.py  (bidirectional, fixed-width ints, Siri-like wrappers)
            ─▶ semantic.py   (account-model, aliasing, constraints)
            ─▶ model.py      (ProgramModel)
            ─▶ idl.py        (Anchor-compatible IDL JSON)
            ─▶ emit/         (lowered C against src/pythsol/runtime/pythsol_rt.h)
            ─▶ toolchain.py  (clang + ld.lld -target sbf)
            ─▶ .so + build manifest
```

Source of truth: `docs/spec/TRD.md` (how) + `docs/spec/PRD.md` (scope).
```
```
- The compiler **never executes** user code — only `ast.parse`.
- The Python reference runtime (`pythsol.refrt`) mirrors the generated C so every
  tested instruction has a CPython-equivalent path (Phase 4).
- The emitter is IR-free (TRD §4.2): C is emitted directly from the model; clang
  `-O2` is the optimizer. This matches Typesol (the base for ADR-0006) and keeps
  audit-friendly C readable.
- Toolchain calls are **generated C only** (`TR-SEC-03`).

## Layout (monorepo)

```
src/pythsol/         compiler, cli, runtime header, templates
tests/               pytest suite (unit + toolchain)
Spikes/              Phase 0/1 spike code (C hello world, LiteSVM runner)
docs/                architecture, ADRs
.github/workflows/   lint / unit / toolchain CI
```

## Phases

| Phase | Deliverable | Status |
|---|---|---|
| 0 | skeleton, ADRs, CI | done |
| 1 | toolchain locator + doctor + spike | done |
| 2 | front-end (parse/subset/typecheck, `pythsol check`) | now |
| 3 | ProgramModel + IDL + runtime + C emitter (`pythsol build`) | next |
| 4+ | see TRD §18 | later |
