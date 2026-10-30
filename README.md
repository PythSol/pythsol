# PythSol

Write Solana programs in **typed Python**, compiled to native SBF bytecode — no Rust on your machine.

> **Status: Phase 2 front-end landed.** `pythsol check` fully type-checks programs
> with stable diagnostics; `pythsol build` (native SBF emitter) lands in Phase 3.
> See the [Phases](#phases) section or `docs/`.

Source of truth: `docs/spec/PRD.md` (scope) + `docs/spec/TRD.md` (how).
When possible ADRs under `docs/decisions/` record every assumption that was validated.

```python
from pythsol import (
    Init, Mut, ProgramError, Pubkey, Signer, account, error, instruction, require, u64, u8,
)

@account
class Counter:
    authority: Pubkey
    count: u64
    bump: u8

@error
class CounterError(ProgramError):
    Unauthorized = 100
    Overflow = 101

@instruction
def increment(authority: Signer, counter: Mut[Counter], by: u64) -> None:
    require(counter.authority == authority.key, CounterError.Unauthorized)
    counter.count += by   # overflow-checked
```

## Install

```bash
pip install -e .          # developer install
pip install pythsol       # end user (when published)
```

## CLI

```bash
pythsol doctor            # check toolchain, Python, RPC
pythsol check counter.py  # full front-end type check; exit 1 with PSxxxx diagnostics
pythsol check --json counter.py
pysol doctor              # `pysol` is the spec-draft alias of the same CLI
```

## Phases

| Phase | Deliverable | Status |
|---|---|---|
| 0 | monorepo skeleton, ADRs, CI, license, name spike | **done** |
| 1 | SBF toolchain locator + doctor, C→SBF spike, LiteSVM spike | **done** |
| 2 | parse/subset/type-check front-end, `pythsol check`, 40+ negative fixtures | **done** |
| 3 | ProgramModel, IDL, C runtime/emitter, `pythsol build` | in progress |
| … | client generation, templates, docs site, playground | later phases |

## License

Apache-2.0. See [LICENSE](./LICENSE) and [docs/decisions/ADR-0002](docs/decisions/ADR-0002-license.md).
