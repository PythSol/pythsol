# Architecture

PythSol is a Python‑subset compiler + tooling for writing native SBF Solana programs.

```
program.py  ─▶ parse.py      (ast, never executed)                     [done]
            ─▶ subset.py     (structural gate: PS1xxx)                 [done]
            ─▶ resolve.py    (@account / @error / @instruction model)  [done]
            ─▶ typecheck.py  (fixed-width ints, wrappers, aliasing)    [done]
            ─▶ model.py      (ProgramModel)                            [phase 3]
            ─▶ idl.py        (Anchor-compatible IDL JSON)              [phase 3]
            ─▶ emit/         (lowered C against src/pythsol/runtime/pythsol_rt.h)
            ─▶ toolchain.py  (clang + ld.lld -target sbf)
            ─▶ .so + build manifest
```

Source of truth: `docs/spec/TRD.md` (how) + `docs/spec/PRD.md` (scope).
- The front-end pipeline (`parse → subset → resolve → typecheck`) always answers
  with `Diagnostic(code=PSxxxx, file, line, col)` values — never exceptions —
  even for random/fuzzed ASTs (`tests/test_phase2_fuzz.py`). A stage crash
  becomes a `PS9000` "report this bug" diagnostic.
- `pythsol check PROGRAM.py` prints the diagnostics (or `--json` payload
  `{"ok": bool, "diagnostics": [...]}`) with exit codes 0/1/2.
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
tests/               pytest suite (unit + toolchain + fuzz)
Spikes/              Phase 0/1 spike code (C hello world, LiteSVM runner)
docs/                architecture, ADRs
examples/            counter program (the Phase 2 flagship)
.github/workflows/   lint / unit / toolchain CI
```

## Phases

| Phase | Deliverable | Status |
|---|---|---|
| 0 | skeleton, ADRs, CI | done |
| 1 | toolchain locator + doctor + spike | done |
| 2 | front-end (parse/subset/resolve/typecheck, `pythsol check`, fixtures+fuzz) | done |
| 3 | ProgramModel + IDL + runtime + C emitter (`pythsol build`) | in progress |
| 4+ | see TRD §18 | later |
