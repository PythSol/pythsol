---
title: Accounts
description: Fixed-width accounts, one PDA seed, and the system program.
---

An `@account` is a fixed layout. The first 8 bytes are
`sha256("account:Name")`. Fields after that do not move, so `Option`,
`FixedString`, and nested structs reserve their full width. `Vec` and data
enums are rejected because a variable payload would slide later fields.

`Init` creates a PDA. The default seed is the snake_case account name. One
literal seed replaces it (`Seeds[Init[T], "vault"]`). The bump is its own
byte. The System program account is appended on instructions that pay or
call `system_transfer`.

The program id is not compiled into the `.so`. LiteSVM assigns it when the
test loads the binary. The runtime reads the id from the transaction input.
