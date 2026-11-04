---
title: Roadmap
description: What is still open. Phase 11 is not scheduled.
---

Shipped: `pip install pythsol` 0.1.0 is on PyPI, the six examples compile,
the stateful ones run in LiteSVM, and the live landing page scores 86
performance / 100 accessibility / 100 best practices / 100 SEO.

Still ahead:

- Hosted full compile on Render (the Vercel endpoints serve check/emit and
  answer compile with Docker guidance).
- A deploy-to-devnet button in the playground, after hosted compile exists.
- A published security audit. Compute-unit benchmarks are measured and
  gated; no external numbers are copied.
- Push-to-deploy: the root Vercel build is verified, but the Vercel account
  still needs its GitHub login connection.

Not scheduled: documentation translations, a second IR, and in-browser SBF
compilation. List comprehensions exist only as
`[expr for i in range(<int literal>)]` for `FixedArray` locals.

`verify`, `profile`, `idl-publish`, `cpi`, and the VS Code extension exist in
this tree.
