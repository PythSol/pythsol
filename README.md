# PythSol

Write Solana programs in **typed Python**, compiled to native SBF bytecode — no Rust on your machine.

> **Status: Phase 3 compiler landed.** `pythsol check` fully type-checks
> programs with stable diagnostics, and `pythsol build` now compiles the
> counter program to a native SBF `.so` + Anchor-style IDL that runs correctly
> in LiteSVM (initialize → increment, `require` reverts at the exact Python
> line). Phase 4 (u128, casts, enums, Option/Vec/FixedArray, control flow,
> helper functions, CPI DSL) is next. See the [Phases](#phases) section.

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
pythsol build counter.py  # native SBF .so + IDL + manifest (needs Anza platform-tools)
pysol doctor              # `pysol` is the spec-draft alias of the same CLI
```

## Build

`pythsol build programs/counter.py` emits `target/pythsol/counter/`:

| file            | contents                                                      |
|-----------------|---------------------------------------------------------------|
| `counter.c`     | auditable C generated from your program (never hand-edited)   |
| `counter.so`    | the SBF ELF deployed on-chain                                 |
| `counter.json`  | Anchor-style legacy IDL for TS client generation              |
| `manifest.json` | sha256 of c/idl/so + toolchain info; **builds are byte-deterministic** |

On-chain guarantees: `require()` failures log `(file:line)` and return
`6000 + index`; integer arithmetic never wraps (checked ops abort with 1009/1010);
`Init` accounts are PDAs created through a System-program CPI with your seeds.
The binary ABI conventions are pinned in
[ADR-0010](docs/decisions/ADR-0010-runtime-abi-and-input-layout.md).

## Phases

| Phase | Deliverable | Status |
|---|---|---|
| 0 | monorepo skeleton, ADRs, CI, license, name spike | **done** |
| 1 | SBF toolchain locator + doctor, C→SBF spike, LiteSVM spike | **done** |
| 2 | parse/subset/type-check front-end, `pythsol check`, 40+ negative fixtures | **done** |
| 3 | ProgramModel, IDL, C runtime/emitter, `pythsol build`, LiteSVM acceptance | **done** |
| … | client generation, templates, docs site, playground | later phases |

## License

Apache-2.0. See [LICENSE](./LICENSE) and [docs/decisions/ADR-0002](docs/decisions/ADR-0002-license.md).
