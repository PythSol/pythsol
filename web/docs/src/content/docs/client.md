---
title: Client
description: Generated solders builders do not import the compiler.
---

`pythsol build` writes `{name}_client.py`. The module imports solders only.
Each instruction is `name(program_id, *accounts, *args) -> Instruction`.
An init signer is writable because the instruction pays. System, Token,
Token-2022, and the ATA program are appended only when that instruction
needs them.

`pythsol client program.json` reads `metadata.pythsol.cpi` for the same
append rules. An IDL written before that metadata key appends nothing.

`pythsol cpi` adds two comments: the builders are for an off-chain caller.
PythSol does not lower a generic on-chain invoke of another program.
