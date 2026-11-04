---
title: Introduction
description: PythSol compiles a typed Python subset to a native Solana SBF program.
---

**PythSol** compiles a typed Python subset to a native SBF shared object.
The compiler parses the source with `ast`. It does not run it — the
playground and the public server check and emit only; building is a local
job for `pythsol build`.

## What a build gives you

`pythsol build` writes, next to your program:

- C the compiler generated for your program — readable, line-attributed.
- a native SBF `.so` (byte-identical across rebuilds, cached).
- an **Anchor-style IDL** with discriminators and error codes.
- a **solders client** generated against that IDL (no `import pythsol`
  in it — the client imports solders only).
- a `manifest.json` tying the artifacts together.

## The pipeline

```bash
pip install -e ".[test]"
pythsol init app --template counter
cd app
pythsol check programs/app.py
pythsol test
pythsol build
```

Every stage reads the same typed subset: `pythsol check` reports stable
`PSxxxx` diagnostics with file, line, and column before anything is
emitted. `pythsol test` runs the built bytecode in LiteSVM without a
network or validator.

## What the code looks like

The four lines below are real — they are `increment` from
`examples/counter/programs/counter.py`:

```python
@instruction
def increment(authority: Signer, counter: Mut[Counter], by: u64) -> None:
    """Add `by` to the count; only the stored authority may call this."""
    require(counter.authority == authority.key, CounterError.Unauthorized)
    counter.count += by
```

The compiler turns that instruction into C that role-checks accounts,
verifies the discriminator, computes `count + by` with a checked add, and
attributes every failure to the `counter.py` line that caused it. See the
user-accounts walkthrough on the [Language](/docs/language) page and the
generated C in the [playground](/playground) (Check → Emit → tabs C, IDL,
Client).

## Example programs

The `examples/` directory ships six builds to learn from. The first four
have docs walkthroughs; the last two are documented by their source and
tests.

| Program | What it shows |
| --- | --- |
| [counter](/docs/tutorial-counter) | accounts, a signer/writable guard, a custom error |
| [ledger](/docs/language) | fixed-capacity `Vec[T, N]` payload fields and a for-range fill |
| [vault](/docs/accounts) | lamports held by a program-owned PDA |
| [escrow](/docs/tutorial-escrow) | lamport moves between two users' accounts |
| [multisig](https://github.com/PythSol/pythsol/blob/main/examples/multisig/programs/multisig.py) | a `FixedArray[Pubkey, 3]` owner set, approval bitmask, PDA payout |
| [poll](https://github.com/PythSol/pythsol/blob/main/examples/poll/programs/poll.py) | allowlisted voters, `bool` arguments, one-vote bitmask |

## Subset in one breath

`Vec[T, N]` is a fixed-capacity list; `Vec` without a capacity is
rejected (`PS3001`/`PS4001` depending on position). A data enum is a tag
plus one reserved scalar. String literals are not a stored type yet —
`"hi"` as a value is `PS2004`; a `FixedString[N]` field is the supported
form. Failures are stable codes, never discount signals.

## Served vs. local

The package version is `0.1.1` and it is published on PyPI
(`pip install pythsol`). This site is the static build in `dist/`.
`pythsol serve` on loopback can compile; `pythsol serve --public` checks and
emits only.
