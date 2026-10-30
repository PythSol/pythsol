# ADR-0001 — Project name and distribution

- **Status:** accepted
- **Date:** 2026-10-30
- **Deciders:** PythSol contributors

## Context

PRD §0.1 / PRD §6.5 flag the name as an [ASSUMPTION] that has to be verified before
any public release. Two problems:

1. The draft name **PySol** is *not* usable: `PySol` is a well-known solitaire
   card game and its PyPI name is already occupied (`pysol`).
2. The final branding requested for this repository is **PythSol**.

## Decision

1. Use **PythSol** as the public name and reference for the framework.
2. The Python distribution is `pythsol` (PyPI, verified available), the import
   package is `pythsol`, and the runtime header is `src/pythsol/runtime/pythsol_rt.h`.
3. Keep `pysol` as a **console-script alias** so the spec-draft command names
   (`pysol doctor`, `pysol build`) still work for contributors who read PRD/TRD
   first. Both `pythsol` and `pysol` point at `pythsol.cli.main.main`.

## Consequences

- Spec text in PRD/TRD keeps saying `pysol` — it stays accurate because the alias
  exists. Docs/DX material will use `pythsol` going forward.
- Namespaces are consistent: `PYTHSOL_SBF_SDK` (spec) and `PYSOL_SBF_SDK` (legacy)
  env vars are both accepted.
- Config file is `pythsol.toml` (TOC `[tool.pythsol]` is not handled yet).

## Verification

- PyPI `pythsol` is free (checked 2026-10-30).
- `pysol` PyPI name is taken by the PySol solitaire project, hence the rename.
