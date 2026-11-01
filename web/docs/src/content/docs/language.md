---
title: Language
description: What the typed subset accepts.
---

The subset accepts annotated integers `u8` through `u128` and `i8` through
`i128`, `bool`, `Pubkey`, `Signer`, `Mut`, `Init`, `Account`, `FixedArray`,
`Option`, `FixedString`, unit `@enum` with `match`, `@struct`, `@event` and
`emit`, plain helpers, `if` / `while` / `for` over `range`, and `require`.

Calls the compiler knows are `require`, `len`, `range`, `emit`,
`system_transfer`, `token_transfer`, `token2022_transfer`, `ata_create`, and
the width casts. Sibling modules (`from acct import Counter`) are read as
text and parsed. Stdlib and third-party imports are rejected.

`Vec[T, N]` reserves N slots. A data enum is `Name: u64` with that width
reserved after the tag. Still rejected: `Vec` without a capacity, f-strings,
unannotated string assignment, and a generic on-chain invoke.
