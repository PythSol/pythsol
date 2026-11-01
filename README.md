# PythSol

Write Solana programs in **typed Python**, compiled to native SBF bytecode — no Rust on your machine.

> **Status: compiler through SPL token CPI, plus the local CLI.** `pythsol check`
> type-checks a typed Python subset. `pythsol build` compiles it to a native
> SBF `.so`, an Anchor-style IDL, and a solders client. A second build of the
> same C prints `cache hit (skipped clang)`. `pythsol test` runs pytest against
> LiteSVM. The counter and ledger examples run there, and so do a one-byte
> `@enum` gate, a fixed-width `Option[u64]` note, a `FixedString[8]` label, a
> till whose fee is an inlined helper, a spot account whose `Point` is packed
> inline, a vault whose PDA seed, has-one, address, owner, and close are
> checked by the program, a bell that `emit`s a fixed-width event, a pay
> instruction whose `system_transfer` moves lamports, and a token move whose
> `token_transfer`, `token2022_transfer`, and `ata_create` CPIs run against
> the programs LiteSVM already loads. A program may split across sibling
> modules (`from acct import Counter`); those files are parsed and are never
> imported or executed.
> `pythsol serve` can also compile that program to a `.so` on your machine
> when the SBF tools are installed.
> `Vec[T, N]` is a fixed-capacity list. A data enum is a tag plus one
> reserved scalar (`Fill: u64`), so later fields stay put. A
> `system_transfer` from a program PDA moves lamports directly. Still ahead:
> unbounded `Vec[T]`, in-browser SBF compile, and translated docs. Host the
> static site from `web/docs/dist` after `npm run build`. Host check and emit
> with `pythsol serve --public`. Compile stays on loopback. The checklist is
> `docs/STATUS.md`. This tree is version 0.1.0 and is not a release.

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
pip install -e ".[test]"  # developer install, with pytest and solders
pip install pythsol       # compiler and CLI only (when published)
```

`pythsol test` needs the `test` extra. Until you reinstall the editable package,
the pytest plugin is not on the entry-point list. `pythsol test` still loads it
with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and `-p pythsol.testing.plugin`.

## CLI

```bash
pythsol doctor            # check toolchain, Python, RPC
pythsol init app --template counter   # or ledger, vault, escrow
pythsol check counter.py  # full front-end type check; exit 1 with PSxxxx diagnostics
pythsol check --json counter.py
pythsol idl counter.py    # Anchor-style IDL, no SBF toolchain
pythsol build counter.py  # native SBF .so + IDL + client + manifest
pythsol test              # build, then pytest on LiteSVM
pythsol client counter.py -o client.py
pythsol cpi counter.py -o cpi.py      # off-chain builders; not an on-chain invoke
pythsol port idl.json -o sketch.py    # skeleton with pass bodies
pythsol deploy --dry-run --so prog.so # prints solana program deploy; mainnet needs --yes
pythsol faucet --amount 1             # devnet only, at most 5 SOL
pythsol wallet new --outfile id.json  # secret stays off the terminal unless --show-secret
pythsol verify --left a.so --right b.so   # exit 0 match, exit 3 mismatch
pythsol profile --logs run.log        # reads "consumed N of" lines already in the log
pythsol idl-publish --address <ID> --dry-run
pythsol serve                         # loopback playground, 127.0.0.1:8765
pythsol docs                          # offline command list
pysol doctor                          # `pysol` is the spec-draft alias of the same CLI
```

## Build

`pythsol build programs/counter.py` emits `target/pythsol/counter/`:

| file            | contents                                                      |
|-----------------|---------------------------------------------------------------|
| `counter.c`            | auditable C generated from your program (never hand-edited) |
| `counter.so`           | the SBF ELF deployed on-chain                               |
| `counter.json`         | Anchor-style legacy IDL                                     |
| `counter_client.py`    | solders `Instruction` builders and account decoders         |
| `manifest.json`        | sha256 of c/idl/so/client, toolchain info, and `cache` (`hit`, `miss`, or `off`) |

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
| 4 | if/while/for, casts, full integer widths, `FixedArray`, checked expressions | **done** |
| 5 | Python client (`*_client.py`, solders) | **done** |
| 6 | `pythsol test`, pytest plugin, build cache, wallet, faucet, deploy, `pysol.toml` | **done** |
| 7 | Starlight scaffold and light tokens (`web/docs`, `web/shared-tokens`) | **scaffold** (not deployed, no Lighthouse run) |
| 8 | `pythsol serve` loopback check, emit, and compile | **local only** (no hosted Pyodide) |
| 9 | gallery of the four examples, `pythsol port`, migration and contributor notes | **partial** (four examples, not twenty) |
| 10 | `verify`, `profile`, `idl-publish`, `cpi`, VS Code diagnostics | **partial** (no audit, no CU gate) |
| 11 | docs translations, comprehensions, a second IR, in-browser SBF | **not scheduled** |
| … | unit enums (`@enum`, `match`) | **done** |
| … | fixed-width `Option[T]` (tag + reserved value) | **done** |
| … | fixed-width `FixedString[N]` (`u32` length + reserved bytes) | **done** |
| … | plain helpers (inlined, not instructions) | **done** |
| … | nested `@struct` (fixed width, inline, no discriminator) | **done** |
| … | constraints `Seeds` / `HasOne` / `Address` / `Owner` / `CloseTo` | **done** |
| … | alias refusal peels constraint wrappers | **done** |
| … | `@event` and `emit` (fixed-width log) | **done** |
| … | `system_transfer` (System program CPI) | **done** |
| … | SPL Token, Token-2022, and ATA CPIs | **done** |
| … | multi-file programs (sibling modules, parsed not executed) | **done** |
| … | `Vec[T, N]`, fixed-width data enums, PDA lamport move | **done** |
| … | unbounded `Vec[T]`, hosted playground, public compile service | later |

## License

Apache-2.0. See [LICENSE](./LICENSE) and [docs/decisions/ADR-0002](docs/decisions/ADR-0002-license.md).
