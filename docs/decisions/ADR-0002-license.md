# ADR-0002 — License

- **Status:** accepted
- **Date:** 2026-10-30
- **Deciders:** PythSol contributors

## Context

PRD §6.5 asks for Apache-2.0 as the compiler/CLI/runtime license (explicit patent
grant) and proposes CC BY 4.0 for docs, MIT for templates/examples (so users can
relicense generated projects).

## Decision

1. **Apache-2.0** for everything inside `src/pythsol/` (compiler, runtime header,
   CLI, generated C). That includes the inherited header `src/pythsol/runtime/pythsol_rt.h`.
2. **MIT** for the *contents of* `examples/` and later `templates/` (Phase 6).
   When those directories gain real code, each file adds a short header:
   `SPDX-License-Identifier: MIT`.
3. Docs markdown under `docs/` is **CC BY 4.0** when Phase 7 publishes the site;
   for now the whole tree ships under the repo-level Apache-2.0 LICENSE, which is
   a conservative placeholder that Phase 7 will narrow.

## Consequences

- Generated C and the runtime header inherit Apache-2.0 automatically.
- Template/example code can be freely relicensed by users.
- Nothing else ships from third parties in the repo; binaries are fetched at test
  time, never redistributed.

## Verification

- `LICENSE` at repo root is Apache-2.0 (fetched from https://www.apache.org/licenses/LICENSE-2.0.txt).
