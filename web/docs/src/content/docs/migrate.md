---
title: Migrate
description: pythsol port writes a skeleton from an IDL.
---

`pythsol port program.json -o sketch.py` writes `@account` classes and
`@instruction` functions whose bodies are `pass`. Run `pythsol check` and
replace each `pass`.

The longer note is `docs/guides/migration.md`. One seed, fixed-width fields,
and no PDA-signed transfer are the limits that usually show up first. The
escrow example in this repo moves lamports. It is not an Anchor token escrow
port.
