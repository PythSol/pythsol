# ADR-0003 — DSL syntax: decorators + annotated wrappers

- **Status:** accepted
- **Date:** 2026-10-30
- **Deciders:** PythSol contributors

## Context

PRD §8.3 OQ-1 asks: decorators with annotated wrappers (`Mut[Signer]`) or Anchor's
class-based `Accounts` contexts? TRD §5.1 lists the supported surface explicitly.

This is a Phase 0 decision because the compiler front-end (Phase 2) starts from
this shape.

## Decision

Use **decorators + annotated wrappers**:

```python
@program
class counter:
    authority: Pubkey
    count: u64
    bump: u8

@instruction(join)
def increment(authority: Signer, counter: Mut[counter], by: u64) -> None:
    require(counter.authority == authority.key, counter.Unauthorized)
    counter.count += by   # overflow-checked
```

Where a parameter/field annotation is always one of:

- a *primitive width type*: `u8,u16,u32,u64,u128, i8,i16,i32,i64,i128`;
- `bool`, `Pubkey`, or an enum like `InstructionError`;
- an *account wrapper*: `Signer`, `Account[T]`, `Mut[T]`, `Init[T]`, `InitIfNeeded[T]`,
  `Zeroed[T]`; programs like `SystemProgram` are referenced as the type itself;
- an `Optional[...]`: optional account;
- a generic *collection* wrapper: `Option[T]`, `Vec[T]`, `FixedArray[T, N]`, `FixedString[N]`.

Constraints (`Seeds`, `HasOne`, `CloseTo`, `Address`, `Owner`, `Executable`, `Ata`)
are declared as annotations in the **account field** of a `@program` class:

```python
@program
class counter:
    authority: Signer
    counter: counter @ Seeds[authority, [b"counter"]] @ HasOne[authority]
```

The exact syntax for constraints is a **Phase 4** decision; Phase 2 only accepts
basic types and the wrappers above.

## Verification (spike)

`samples/syntax-spike.py` (in `Spikes/pythsol-spike/`) contains the target surface
above; Phase 2's front-end is going to be able to `ast.parse` it without exception.
If the target syntax is **not** representable in pure `ast.parse` (e.g., wrappers
reject anything before the parse), the spike test is the gate that fails, not a
silent change: Phase 2 then shrinks the *syntactic* surface and documents it.

## Consequences

- The DSL is Python syntax only, so editors, `mypy --strict`, and `ruff` work with
  zero plugins (PRD F-01-d).
- Programs are *declared* with decorators and maybe a dispatch attribute; the
  dependency graph is explicit and audit-friendly.
- Anchor migration (PRD F-14) is mostly a 1:1 mapping.
