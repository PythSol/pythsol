---
title: Vault
description: A lamport vault with Seeds, HasOne, and CloseTo.
---

`examples/vault/programs/vault.py` holds lamports on a PDA whose seed is the
literal `vault`. `deposit` calls `system_transfer` from the authority and
adds the amount to `balance`. `close` checks the authority, then `CloseTo`
returns the lamports after the body succeeds.

The account is 49 bytes: discriminator, authority at offset 8, balance at
40, bump at 48. This vault is not the fixture program under `tests/fixtures`,
which uses the seed `box`.
