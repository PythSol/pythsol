---
title: API
description: Decorators and types. This page is not generated from docstrings.
---

Program authors import from `pythsol`:

- `@account`, `@instruction`, `@error`, `@enum`, `@struct`, `@event`
- `Signer`, `Mut`, `Init`, `Account`, `Pubkey`
- `Seeds`, `HasOne`, `CloseTo`, `Address`, `Owner`
- `Option`, `FixedString`, `FixedArray`
- `require`, `emit`, `system_transfer`, `token_transfer`, `token2022_transfer`, `ata_create`

This page is written by hand. There is no griffe export in the scaffold.
The stubs live in `src/pythsol/__init__.py`. Constraint names need a
`type: ignore` comment because they are erased before mypy sees a real base.
