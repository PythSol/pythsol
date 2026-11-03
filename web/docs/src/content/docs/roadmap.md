---
title: Roadmap
description: What is still open. Phase 11 is not scheduled.
---

Still ahead:

- Hosted full compile on Render (the Vercel endpoints serve check/emit and
  answer compile with Docker guidance).
- A deploy-to-devnet button in the playground, after hosted compile exists.
- A published security audit and a compute-unit regression gate. Benchmarks
  are measured locally; no external numbers are copied.
- An accessibility and Lighthouse run recorded against the live site.
- PyPI upload (the wheel and sdist build and pass `twine check`; the upload
  needs the project token).

Not scheduled: documentation translations, a second IR, and in-browser SBF
compilation. List comprehensions exist only as
`[expr for i in range(<int literal>)]` for `FixedArray` locals.

`verify`, `profile`, `idl-publish`, `cpi`, and the VS Code extension exist in
this tree. The six gallery programs compile, and the ones that move lamports
or write state run in LiteSVM.
