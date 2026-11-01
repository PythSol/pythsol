---
title: Contributing
description: Where to add a builtin, a constraint, or an error.
---

`docs/guides/recipes.md` is the short walkthrough:

- A program error is an `@error` member. The on-chain code is `6000 + index`.
- A framework code is a new `RT_ERR_*` in the runtime header.
- A constraint is a stub, a typecheck record, and an emit check that returns `1014`.
- A builtin is a known callable, a typecheck, an emit lowering, and a runtime function.

Do not reformat `src/pythsol/compiler/emit.py` to chase `ruff format`. Golden
fragments pin exact C text for the counter. Version stays `0.1.0` until a
release is actually cut.
