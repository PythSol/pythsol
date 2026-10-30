# ADR-0009 — pyright is optional, deferred until Phase 3

- **Status:** accepted
- **Date:** 2026-10-31
- **Deciders:** PythSol contributors

## Context

TRD §Phase 2 acceptance lists "pyright `--strict` (or defer via ADR)" as a
verifiable criterion. Running two type systems on the same source has value
(mypy/pyright disagreements historically catch real API bugs in typed stub
surfaces — exactly what `src/pythsol/__init__.py` is), but each extra gate also
costs CI minutes and authoring effort every time the surface changes.

The environment where Phase 2 was built had a slow network and the pyright
wheel (~30 MB + Node runtime download) was the most expensive dependency to
install; the deliverable dates slipped otherwise.

## Decision

Deferral:

1. **mypy `--strict` is the normative gate** (CI + local). Phase 2's DSL
   surface and compiler modules must stay clean under it, including the
   program example `examples/counter/programs/counter.py`.
2. **pyright is optional** (`[project.optional-dependencies] dev`, install
   manually with `pip install -e ".[dev]"` + `uvx pyright` or
   `pyright src examples`). It will be added to CI in Phase 3 when the surface
   stabilizes behind `pythsol build`, so we reconcile the second checker once,
   not on every import-list tweak.
3. `tests/test_phase2.py::test_export_list_matches_surface` keeps the
   `pythsol.__all__` ↔ compiler import list contract pinned, which removes the
   main class of bugs pyright would find in the interim.

## Consequences

- Two checkers disagree → treat as an API smell, not a config fight.
- The DSL surface must remain a *typed stub* package (`py.typed` marker next to
  the code) so pyright, when wired, needs no configuration.
- If pyright stays deferred after Phase 3, replace this ADR with a
  recorded decision to drop the criterion (with reason) instead of silently
  letting it dangle.
