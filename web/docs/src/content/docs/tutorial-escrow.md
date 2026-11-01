---
title: Escrow
description: One lamport deal. Take pays the maker and closes to the taker.
---

`examples/escrow/programs/escrow.py` is a lamport escrow, not an SPL-token
escrow. The seed is `escrow`, so a program has one open deal. `make` records
the maker, the taker, and the amount, then transfers that many lamports in.
`take` checks both keys, transfers `price` from the taker to the maker, and
closes the account to the taker. `cancel` closes it back to the maker.

A PDA-signed transfer is not available. Closing the account is what returns
the escrowed lamports. Two signers on `take` cost 10000 lamports in fee on
LiteSVM. SPL transfers are `token_transfer` and `token2022_transfer`, used
by the token fixture, not by this example.
