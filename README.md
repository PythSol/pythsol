# PythSol

Write Solana programs in **typed Python**, compiled to native SBF bytecode — no Rust on your machine.

> **Status: Phase 0/1 skeleton.** The compiler front-end (Phase 2) and the runtime/IDL/emitter
> (Phase 3) land next. See the [Phases](#phases) section or `docs/`.

Source of truth: `docs/spec/PRD.md` (scope) + `docs/spec/TRD.md` (how).
When possible ADRs under `docs/decisions/` record every assumption that was validated.

```python
from pythsol import (Program, Pubkey, u64, u8, Init, Signer, Mut, require, ProgramError)

@program
class counter:
    authority: Pubkey
    count: u64
    bump: u8

@instruction(program_id)
def increment(authority: Signer, counter: Mut[counter], by: u64) -> None:
    require(counter.authority == authority.key, ProgramError("Unauthorized", 0))
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
pysol doctor              # `pysol` is the spec-draft alias of the same CLI
```

## Phases

| Phase | Deliverable | Status |
|---|---|---|
| 0 | monorepo skeleton, ADRs, CI, license, name spike | **done** |
| 1 | SBF toolchain locator + doctor, C→SBF spike, LiteSVM spike | **in progress** |
| 2 | parse/subset/type-check front-end, `pythsol check`, 40 negative fixtures | pending |
| 3 | ProgramModel, IDL, C runtime/emitter, `pythsol build` | pending |
| … | client generation, templates, docs site, playground | later phases |

## License

Apache-2.0. See [LICENSE](./LICENSE) and [docs/decisions/ADR-0002](docs/decisions/ADR-0002-license.md).
