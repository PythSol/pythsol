# Architecture

PythSol is a Python‑subset compiler + tooling for writing native SBF Solana programs.

```
program.py  ─▶ parse.py      (ast, never executed)                     [done]
            ─▶ subset.py     (structural gate: PS1xxx)                 [done]
            ─▶ resolve.py    (@account / @error / @enum / @instruction) [done]
            ─▶ typecheck.py  (fixed-width ints, wrappers, aliasing)    [done]
            ─▶ model.py      (ProgramModel)                            [phase 3]
            ─▶ idl.py        (Anchor-compatible IDL JSON)              [phase 3]
            ─▶ emit.py       (lowered C against src/pythsol/runtime/pythsol_rt.h)
            ─▶ client/gen.py (solders Instruction builders; no compiler import)
            ─▶ toolchain.py  (clang + ld.lld -target sbf)
            ─▶ .so + IDL + *_client.py + build manifest
```

Source of truth: `docs/spec/TRD.md` (how) + `docs/spec/PRD.md` (scope).
- The front-end pipeline (`parse → subset → resolve → typecheck`) always answers
  with `Diagnostic(code=PSxxxx, file, line, col)` values — never exceptions —
  even for random/fuzzed ASTs (`tests/test_phase2_fuzz.py`). A stage crash
  becomes a `PS9000` "report this bug" diagnostic.
- `pythsol check PROGRAM.py` prints the diagnostics (or `--json` payload
  `{"ok": bool, "diagnostics": [...]}`) with exit codes 0/1/2.
- The compiler **never executes** user code — only `ast.parse`.
- The Python reference runtime (`pythsol.refrt`) mirrors the generated C so every
  tested instruction has a CPython-equivalent path (Phase 4).
- The emitter is IR-free (TRD §4.2): C is emitted directly from the model; clang
  `-O2` is the optimizer. This matches Typesol (the base for ADR-0006) and keeps
  audit-friendly C readable.
- Toolchain calls are **generated C only** (`TR-SEC-03`).

## Layout (monorepo)

```
src/pythsol/         compiler, cli, runtime header, templates, testing plugin, playground
tests/               pytest suite (unit + toolchain + fuzz)
Spikes/              Phase 0/1 spike code (C hello world, LiteSVM runner)
docs/                architecture, ADRs, guides, gallery index
examples/            counter, ledger, vault (lamport PDA), escrow (one-seed deal)
web/docs/            Starlight scaffold (not a deployed site)
web/shared-tokens/   light-only design tokens
contrib/vscode/      diagnostics via `pythsol check --json`
.github/workflows/   lint / unit / toolchain CI
```

## Phases

| Phase | Deliverable | Status |
|---|---|---|
| 0 | skeleton, ADRs, CI | done |
| 1 | toolchain locator + doctor + spike | done |
| 2 | front-end (parse/subset/resolve/typecheck, `pythsol check`, fixtures+fuzz) | done |
| 3 | ProgramModel + IDL + runtime + C emitter (`pythsol build`) | done |
| 4 | control flow, casts, u128/i128, FixedArray, checked expressions | done |
| 5 | Python client (`render_client`, written by `pythsol build`) | done |
| 6 | `pythsol test`, pytest plugin, build cache, wallet, faucet, deploy | done |
| 7 | Starlight scaffold, light tokens | scaffold (not deployed) |
| 8 | `pythsol serve` check, emit, and compile on loopback | local only |
| 9 | four-example gallery, `port`, migration and contributor notes | partial |
| 10 | `verify`, `profile`, `idl-publish`, `cpi`, VS Code extension | partial |
| 11 | translations, comprehensions, IR, in-browser SBF | not scheduled |
| — | unit enums (`@enum`, 1-byte tag, `match`) | done |
| — | fixed-width `Option[T]` (tag byte + reserved value) | done |
| — | fixed-width `FixedString[N]` (`u32` length + reserved bytes) | done |
| — | plain helpers, inlined into the caller | done |
| — | nested `@struct` (fixed width, inline) | done |
| — | `Seeds`, `HasOne`, `Address`, `Owner`, `CloseTo` | done |
| — | alias refusal peels one constraint wrapper | done |
| — | `@event` / `emit` (fixed-width `sol_log_data`) | done |
| — | `system_transfer` (System program CPI, tag 2) | done |
| — | SPL Token, Token-2022 transfer, and ATA create | done |
| — | multi-file programs (sibling `from module import Name`) | done |
| — | `Vec[T, N]`, data enums (tag plus one reserved scalar), PDA lamport moves | done |
| — | unbounded `Vec[T]`, hosted Pyodide, public compile service | later |

Unit enums are one byte. The variant's integer is its declaration index, which
is also the Anchor tag (`{"kind":"enum","variants":[...]}` with no explicit
discriminant). A field's IDL type is `{"defined":"Status"}`. `Status.Open`
lowers to a `uint8_t` literal, so existing load, store, and compare paths
apply. `match` requires every variant or a final `_`; an on-chain byte that
is not a declared variant returns `1011` (`RT_ERR_ENUM`). Data enums stay out:
a tag plus a payload is not fixed-width and would move later fields.

`Option[T]` is fixed-width for the same reason. The wire form is a tag byte
(`0` none, `1` some) plus the inner value always reserved, including for
instruction arguments, so `data_len` stays exact. The IDL does not use
Anchor's short `{"option": T}` (a missing value would slide every later
field). It emits a defined struct such as `OptionU64` with `tag: u8` and
`value: u64`. `None` clears the tag. Assigning `T` sets it. `.value` on a
clear tag returns `1012` (`RT_ERR_OPTION`).

`FixedString[N]` is fixed-width for the same reason. The wire form is a
little-endian `u32` byte length plus `N` reserved payload bytes, including
for instruction arguments. The IDL does not use Anchor's short `string`
(a shorter value would slide every later field). It emits a defined struct
such as `FixedString8` with `len: u32` and `data: u8[8]`. `len` reads the
stored count. A length past `N` returns `1013` (`RT_ERR_STRING`). The bytes
live on the stack or in the account. An untyped `s = "hi"` is still rejected.
`Vec` stays out until account resize exists: a variable vector in the middle
of an account cannot keep the later offsets this layout promises.

A helper is a typed function without `@instruction`. The emitter inlines it
at the call so a checked-math failure still `return`s from the instruction
function. The helper sees only the arguments it was passed. It is omitted
from the IDL and from `RT_DISPATCH`. A cycle, or a chain longer than 8, is
rejected before any C is emitted.

A `@struct` is fixed-width data, not an account. It has no discriminator, so
a later field of the account does not move. `account.point.x` is the leaf at
the sum of the payload offsets. Assigning one struct field to another of the
same struct copies that many bytes. The IDL type is `{"kind":"struct",...}`
and an account field that holds one is `{"defined":"Point"}`. The client
decodes it to a dict. A struct cannot be an instruction argument, a local, or
an `Account`/`Mut` target. A cycle is rejected. `Option` of a struct stays
unsupported: the option form here reserves a scalar, not a nested struct.

An account constraint wraps one instruction parameter. `Seeds[Init[T], "box"]`
replaces the default PDA seed (the account's snake_case name) with that
literal; the bump is still its own seed byte. `HasOne[Mut[T], "field"]` loads
the Pubkey field and compares it to the earlier parameter of that name.
`Address[Mut[T], expected]` compares the account key to a `Pubkey` argument.
`Owner[Mut[T], program]` checks `owner` against that account's key instead of
this program. `CloseTo[Mut[T], dest]` runs only after the body returns
success: lamports move with a checked add, the data length in the input
buffer is set to 0, and the owner becomes the system program. The referenced
account for `HasOne` and `Owner` is declared first so its pointer exists. A
constraint failure returns `1014` (`RT_ERR_CONSTRAINT`). One constraint per
account. `Executable` and `Ata` are not in this cut. The alias check peels
that one wrapper, so two `HasOne[Mut[T], ...]` parameters are still `PS3000`.

`@event` is a fixed-width value, not an account. `emit(Name(field, ...))`
writes `sha256("event:" + Name)[..8]` and the packed fields (integers, bool,
Pubkey, or a unit enum) and logs that one slice with `sol_log_data`. The
payload cap is 1016 bytes. The IDL `events` list carries the discriminator.
`decode_event` on the client reads it back. An event cannot be stored.

`system_transfer(src, dest, lamports)` is the System program's Transfer
instruction (u32 tag 2, then a u64). `src` and `dest` are instruction
accounts (`Signer` or `Mut`) and must be different names. The client appends
the System program and marks those accounts writable. A missing System
account returns `1007`.

`TokenAccount` and `TokenMint` are foreign accounts: the program checks that
a token account is writable and does not check owner, size, or discriminator.
A mint is read-only in the outer transaction. `token_transfer` and
`token2022_transfer` are instruction byte 3 (a u64 amount) with source,
destination, and a `Signer` authority. `ata_create` is associated-token
CreateIdempotent (byte 1) and always names the legacy token program. The
client appends System, Token, Token-2022, and the ATA program only when the
instruction needs them. A missing program returns `1007`. These calls are
rejected inside a helper.

The dispatch entry is disc, function pointer, then a spare `uint64_t`. The
SBF linker writes a rodata function relocation as an `lddw` immediate and
the high half lands twelve bytes past the pointer. The spare word catches
that write so the next discriminator, and any constant after the table,
stays intact. The loader rewrites the function pointer from `.rel.dyn`.

A program may be split across `.py` files in one directory. `from acct import
Counter` is legal when `acct.py` is a sibling of the entry file. The compiler
reads the sibling as text and parses it. It never imports the module, so the
build cannot run user code. `import os`, `from typing import Any`, relative
imports, aliases, and star imports stay `PS1001`. Names the file did not
import stay unknown, even if another name from that sibling was imported.
Accounts, errors, enums, structs, events, and helpers from a loaded sibling
are part of the program. An instruction is included only when some loaded
file imports it by name. Runtime logs use that file's basename.

## Phase 3 emit invariants

The C emitter (`src/pythsol/compiler/emit.py`) against the runtime
(`src/pythsol/runtime/pythsol_rt.h`) keeps these guarantees — regression-guarded
by `tests/test_phase3_litesvm.py` (real LiteSVM execution) and the golden
fragments in `tests/test_phase3_emit.py`:

- **Determinism** — two `emit_program` runs over identical source emit
  identical C bytes; two builds emit identical `.so` sha256 (manifest-pinned).
- **No globals** — the SBF loader rejects writable ELF sections; the runtime
  uses only stack buffers with static bounds (SBF stack ≈ 4 KB).
- **Line-true errors** — every `rt_fail_log` carries the Python `file:line`
  (declaration line for role checks, statement line for `require`/arithmetic):
  `Custom(6000)` + `(counter.py:51)` on-chain for the counter's unauthorized
  revert. Checked arithmetic logs the helper's return code (`1009` overflow,
  `1010` division by zero) rather than a hard-coded `1009`.
- **Cropped dispatch** — `rt_entrypoint` consumes the 8-byte instruction
  discriminator before dispatch; user instruction data starts at offset 0 of
  `rt->data` with `rt->data_len` excluding the disc.
- **CPI ABI pinned** — 5-arg `sol_invoke_signed_c`, 16-byte `SolAccountMeta`,
  56-byte `SolAccountInfo` with by-value `data_len`, `"ProgramDerivedAddress"`
  PDA suffix, System program in the caller's account list for `Init` CPIs.
  Full table: [ADR-0010](docs/decisions/ADR-0010-runtime-abi-and-input-layout.md).

## Product surface

`pythsol build` hashes the generated C, the package version, the clang version,
the arch, and the runtime header. A cache hit copies `program.so` and skips
clang. C, the IDL, the client, and `manifest.json` are still written. The
manifest field `cache` is `hit`, `miss`, or `off`. The cache directory is
`PYTHSOL_CACHE` or `PYSOL_CACHE`, unless `PYTHSOL_NO_CACHE` is set. The default
is `%LOCALAPPDATA%/pythsol/cache` on Windows and `~/.cache/pythsol` elsewhere.

`pythsol test` builds, then runs pytest with the plugin in
`src/pythsol/testing/plugin.py`. Fixtures are `svm`, `program`, `payer`,
`accounts`, and `send`. An `Init` account is the PDA for `param.seed` or the
snake_case account name. One derived bump fills a data argument named `bump`.
`expect_error("Unauthorized")` maps the error name to `6000 + index`. The
subprocess sets `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and passes
`-p pythsol.testing.plugin`. `--localnet` starts `solana-test-validator` and
deploys when those binaries exist. The fixtures still talk to LiteSVM.

The IDL object `metadata.pythsol.cpi` stores `ata`, `pays`, `system`, `token`,
and `token2022` for each instruction. `pythsol client` on a `.json` file uses
that to append programs and to mark an init signer writable. Unconstrained
account metas do not grow extra keys. `pythsol cpi` is the same client with a
header: a generic on-chain invoke is not lowered.

`pythsol serve` binds `127.0.0.1`, `localhost`, or `::1` only. `POST /v1/check`
and `POST /v1/emit` call the compiler. `POST /v1/compile` runs `pythsol build`
on that generated C when the SBF tools are installed, and returns the `.so`
as base64. User source is parsed, not executed. There is no hosted Pyodide
worker and no public compile service.

`pythsol verify` exits 0 on a sha256 match and 3 on a mismatch. `pythsol profile`
reads `consumed N of` and `(file.py:line)` from logs. `pythsol idl-publish`
writes an IDL and prints `anchor idl init`. It exits 1 when `anchor` is not on
`PATH`, after the file exists. `--dry-run` does not look for `anchor`.

Data enums and `Vec` are still rejected. Phase 11 (translations, comprehensions,
a second IR, in-browser SBF) is not scheduled. Version stays `0.1.0`.
