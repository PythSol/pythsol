# Contributor recipes

The compiler never executes user code. A change that lowers a new construct
belongs in the subset gate, the type checker, the model, the emitter, and
the runtime header. Golden fragments in `tests/test_phase3_emit.py` pin
exact C for the counter. Do not reformat `src/pythsol/compiler/emit.py` to
satisfy `ruff format` if that would move those fragments.

## Add an error to a program

No compiler change. Declare a member on an `@error` class:

```python
@error
class CounterError(ProgramError):
    Unauthorized = 100
```

`100` is the declared value stored on the model. The value returned on chain
is `6000 + index` in declaration order. `Unauthorized` above is `6000`.
Tests should use `expect_error("Unauthorized")` or the code `6000`.

## Add a framework error code

Framework codes live in `src/pythsol/runtime/pythsol_rt.h` as `RT_ERR_*`.
The next free code after `RT_ERR_CONSTRAINT` (1014) is the place for a new
one. Return it from the emitted C through the existing `rt_fail_log` path,
document it in `docs/architecture.md`, and add a LiteSVM test that observes
the numeric code. Do not reuse `6000 + index`; that range is program errors.

## Add a constraint

1. Add the typing stub next to `Seeds` in `src/pythsol/__init__.py`. Stubs
   are erased before typecheck. A parameter that mentions the name needs
   `# type: ignore[name-defined]` before `# noqa: F821`.
2. Teach `src/pythsol/compiler/typecheck.py` to record one of `seed`,
   `has_one`, `owner_of`, `address_of`, or `close_to` on `AccountParamModel`.
   One constraint per account. The alias check peels that single wrapper, so
   two mutable views of the same account stay `PS3000`.
3. Lower the check in `src/pythsol/compiler/emit.py` before the body. A
   failed constraint returns `1014` (`RT_ERR_CONSTRAINT`). `CloseTo` runs
   only after the body succeeds, and a body that `return`s is rejected.
4. Cover it with a negative fixture (code, line, column) and a LiteSVM test.

## Add a builtin call

1. Add the name to `_KNOWN_CALLABLES` in `src/pythsol/compiler/subset.py`.
   A call that is not in that set is rejected before typecheck.
2. Check the arguments in `src/pythsol/compiler/typecheck.py`.
3. Lower the call in `src/pythsol/compiler/emit.py` to a function in
   `src/pythsol/runtime/pythsol_rt.h`.
4. If the client must append a program account, set a flag on
   `InstructionModel` and append it in `src/pythsol/client/gen.py` and in
   `src/pythsol/client/from_idl.py`. Record the same flag in
   `metadata.pythsol.cpi` from `src/pythsol/compiler/idl.py`.
5. Add a unit test that does not need clang, and a LiteSVM test when the
   call moves lamports or tokens.

`system_transfer` signs with the transaction signers. It passes a null
signer-seeds pointer into `sol_invoke_signed_c`. A PDA-signed transfer is a
different builtin and is not implemented.
