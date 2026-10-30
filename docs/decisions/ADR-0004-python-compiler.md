# ADR-0004 — Compiler implementation language: Python + stdlib `ast`

- **Status:** accepted
- **Date:** 2026-10-30
- **Deciders:** PythSol contributors

## Context

PRD §8.3 OQ-2 / TRD §3 ask if the compiler should be written in Python.

## Decision

Yes. The compiler, CLI, client generator and test harness are **pure Python** with
a `py3-none-any` wheel. Core rules:

1. User program code is **only** parsed with `ast.parse` — never executed.
2. Type inference is a small checker written on top of the parsed `ast` (Phase 2).
3. Code emission targets C11 with `static inline` helpers (Phase 3).
4. Heavy backends (clang, lld) are driven via `subprocess`-safe helpers in
   `pythsol.compiler.toolchain`; they are only given *generated* C.

## Verification

No spike is needed beyond `ast.parse` itself (Python 3.11+ is in the matrix).
The spike exists as a rough sanity check in `Spikes/python/cn_litesvm_hello.py`
(Phase 1); the *front-end* is phase 2 territory and is gated by tests.

## Consequences

- Contributor barrier is low (PRD G5).
- Pyodide compatibility is a *post‑1.0* question (PRD F-09 is a Should‑have).
- Python's dynamic semantics (unbounded ints, `//` floor division, truthiness)
  become the *default* semantics and are documented with precision — see the
  Langue matrix in TRD §5.2 and the Phase 2/4 tests.
