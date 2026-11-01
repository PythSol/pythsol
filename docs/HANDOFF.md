# Handoff for the next agent

Read this before changing the compiler, the playground, or the docs.
The user goal is a working product: write typed Python, get a native Solana
program, and host a light-themed site like https://typesol.com/ (landing,
docs, playground). TypeSol is TypeScript. This project is Python. Do not
copy TypeSol's compute-unit table, token, or dark theme.

Today's date in the last session was 2026-10-31. Version is **0.1.0**.
CHANGELOG stays **Unreleased**. IDL spec stays **0.1.0**. Do not cut a
release or publish to PyPI unless the user gives credentials and an explicit
publish order.

## Goal

Typed Python subset → parse with `ast` (never execute user code) → subset /
resolve / typecheck → ProgramModel → C + `pythsol_rt.h` → Agave clang
`-target sbf` → `.so` + Anchor-style IDL + solders client + manifest.

The public site, served by `pythsol serve` on `127.0.0.1:8765`:

| URL | What it is |
|---|---|
| `/` | Landing |
| `/docs` | Short docs that ship with the CLI |
| `/playground` | Editor: Check, Show C, Compile .so |
| `/site.css`, `/app.css`, `/app.js` | Assets. CSS is a file. Inline `<style>` is blocked by CSP `default-src 'self'`. |

`pythsol serve --public --host 0.0.0.0` is the hostable mode: check and emit
only. Compile stays off. A longer Starlight site lives in `web/docs` (`npm run
build` → `web/docs/dist`).

Theme: light only. Python blue `#306998`, yellow `#FFD43B`, Solana purple
`#9945FF` and mint `#14F195` as small accents. Tokens:
`web/shared-tokens/tokens.json`.

## Already built

Compiler: accounts, PDAs (one seed + bump), `require`, control flow, helpers,
`@struct`, `Option`, `FixedString`, `FixedArray`, unit enums, data enums
(`Name: u64` = tag plus reserved payload), `Vec[T, N]`, events, `system_transfer`,
token / Token-2022 / ATA CPI, sibling modules, constraints (`Seeds`, `HasOne`,
`CloseTo`, `Owner`, `Address`).

CLI: `check`, `build` (cache keyed on C + clang + header + flavor
`sbf-o2-gc-strip-v1`), `test`, `init`, `idl`, `idl-publish`, `client`, `cpi`,
`port`, `deploy`, `faucet`, `wallet`, `verify` (exit 0 match, 3 mismatch),
`profile` (log parser only), `docs`, `serve`, `doctor`. Scripts: `pythsol` and
`pysol`.

Examples: `examples/counter`, `ledger`, `vault`, `escrow`. Init templates match
those four. Gallery: `docs/gallery/index.json` (four entries).

Testing: pytest plugin `pythsol.testing.plugin`, fixtures `svm`, `program`,
`payer`, `accounts`, `send`. `expect_error` asserts only when the `with` body
does not raise. LiteSVM program id used in tests:
`F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU`. Two signers cost 10000 lamports
in fee, one signer 5000.

Local SBF tools on this machine:
`Spikes/tools/platform-tools-1.58`. `locate_platform_tools(None)` also walks
parents of cwd and of `toolchain.py` for `Spikes/tools/platform-tools-*`.
An explicit `PYTHSOL_SBF_SDK` that is unusable raises `PysolError`. A missing
default path returns `None`.

Interpreter: `.venv\Scripts\python.exe` (3.12). System Python may be 3.15 and
has no pytest. PowerShell 5.1: chain with `;`, not `&&`.

## Left to build

These are still open. Pick from this list. Do not mark them done without a
test or a real host.

1. **Unbounded `Vec[T]`** — rejected. A variable payload in the middle of an
   account moves later fields. `Vec[T, N]` is the supported form. A last-field
   growable vec needs realloc and a new account-size story. Do not silently
   change `Vec[T]` (arity 1) diagnostics: `tests/test_option.py` and
   `tests/test_phase2.py` pin `Vec[u64]` as instruction-arg `PS3001` and
   account-field `PS4001`.
2. **List comprehensions** — subset rejects them (`PS1011`). Lowering them is
   a subset + typecheck + emit change. `pass` is already allowed.
3. **More examples** — four real programs. The old plan asked for ~20. Add
   only programs that `check` and, if they move lamports, run in LiteSVM.
   Do not invent a gallery of stubs. The escrow example moves **lamports**,
   not SPL tokens. Token CPI lives on the token fixture / `token_transfer`.
4. **Hosted docs / playground on the public internet** — local site works.
   Deploying needs a host the user owns. Do not fake a URL. Do not open
   `/v1/compile` on `--public`.
5. **In-browser SBF / WASM clang / second IR / docs i18n** — Phase 11, not
   scheduled. Starlight warns that the `i18n` collection is empty. That is
   expected.
6. **PyPI, audit, Lighthouse, CU-vs-Anchor table** — need a real publish, a
   real audit, a real Lighthouse run, and a measured benchmark suite. Do not
   copy TypeSol's numbers. Do not invent a token.
7. **PDA-signed System Transfer CPI** — the System program refuses Transfer
   when `from` carries data. Paying out of a program account uses
   `rt_move_lamports` (direct debit of a program-owned account). Keep
   `rt_system_transfer` for a `Signer` source.
8. **Instruction-arg data enums** — data enums are account fields. A data
   enum as instruction data is `PS4001`. Payload `.value` is
   `account.field.value`.
9. **Starlight vs CLI docs** — `pythsol serve` `/docs` is
   `src/pythsol/playground/docs.html`. The long site is `web/docs`. Keep both
   honest and in sync when language facts change.

## How later agents mismatch (read this and the work stays short)

**Machine and tools**

- Use `.venv\Scripts\python.exe` and `.venv\Scripts\pythsol.exe`.
- PowerShell 5.1: `;` not `&&`.
- Click 8.5: `result.output` is stdout. Assert `result.stderr` separately.
- `ruff` select is E,F,I,N,UP,B,SIM,RUF. Line length 100. `tests/*` ignores
  E501. That ignore does **not** cover `tests/fixtures/`. S is not selected;
  a `# noqa: S310` will trip RUF100.
- `ruff format --check .` already fails on pre-existing files:
  `src/pythsol/client/gen.py`, `compiler/emit.py`, `idl.py`, `model.py`,
  `resolve.py`, `subset.py`, `typecheck.py`, `tests/test_multifile.py`,
  `tests/test_phase4_language.py`. Do not `ruff format` `emit.py`. Goldens in
  `tests/test_phase3_emit.py` pin exact C, including
  `"return 0u; /* RT_OK */"` and `RtDispatchEntry` with a `spill` field.
  Keep `spill`. Initializer `{ { disc }, &fn }` zero-fills it.
- mypy `--strict` on `src/pythsol` and `examples` only. Explicit `Any` is
  allowed. Unused `# type: ignore` is an error.
- Do not ruff-check `app.js` as Python.

**Compiler**

- Never execute user programs. `ast` only.
- Diagnostics are stable `PSxxxx`. Sort is `(file, line, col, code)`.
- Builds are byte-deterministic. Two-build tests compare `.so` sha256.
  Extra manifest key `"cache"` is allowed. Phase 3 does not snapshot the
  whole manifest.
- `check_tree` is single-file. `check_source` accepts `modules` /
  `module_files`. Do not make `check_tree` discover siblings.
- `cli idl PROGRAM.py` is a command, not a group.
  `tests/test_phase4_language.py` invokes `cli ["idl", path]`.
- Counter initialize: IDL `isSigner` true, `isMut` false. Client still marks
  the payer writable because the instruction pays.
- String-literal fixture: `PS2004` line 14 col 9 (`s = "hi"`). F-strings
  `PS1003` line 14 col 9. `x: str = "hi"` is `PS1007` at the annotation.
- Enum variant tag must equal declaration index.
- One constraint per account. `CloseTo` runs after a successful body and
  rejects a body that `return`s.
- Constraint stub comments: `# type: ignore[name-defined]` **before**
  `# noqa: F821`.
- Runtime codes: UNKNOWN 1, SIGNER 1001, WRITABLE 1002, OWNER 1003, SIZE 1004,
  DISC 1005, OOB 1006, CPI 1007, PDA 1008, OVERFLOW 1009, DIV_ZERO 1010,
  ENUM 1011, OPTION 1012, STRING 1013, CONSTRAINT 1014. Custom errors
  `6000 + index`. Declared values on `@error` members are documentation.
- Rent: `(size+128)*3480*2`. Deploy dry-run rent print: `size * 6960`.
- Compile `-O2`. Link `--gc-sections --strip-all -z notext -z max-page-size=4096 --allow-multiple-definition` and the v0 linker script. This clang
  reports arch `generic` (`linkgeneric.ld`). `--strip-all` does not remove
  `.rel.dyn`. No `-Werror`.
- Token program id and transfer byte `3` then u64 LE are already verified.
  ATA CreateIdempotent data byte `1`, 6 metas, always the legacy token
  program. No `ata2022_create`.
- Client generators must not emit `import pythsol`. Generated clients import
  solders only. Do not rewrite `src/pythsol/client/gen.py` just to format it.
- IDL unconstrained account metas stay unchanged. Events key always present.
  Event objects have `"discriminator"` and `"index": False`.
  `metadata.pythsol.cpi[snake]` = `{ata, pays, system, token, token2022}`.
  `idl_json` uses `sort_keys=True`.
- `ProgramModel.snake_name` is `snake_case(self.name)`. `instruction()`
  matches the Python name.

**Playground and tests**

- `/` is the landing page. The editor is `/playground`. Tests that used to
  GET `/` for `<textarea>` and `/app.js` now GET `/playground`.
- Wheel must force-include html, css, and js (see `pyproject.toml`).
- `pythsol test` sets `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and
  `-p pythsol.testing.plugin`. Do not also add `tests/conftest.py`
  `pytest_plugins` if the entry point is installed.
- Template tests live in `src/pythsol/cli/templates.py` and are written by
  `init` to `tests/test_program.py`. They use plugin helpers only: no
  `struct.pack`, no compiler import.
- Fixture vault (`tests/fixtures/vault.py`) uses seed `"box"`. Example vault
  uses `b"vault"`, size 49. Example escrow size 81, seed `b"escrow"`.
- `expect_error` used to assert after `finally` and swallow body exceptions.
  It now asserts only on a clean `with` exit. Keep that.
- solders is a test extra. Plugin imports it lazily. Missing solders +
  `PYTHSOL_TEST_SO` set → `pytest.fail`. Otherwise skip.
- Faucet and deploy refuse mainnet without `--yes` (deploy) or always
  (faucet), before HTTP / build.
- Wallet writes Solana CLI JSON and `chmod 0o600`. On Windows the mode is
  not really 0600; tests spy chmod and check mode only when `os.name != "nt"`.
  Secret prints only with `--show-secret`.

**When you add a language feature**

Follow `docs/guides/recipes.md`: subset known callable, typecheck, model,
emit, runtime header, client, IDL flag, negative fixture (code+line+col),
LiteSVM if it runs. Do not hide a gap with a comment.

## How to verify

```powershell
.venv\Scripts\python.exe -m pytest tests\test_playground.py tests\test_product_cli.py tests\test_data_enum.py tests\test_vec_pda.py -q --tb=short
.venv\Scripts\pythsol.exe check "examples\counter\programs\counter.py"
.venv\Scripts\pythsol.exe serve --host 127.0.0.1 --port 8765
```

Then open `http://127.0.0.1:8765/`, `/docs`, `/playground`. Hard-refresh if
CSS looks missing.

Shorter status list: `docs/STATUS.md`. TypeSol gap list:
`docs/comparison-typesol.md`. Architecture: `docs/architecture.md`.
Plan: `TRD.md` phases 0–10 in scope, phase 11 not scheduled.
