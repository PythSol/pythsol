# Moving a program toward PythSol

`pythsol port IDL.json -o sketch.py` reads an Anchor-style IDL and writes a
PythSol skeleton. Each instruction body is `pass`. The file is a starting
point. It is not a finished program, and it is not something the compiler
can deploy until the bodies match the account layout you want.

What the sketch keeps:

- Accounts become `@account` classes. A signer account becomes `Signer`.
- A `seeds` constraint becomes `Seeds[Init[T], "seed"]` when the IDL says so.
  PythSol accepts one seed of letters, digits, and `_`, plus the bump.
- `has_one`, `close`, `address`, and `owner` become `HasOne`, `CloseTo`,
  `Address`, and `Owner`.
- An instruction whose name is `initialize`, `init`, `make`, `create`, or
  `open`, and whose account is mutable, is sketched as `Init[T]`.
- An unmatched account that is not a signer is `Pubkey`.
- Defined structs that are the fixed `Option` or `FixedString` shape are
  written back as `Option[T]` and `FixedString[N]`.
- Unit-enum variants use their declaration index. The tag must equal that
  index.
- An error class uses the declared values. At runtime the code is still
  `6000 + index`.

What it does not do:

- Data enums and `Vec` are rejected by the compiler. A port that needs either
  one will not check until the layout is fixed-width.
- PDA-signed `system_transfer` is not lowered. Closing an account is how the
  vault and escrow examples return lamports.
- `pythsol cpi` writes off-chain instruction builders. A PythSol program
  cannot call an arbitrary program through those builders. Token and System
  transfers go through `token_transfer`, `token2022_transfer`, `ata_create`,
  and `system_transfer`.
- The escrow example moves lamports. It is not an SPL-token escrow.

After `port`, run `pythsol check` on the sketch, replace each `pass`, and
run `pythsol test`.
