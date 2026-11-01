---
title: Counter
description: A PDA counter with an authority check.
---

`examples/counter/programs/counter.py` stores `authority`, `count`, and
`bump`. `initialize` creates the PDA (seed `counter`) and sets the count to
0. `increment` requires `counter.authority == authority.key` and then adds
`by` with checked arithmetic.

`Unauthorized` is error code `6000`. Overflow returns `1009` and does not
change the account. The source positions in the program log are
`(counter.py:51)` for the authority check and `(counter.py:52)` for the add.
