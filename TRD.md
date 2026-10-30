# TRD — PySol: Technical Requirements Document

| Field | Value |
|---|---|
| Working name | **PySol** [ASSUMPTION — see PRD] |
| Document | Technical Requirements Document, companion to `PRD.md` |
| Version / date | 0.1 draft — 30 Oct 2026 |
| Basis | Typesol repo/docs/landing (read); Typesol playground (metadata only); general Solana/Python knowledge |

Conventions: **[VERIFIED]** = observed in a Typesol source. **[ASSUMPTION]** = unverified; must be validated by a spike or review. Requirement IDs use `TR-*`.

---

## 1. Scope and Research Basis

PySol is a Python-subset-to-SBF compiler plus tooling. The reference architecture is Typesol's pipeline **[VERIFIED]**:

```
program.ts → tsc typecheck → subset check → ProgramModel → C (+ typesol_rt.h) → clang -target sbf + ld.lld → .so
                                                └→ Anchor IDL
```

Typesol also lowers the checked AST directly to C with no IR, relying on clang -O2 for optimization, and documents explicit triggers for introducing an IR later **[VERIFIED: docs/architecture]**. PySol follows the same principle (no IR in v1).

Items **not** verified from Typesol (treat as assumptions): playground internals, deploy-from-browser mechanics, doc-site generator, theming implementation, light theme, rate limiting, snippet storage.

---

## 2. System Architecture Overview

### 2.1 Components

| # | Component | Responsibility | Runs where |
|---|---|---|---|
| C1 | `pysol-compiler` (Python package) | Parse → type-check → subset-check → ProgramModel → C emit → IDL | Local, CI, Pyodide (browser), compile service |
| C2 | `pysol-rt` (C header `pysol_rt.h`) | Entry point, account deserialization, checks, checked math, Borsh, CPI, logging | Compiled into each program |
| C3 | `pysol` (SDK stubs) | `pysol/__init__.py` + `.pyi`: types/decorators used for authoring; raises if executed outside compiler/reference runtime | Dev machine, editor |
| C4 | `pysol-cli` | `pysol` command wrapping C1, toolchain, deploy, faucet, verify | Dev machine, CI |
| C5 | `pysol-client` | Python client library + generator from IDL | Dev machine, apps |
| C6 | `pysol-testing` | pytest plugin + LiteSVM helpers | Dev machine, CI |
| C7 | Playground frontend | Editor, output panes, wallet, tx runner | Browser |
| C8 | Playground backend | Compile API, snippet API, rate limiting | Cloud |
| C9 | Compile workers | Sandboxed toolchain execution | Cloud (isolated) |
| C10 | Docs site | Static site, search, versioned docs | CDN |
| C11 | CI/CD pipeline | Test matrix, release, deployments | GitHub Actions |

### 2.2 Data-flow diagram (text)

```
 ┌─────────────┐  .py  ┌─────────────────────────────────────────────┐
 │ Developer   │─────▶│ pysol-cli                                    │
 │ editor      │      │  check ─▶ compiler(C1) ─▶ ProgramModel       │
 └─────────────┘      │             │               │                │
                      │             ▼               ▼                │
                      │        program.c         program.idl.json    │
                      │             │ (+pysol_rt.h)     │            │
                      │             ▼                   ▼            │
                      │   platform-tools clang/lld   client gen (C5) │
                      │             ▼                   ▼            │
                      │        program.so         program_client.py  │
                      └─────────────┬───────────────────────────────┘
                                    │ deploy (solana program deploy / own loader client)
                                    ▼
                         localnet / devnet / mainnet RPC
```

### 2.3 Playground topology (text)

```
Browser ── static assets ──▶ CDN (docs + playground shell)
  │ Pyodide worker: C1 analyze → diagnostics, C, IDL, client  (no network needed)
  │
  ├── POST /v1/compile {source, options} ──▶ API gateway (rate limit, auth-less, captcha on burst)
  │                                            │ enqueue
  │                                            ▼
  │                                     Job queue (Redis streams)
  │                                            │
  │                                            ▼
  │                               Compile worker pool (gVisor/Firecracker microVM, no network)
  │                                            │ .so + logs ─▶ object store (content-addressed)
  │◀── {artifactId, diagnostics, sha256} ──────┘
  │
  ├── Wallet Standard (user's wallet signs) ──▶ devnet RPC (public/provider)
  └── POST /v1/snippets (optional) ──▶ snippet store (Postgres + object store)
```

---

## 3. Technology Stack and Justification

| Layer | Choice | Justification | Alternatives rejected |
|---|---|---|---|
| Language (compiler, CLI, SDK, client, testing) | **Python ≥ 3.11** | Contributors are Python developers; uses stdlib `ast`; Pyodide can run it in-browser; `match`, `tomllib` (3.11) available | Rust compiler (faster but high contributor barrier, contradicts positioning); TypeScript (Typesol's choice — would split the community) |
| Parser | CPython `ast` (via `ast.parse`, feature_version pinned) | Zero dependency, identical syntax to user's Python; never executes user code | tree-sitter (extra dep), libcst (needed only for formatters) |
| Type checking of user code | **Own checker over `ast`** for the subset (bidirectional inference), plus shipped `.pyi` so mypy/pyright give editor feedback | Python's runtime types are too loose; subset needs exact-width ints and account wrappers | Relying on mypy only (can't enforce subset or int widths) |
| Backend | **C → clang (Agave platform-tools) → SBF** | Proven by Typesol **[VERIFIED]**; clang/LLD already handle SBF; small, cheap binaries; readable generated code for audit | See §4 |
| Runtime | Header-only C (`pysol_rt.h`), `static inline` | Dead-code elimination; auditable; no Rust | Linking Rust crates |
| CLI framework | `argparse` + small custom layer, or `click` [ASSUMPTION: pick `click`] | Strict options, completion; `click` has stable ecosystem | Typer (extra dep surface) |
| Config | `pysol.toml` or `[tool.pysol]` in `pyproject.toml` (parsed by `tomllib`) | Python-idiomatic | JSON (Typesol `typesol.json` [VERIFIED]) — less ergonomic for Python |
| Solana Python libs | **solders** (types, tx, keypair) + **solana-py** (RPC) [ASSUMPTION — verify maintenance and API at implementation time] | De-facto Python Solana stack | Home-grown RPC (more work) |
| Local SVM | **LiteSVM Python bindings** [ASSUMPTION — verify PyPI package `litesvm` & API] | In-process, fast, mirrors Typesol's testing [VERIFIED] | `solana-test-validator` only (slow) |
| Test framework | pytest + hypothesis | Standard; property-based fuzzing | unittest |
| Packaging | `uv`/`pip`, build backend `hatchling`; wheels (pure Python) | Simple; PyPI Trusted Publishing | setuptools |
| Lint/format/type | ruff, mypy (strict for compiler), pyright smoke on stubs | Fast, standard | black+flake8 |
| Docs site | **Astro Starlight** [ASSUMPTION] | Static output, Pagefind search, built-in i18n, theming through CSS variables, versioning via plugin or per-tag builds, MDX for interactive widgets | MkDocs Material + mike + mkdocstrings (excellent Python API docs; weaker interactive playground embedding); Docusaurus (heavier) |
| Playground frontend | TypeScript + React (or Preact) island in Starlight; **CodeMirror 6** editor; Web Worker + **Pyodide** | CM6 is lighter and more accessible than Monaco; worker keeps UI responsive | Monaco (≈ MBs, weaker mobile/a11y) |
| Wallet | Wallet Standard (`@wallet-standard/*`) + `@solana/kit`-based tx building [ASSUMPTION] | Wallet-agnostic | Single-wallet SDKs |
| Playground API | **FastAPI** (Python) + Uvicorn | Same language as compiler | Node/Express |
| Queue/rate limit | Redis (streams + token bucket) | Simple, proven | SQS (cloud lock-in) |
| Persistence | Postgres (metadata), S3-compatible object store (artifacts/snippets) | Durable, portable | KV-only |
| Sandbox | gVisor or Firecracker microVM per job, read-only rootfs, no network | Strong isolation for running clang on untrusted-derived C | Plain Docker (weaker) |
| Observability | OpenTelemetry → Prometheus/Grafana/Loki [ASSUMPTION] | Vendor-neutral | Proprietary only |
| Hosting (web) | Static host/CDN (Cloudflare Pages / Netlify / GitHub Pages) | Cheap, fast | — |

---

## 4. Python → SBF Translation Strategy (Options Evaluation)

### 4.1 Options

| Option | Description | Pros | Cons |
|---|---|---|---|
| **A. Transpile to Rust/Anchor** | Python subset → Anchor Rust source → `cargo build-sbf` (Poseidon-style) | Reuses Anchor safety/IDL; easy to audit Rust output; ecosystem-proven | Requires Rust+Anchor toolchain (defeats goal G1/P2); slow builds; 150–190 KB Anchor binaries and high CU **[VERIFIED from Typesol benchmark table, project-reported]**; error messages leak Rust |
| **B. Python subset → C → clang (SBF)** (Typesol model) | Own front-end, emit C against a runtime header, compile with platform-tools clang | No Rust; small/cheap programs (project-reported 5–46% of Anchor CU, ~10× smaller **[VERIFIED claim, not independently reproduced]**); fully deterministic; readable intermediate; clang -O2 free | Must write/maintain the C runtime + emitter; relies on platform-tools; aliasing/semantics work is ours |
| **C. Python subset → LLVM IR directly** (e.g., llvmlite) → SBF | Skip C; emit IR | One fewer stage; finer optimization control | Needs LLVM build with SBF target (platform-tools has it, llvmlite does not); IR emission is harder to audit; large dependency |
| **D. Python subset → own SBPF bytecode backend** | Custom code generator | No external toolchain | Huge effort, optimization quality, high bug risk |
| **E. Embed interpreter (MicroPython/RustPython) on-chain** | Run Python bytecode in program | Full-ish Python | Very large, CU-expensive, nondeterminism risk; rejected (NG1) |

### 4.2 Recommendation: **Option B**

| Criterion | A | **B** | C | D | E |
|---|---|---|---|---|---|
| No Rust on user machine | ✗ | ✓ | ✓ | ✓ | ✓ |
| Binary size / CU | ✗ | ✓ | ✓ | ? | ✗✗ |
| Auditability of intermediate | ✓ | ✓ (C) | ✗ | ✗ | ✗ |
| Implementation effort | ✓ | ~ | ✗ | ✗✗ | ~ |
| Determinism | ✓ | ✓ | ✓ | ✓ | ✗ |
| Proven precedent | ✓ (Poseidon) | ✓ (Typesol) | — | — | — |

**Trade-offs accepted:** dependency on Agave platform-tools (mitigation: pinned hashes, `doctor`, backend interface so a future IR/other toolchain can be added); we own the runtime's correctness (mitigation: differential + fuzz + golden tests, audit).

**Backend interface** (to keep option C/IR open): `Backend.compile(program_model, options) -> BuildArtifacts`. v1 ships `CBackend`. Typesol's documented IR re-evaluation triggers (second backend; data-flow optimizations; aliasing false refusals) are adopted as PySol's triggers **[VERIFIED from Typesol docs]**.

### 4.3 Compilation pipeline (stages)

| Stage | Module | Input → Output | Failure behavior |
|---|---|---|---|
| 1 Parse | `parse.py` | source files → `ast.Module` per file | Syntax error with file:line:col |
| 2 Resolve | `resolve.py` | modules → symbol table; imports limited to `pysol` and project files | Foreign import → diagnostic |
| 3 Subset check | `subset.py` | AST → pass/diagnostics | Each forbidden construct has a code `PS1xxx` and docs link |
| 4 Type check | `typecheck.py` | AST → typed AST, `ProgramModel` | Type errors (`PS2xxx`) |
| 5 Semantic checks | `semantic.py` | ProgramModel → constraints validated, aliasing rules | `PS3xxx` |
| 6 IDL | `idl.py` | ProgramModel → IDL JSON | Schema validation |
| 7 Emit | `emit/*.py` | ProgramModel → `program.c` | Internal error `PS9xxx` (bug) |
| 8 Toolchain | `toolchain.py` | `program.c` → `.so` | Toolchain missing → `doctor` guidance |
| 9 Manifest | `manifest.py` | all → `program.build.json` (versions, sha256 of sources, C, `.so`) | — |

Compiler never imports or executes user modules (**TR-SEC-01**).

---

## 5. Language Surface and Semantics

### 5.1 Supported constructs (v1.0 target)

| Category | Supported | Rejected (examples) |
|---|---|---|
| Types | `u8…u128`, `i8…i128`, `bool`, `Pubkey`, `Hash`, `FixedArray[T,N]`, `FixedString[N]`, `Option[T]`, `Vec[T]` (account-resizing), `@account` structs, nested structs, unit and data enums | `float`, `complex`, `str` (unbounded), `list`/`dict`/`set` (dynamic), `Any`, `None` outside `Option` |
| Statements | assignment, augmented assignment, `if/elif/else`, `for i in range(...)`, `while`, `match` on enums, `return`, `assert`-like `require()` | `try/except`, `with`, `async`, `yield`, `lambda`, nested functions/closures, `global`, `del`, comprehensions (until v1.x) |
| Functions | `@instruction` entry points, plain typed helper functions (non-recursive; call-graph depth limit) | decorators other than `pysol` ones, `*args/**kwargs`, default mutable args |
| Imports | `from pysol import …`, project modules | any third-party/stdlib import |
| Accounts | `Signer`, `Mut[T]`, `Init[T]`, `InitIfNeeded[T]`, `Account[T]`, `Zeroed[T]`, `Optional[...]` accounts, token accounts, programs, sysvars | — |
| Constraints | `Seeds[...]`, `HasOne[...]`, `CloseTo[...]`, `Address[...]`, `Owner[...]`, `Executable`, `Ata[...]` | arbitrary Python predicates in annotations |
| CPI | System, SPL Token, Token-2022, ATA; generic `invoke` with PDA signing; typed CPI from IDL | — (Metaplex/oracles post-MVP) |
| Events/Errors | `@error`, `emit()`, `emit_cpi()` | exceptions |

### 5.2 Semantic rules (critical for correctness)

| ID | Rule |
|---|---|
| TR-LANG-01 | **Every** parameter, field, local that cannot be inferred from a typed literal/expression must be annotated. No implicit `Any`. |
| TR-LANG-02 | Integer literals are typed by context (bidirectional inference); an out-of-range literal is a compile error. Mixed-width arithmetic requires explicit casts `u64(x)`; widening/narrowing casts are explicit and narrowing is checked. |
| TR-LANG-03 | `+ - *` on fixed-width ints are **overflow/underflow-checked** and abort the instruction. Wrapping ops are explicit (`wrapping_add(a, b)`). |
| TR-LANG-04 | `/` (true division) is rejected; `//` on unsigned is floor division; on signed ints it follows **Python floor semantics** (differs from C/Rust truncation) — implemented in runtime; `%` follows Python semantics; division by zero aborts. |
| TR-LANG-05 | `==`/`!=` on `Pubkey`, ints, bool, enums, fixed arrays are by value. `is` is rejected. |
| TR-LANG-06 | Struct assignment copies value unless the left side is a *reference into account data*; references alias account data (Python-like) and the compiler **refuses** programs where aliasing could make behavior diverge from CPython semantics (same philosophy as Typesol's `assertNotAliased` **[VERIFIED architecture]**). |
| TR-LANG-07 | Evaluation order follows Python (left-to-right; assignment target resolved before RHS). Emitter must preserve it with temporaries. |
| TR-LANG-08 | No recursion; loops must be statically bounded **or** compute-metered (CU meter is the real limit); document unbounded `while` risk. |
| TR-LANG-09 | Heap use is bounded (bump allocator, default 32 KiB, never freed) [mirrors Typesol **[VERIFIED]**]; allocation inside loops is rejected unless hoisted. |
| TR-LANG-10 | **Conformance:** a pure-Python *reference runtime* (`pysol.refrt`) can execute a program's instruction functions against a Python model of accounts, so semantic tests can compare CPython vs SVM outcomes. |

### 5.3 Diagnostics

Format: `path.py:LINE:COL: error[PS2104]: expected u64, found u32 (add explicit cast u64(x))` plus docs URL `https://<docs>/errors/PS2104`. `--json` emits an array of `{code, severity, file, line, col, endLine, endCol, message, help}`. A refused construct must never be silently accepted (**TR-LANG-11**).

Runtime failures log `Error 6000 Unauthorized: <msg> (counter.py:21)` — compatible with Anchor error-code numbering where meanings match (6000+ custom, Anchor framework codes reused) [mirrors Typesol **VERIFIED**].

---

## 6. IDL and Client Generation

### 6.1 IDL

| Requirement | Detail |
|---|---|
| TR-IDL-01 | Output Anchor-compatible IDL; pin a spec version (target the same spec as Typesol's `0.1.0` **[VERIFIED]**; confirm against current Anchor at implementation [ASSUMPTION]). |
| TR-IDL-02 | Includes `address`, `metadata`, `instructions` (discriminators, accounts with `writable`, `signer`, `pda`, `relations`, `optional`, `address`, args), `accounts`, `events`, `errors`, `types`, docs from docstrings. |
| TR-IDL-03 | Discriminators: Anchor-compatible (sha256 prefix, 8 bytes) by default; `@discriminator(...)` override for interface programs (e.g., transfer hooks) [ASSUMPTION]. |
| TR-IDL-04 | Validate IDL against JSON Schema in unit tests; golden IDL files for each template. |
| TR-IDL-05 | `pysol idl build` re-emits IDL without compiling `.so`. `pysol idl publish` (Could) publishes on-chain. |

### 6.2 Python client generation

| Requirement | Detail |
|---|---|
| TR-CLI-GEN-01 | `pysol client <idl.json> -o <file>` and automatic emission in `pysol build`. |
| TR-CLI-GEN-02 | Generated module is a single file with: `PROGRAM_ID`, dataclasses for accounts/types, `encode/decode` (Borsh), instruction builder functions returning `solders.instruction.Instruction`, PDA helpers (`find_counter_pda(authority)`), error enum, event decoders, async and sync RPC convenience wrappers. |
| TR-CLI-GEN-03 | The client has no dependency on the compiler (only `solders`, `solana`). |
| TR-CLI-GEN-04 | Round-trip test per template: build tx → LiteSVM → decode state. |
| TR-CLI-GEN-05 | Optional TypeScript client generation is **out of scope** for v1 (Anchor's TS client can read the IDL unchanged). |

Example generated usage:

```python
from target.counter_client import CounterClient
client = CounterClient(rpc_url="https://api.devnet.solana.com", payer=keypair)
await client.initialize()
await client.increment(by=5)
print((await client.fetch_counter()).count)
```

---

## 7. CLI and Configuration Specification

### 7.1 Global behavior

| Item | Spec |
|---|---|
| Binary | `pysol` (also `python -m pysol`) |
| Exit codes | `0` success · `1` failure · `2` usage error · `3` verify mismatch (mirrors Typesol **[VERIFIED]**) |
| Global flags | `--help`, `--version`, `--json`, `--quiet`, `--verbose`, `--no-color`, `--config PATH` |
| Env | `PYSOL_SBF_SDK` (toolchain override), `PYSOL_RPC_URL`, `PYSOL_KEYPAIR`, `NO_COLOR`, `PYSOL_TELEMETRY=0/1` |
| Principles | Strict option parsing; every command prints the exact external command it runs under `--verbose`; `--dry-run` where side effects exist |

### 7.2 Commands

| Command | Purpose | Key flags | Example output |
|---|---|---|---|
| `pysol init <dir>` | Scaffold project | `--name`, `--template counter\|vault\|escrow\|…`, `--no-git`, `--python 3.12` | `Created my-app/ (template: counter)\n  pysol.toml\n  programs/counter.py\n  tests/test_counter.py\nNext: cd my-app && pip install -e . && pytest` |
| `pysol doctor` | Diagnose environment | `--fix` (prints/executes fix commands with confirmation) | `✓ Python 3.12.4\n✓ platform-tools v1.xx (clang 18)\n✗ Solana CLI not found → run: sh -c "$(curl -sSfL https://release.anza.xyz/stable/install)"\n✓ keypair ~/.config/solana/id.json\n✓ RPC devnet reachable` |
| `pysol check [path]` | Type + subset check only | `--json`, `--files` (editor buffers), `--strict` | `programs/counter.py: OK (2 instructions, 1 account, 1 error)` |
| `pysol build [path]` | Compile program(s) | `--release` (default), `--profile` (CU logging), `--sbpf v0\|v1\|v2`, `--out DIR`, `--emit-c` | `Built counter\n  target/counter/counter.so  12.8 KB\n  target/counter/counter.json (IDL)\n  target/counter/counter_client.py\n  target/counter/counter.build.json  sha256:ab12…` |
| `pysol test` | Build + run pytest | `--localnet`, `-k`, passthrough args | pytest output; on failure shows program logs and `(counter.py:21)` |
| `pysol deploy` | Build then deploy/upgrade | `--url devnet\|localhost\|mainnet-beta\|URL`, `--keypair`, `--program-keypair`, `--dry-run`, `--yes` (required for mainnet in non-TTY) | `Program ID: 7Xk…\nPayer balance: 4.2 SOL; estimated rent: 0.09 SOL\nDeployed. Signature: 5Gh…` |
| `pysol faucet` | Request devnet SOL | `--amount`, `--url` | `Airdropped 2 SOL (sig 3fT…). Balance: 2.00 SOL` / on rate limit: `Rate-limited. Use https://faucet.solana.com` |
| `pysol wallet new\|address\|balance` | Key helpers | `--outfile`, `--show-secret` | Writes `0600` keypair file; never prints secret by default |
| `pysol idl build\|publish` | IDL ops | `--address`, `--url` | path or signature |
| `pysol client <idl>` | Generate client from IDL | `-o`, `--address` (fetch IDL on chain) | path |
| `pysol cpi <idl>` | Generate typed CPI helpers (Could) | `-o` | path |
| `pysol port <idl>` | Skeleton program from Anchor IDL | `-o` | path + list of TODOs |
| `pysol verify` | Rebuild and compare with on-chain ELF | `--address`, `--url`, `--dump file.so` | exit 0 `MATCH sha256:…`; exit 3 `MISMATCH` with diff summary |
| `pysol profile` | CU per Python line | `--logs FILE` or `--tx SIG` | table `counter.py:22  110 CU` |
| `pysol emit-c [path]` | Print generated C | `-o` | C source |
| `pysol docs` | Open docs/offline reference | — | — |

### 7.3 Configuration (`pysol.toml`)

```toml
[project]
name = "my-app"
python = ">=3.11"

[[programs]]
name = "counter"
entry = "programs/counter.py"
# program id comes from target/deploy/counter-keypair.json unless overridden
# address = "…"

[build]
sbpf = "v0"
heap_kib = 32
out_dir = "target"

[cluster]
default = "devnet"

[cluster.devnet]
url = "https://api.devnet.solana.com"
keypair = "~/.config/solana/id.json"
```

Alternatively `[tool.pysol]` in `pyproject.toml` (same keys).

### 7.4 Programmatic API

```python
from pysol.compiler import generate, build
result = build("programs/counter.py", out_dir="target/counter", program_id="…")
result.so_path, result.idl, result.diagnostics, result.c_source
```
Public API is semver-governed; internals under `pysol._internal`.

---

## 8. Local Testing Environment and Mock Validator

| Requirement | Detail |
|---|---|
| TR-TEST-LOC-01 | `pysol-testing` pytest plugin exposes fixtures: `svm` (LiteSVM instance), `program` (built `.so` loaded), `payer`, `accounts` (name-addressed accounts derived from IDL), `send(ix, signers)`. |
| TR-TEST-LOC-02 | Tests reference accounts by IDL names and plain Python values — no manual byte packing (mirrors Typesol's `typesol/testing` **[VERIFIED]**). |
| TR-TEST-LOC-03 | Build cache keyed by sha256(source + compiler version + toolchain version) so repeated test runs skip clang. |
| TR-TEST-LOC-04 | `--localnet`: start `solana-test-validator` with a temp ledger on a free port, deploy, run tests, tear down; respects `PYSOL_RPC_URL`. |
| TR-TEST-LOC-05 | Logs and compute units are exposed on every result (`result.logs`, `result.compute_units`). |
| TR-TEST-LOC-06 | Time-travel helpers (`svm.warp_to_slot`, clock sysvar) [ASSUMPTION: depends on LiteSVM bindings]. |

Example:

```python
def test_increment(svm, program, payer):
    counter = program.initialize(authority=payer)
    program.increment(authority=payer, counter=counter, by=5)
    assert program.fetch("Counter", counter).count == 5

def test_unauthorized(svm, program, payer, other):
    counter = program.initialize(authority=payer)
    with program.expect_error("Unauthorized"):
        program.increment(authority=other, counter=counter, by=1)
```

---

## 9. Playground Architecture

Typesol's playground is described as compiling "in your browser" and showing generated C, IDL and client **[VERIFIED from page metadata only]**; everything else below is [ASSUMPTION].

### 9.1 Responsibilities split

| Capability | Where | Reason |
|---|---|---|
| Parse, subset/type check, diagnostics, C/IDL/client generation | **Browser** (Pyodide in a Web Worker) | Instant feedback, no server cost, no code leaves browser |
| C → SBF `.so` | **Compile service** (default) | clang with SBF target is not available in WASM today [ASSUMPTION — spike OQ-3 to test a WASM build of LLVM] |
| Transaction building and signing | **Browser** + user's wallet | Keys never leave wallet (TR-SEC-02) |
| RPC to devnet | Browser → public/provider RPC (through optional proxy that only forwards allow-listed methods) | Avoid exposing provider keys |
| Snippet sharing | Backend | Persistence |

Fallback: if Pyodide fails to load, the editor works with server-side `check` (`POST /v1/check`).

### 9.2 Frontend modules

| Module | Spec |
|---|---|
| Editor | CodeMirror 6, Python mode + PySol completions from `.pyi`-derived JSON; diagnostics gutter + panel; vim/emacs keymaps optional; ARIA live region for diagnostic count |
| Output tabs | Generated C · IDL · Python client · Build log · Program logs · Accounts (decoded) |
| Examples picker | Loads from `/gallery/index.json`; deep link `?example=counter` |
| Build button | Calls `/v1/compile`; shows queue position; cancel supported |
| Wallet | Wallet Standard connect/disconnect; network pinned to **devnet**; mainnet unavailable (NG6) |
| Deploy panel | Shows program size, estimated rent (≈ 6,960 lamports/byte for program data **[VERIFIED figure from Typesol landing]**, plus buffer/upgrade headroom [ASSUMPTION]), fee, program ID; requires explicit confirm; writes chunks via loader transactions signed by wallet |
| Invoke panel | Form generated from IDL; PDA auto-derivation; account chooser; simulates first (`simulateTransaction`), then optional send; displays logs/CU |
| Faucet | Button invoking devnet airdrop RPC with backoff + link to web faucet |
| State | URL hash for non-sensitive state (`#example`, `#snippet=<id>`); `localStorage` for editor draft and theme; **no secrets stored** |

### 9.3 Compile API

| Endpoint | Method | Request | Response |
|---|---|---|---|
| `/v1/compile` | POST | `{source: {files:{"programs/main.py":"…"}}, options:{sbpf:"v0",profile:false}, compilerVersion:"0.5.2"}` | `202 {jobId}` or `200` cache hit `{artifactId, sha256, diagnostics[], sizeBytes}` |
| `/v1/jobs/{id}` | GET | — | `{state: queued\|running\|done\|failed, position, logs, artifactId}` |
| `/v1/artifacts/{id}.so` | GET | — | binary (immutable, cacheable, `Content-Type: application/octet-stream`) |
| `/v1/check` | POST | source | diagnostics only (fallback) |
| `/v1/snippets` | POST | `{files, title?, example?}` | `{id, url}` (immutable) |
| `/v1/snippets/{id}` | GET | — | snippet JSON |
| `/healthz`, `/metrics` | GET | — | ops |

Limits (all [ASSUMPTION], configurable): body ≤ 256 KB; ≤ 20 files; job wall-clock ≤ 30 s; CPU ≤ 2 cores; memory ≤ 1 GiB; output `.so` ≤ 512 KB; per-IP 10 compiles/min and 200/day; global concurrency cap with 429 + `Retry-After`; proof-of-work/captcha challenge on sustained bursts.

### 9.4 Sandboxed execution

1. API validates schema/size, canonicalizes source, computes `cacheKey = sha256(source ‖ compilerVersion ‖ toolchainVersion ‖ options)`; returns cache hit if present.
2. Worker starts a fresh microVM/gVisor sandbox from an immutable image containing only: Python + `pysol-compiler` + platform-tools clang/lld (pinned by hash). **No network, read-only root, tmpfs workdir, seccomp, non-root UID, PID/CPU/memory/time cgroups.**
3. Compiler stage reads source via `ast.parse` only (never executes) and emits C; clang runs on **generated** C, never on user-supplied C (TR-SEC-03).
4. Output `.so` + manifest are written to object store keyed by `cacheKey`; sandbox is destroyed.
5. Worker logs only metadata (sizes, timings, error codes), not source, unless the snippet was shared.

### 9.5 Snippet storage

Immutable, content-addressed (`id = base32(sha256(canonical_json))[:12]`); stored in object store with metadata row in Postgres; no accounts or PII; server-side scanning for abuse patterns [ASSUMPTION]; deletion on request via signed token issued at creation; unviewed-for-90-days retention [ASSUMPTION]. Rendering escapes all content; snippet code is never executed by the page.

### 9.6 Rate limiting and abuse

| Layer | Control |
|---|---|
| Edge/CDN | WAF rules, bot score, request size caps |
| API | Token bucket in Redis keyed by IP + coarse fingerprint (no cookies) |
| Queue | Max queue depth; shed load with 429 |
| Worker | Hard cgroup limits; compile watchdog |
| Product | No mainnet; devnet-only; unaudited banner |

---

## 10. Documentation System

| Concern | Design |
|---|---|
| Generator | Astro Starlight (MDX) [ASSUMPTION]; content in `docs/` in the main repo (docs change with code) — "Edit this page on GitHub" links on every page (as on Typesol **[VERIFIED]**) |
| Versioning | Docs built per release tag (`/0.5/`, `/latest/`, `/next/`); version selector; footer stamp "Docs for PySol vX.Y.Z, built from <commit> (<date>)" (mirrors Typesol **[VERIFIED]**) |
| API reference | Generated from Python docstrings/stubs via a small extractor (or `griffe`) into MDX; language reference hand-written and tested |
| Search | Pagefind static index built at deploy; filters by version; `/` shortcut; keyboard-navigable results; indexes headings, code, error codes (`PS2104` is directly searchable) |
| Code blocks | Shiki highlighting with both theme palettes; copy button component (TR-DOC-01); line-highlighting; file title; ```` ```python test ```` marks code to be compiled in CI |
| Example testing | `scripts/extract_examples.py` extracts blocks tagged `test` (and `test-fail code=PS2104` for expected diagnostics) → compiled in CI via `pysol check/build`; output compared to inline `# expect:` comments; unmatched → CI failure |
| Playground embed | `<Playground example="counter" />` MDX component lazily hydrates island on interaction |
| Link/asset checks | `lychee` link check; Lighthouse CI; axe CI |
| i18n readiness | Starlight i18n config with `en` only; strings in `src/content/i18n`; docs routes `/en/…` redirect from `/` |
| Page inventory | See PRD §5.3 |
| Changelog/roadmap | `CHANGELOG.md` rendered as a docs page; roadmap generated from GitHub Project export JSON |

---

## 11. Theming System

### 11.1 Mechanism

| Item | Spec |
|---|---|
| Tokens | Design tokens in `tokens.json` (source of truth) → compiled to CSS custom properties by a build script; also exported to Shiki and CodeMirror theme objects so docs and playground cannot drift |
| Attribute | `<html data-theme="light|dark">`; `color-scheme` set accordingly; tokens defined on `:root[data-theme="light"]` and `:root[data-theme="dark"]` |
| Preference | `localStorage["pysol-theme"] ∈ {"light","dark","system"}`; `system` follows `prefers-color-scheme` and updates live |
| No FOUC | Blocking inline `<script>` in `<head>` (≤ 20 lines, try/catch) resolves theme before first paint; CSP nonce/hash allowed |
| Cross-surface | Docs and playground share the origin (or `BroadcastChannel`/query param) so the choice persists across them |
| Toggle | Accessible button (`aria-pressed`, label "Theme: light/dark/system"); cycles; announces change |
| Reduced motion | Transitions only when `prefers-reduced-motion: no-preference` |

### 11.2 Python-inspired light theme tokens [ASSUMPTION — final values need a contrast audit]

| Token | Light (Python-inspired) | Dark | Use |
|---|---|---|---|
| `--bg` | `#FFFFFF` | `#0B0D12` | Page |
| `--bg-subtle` | `#F5F8FC` | `#12151C` | Sidebar, cards |
| `--surface-code` | `#F3F6FA` | `#161A23` | Code blocks |
| `--text` | `#1B2430` | `#E6EAF2` | Body |
| `--text-muted` | `#4A5668` | `#9AA6B8` | Secondary |
| `--border` | `#D5DDE8` | `#262C38` | Dividers |
| `--primary` | `#306998` (Python blue, deep) | `#6EA8DC` | Links, primary buttons (white text on `#306998` ≈ 6:1) |
| `--primary-strong` | `#255077` | `#8DBDE8` | Hover |
| `--accent` | `#FFD43B` (Python yellow) | `#FFD43B` | Highlights, selection, active-nav marker, focus ring outer, badges — **never body text on white** |
| `--on-accent` | `#1B2430` | `#0B0D12` | Text on yellow (≥ 10:1) |
| `--success/--warning/--danger` | `#1E7F4F / #8A5A00 / #B3261E` | lighter variants | Diagnostics (always with icon + label) |
| `--focus-ring` | 2px `#255077` + 2px `#FFD43B` outer | same | Visible focus ≥ 3:1 vs adjacent colors |
| Syntax palette | Keywords blue, strings green-teal, numbers amber-brown, comments gray; yellow reserved for current-line/selection | tuned for dark | AA contrast on `--surface-code` |

Signature touches: two-tone blue/yellow logo mark; yellow underline on active nav; subtle blue-tinted `--bg-subtle`; monospace for code and inline identifiers; generous spacing; no gradients required.

### 11.3 Acceptance

- `axe` reports zero contrast violations in both themes for all page templates (CI).
- Visual regression snapshots (Playwright) for light/dark on 5 key pages.
- Toggle persists across navigation, reload, and between docs ↔ playground.

---

## 12. Data Models and Schemas

### 12.1 Project (`pysol.toml` → internal JSON)

```json
{
  "$id": "https://pysol.dev/schemas/project-0.1.json",
  "type": "object",
  "required": ["project", "programs"],
  "properties": {
    "project": {"type":"object","required":["name"],"properties":{"name":{"type":"string","pattern":"^[a-z][a-z0-9_-]{0,62}$"},"python":{"type":"string"}}},
    "programs": {"type":"array","minItems":1,"items":{"type":"object","required":["name","entry"],"properties":{"name":{"type":"string"},"entry":{"type":"string"},"address":{"type":"string","description":"base58 program id"}}}},
    "build": {"type":"object","properties":{"sbpf":{"enum":["v0","v1","v2"]},"heap_kib":{"type":"integer","minimum":32,"maximum":256},"out_dir":{"type":"string"}}},
    "cluster": {"type":"object"}
  }
}
```

### 12.2 Build manifest (`<name>.build.json`)

| Field | Type | Notes |
|---|---|---|
| `schema` | string | `"pysol.build/1"` |
| `program` | string | name |
| `compilerVersion`, `runtimeVersion`, `pythonVersion` | string | |
| `toolchain` | object | `{clang, lld, platformToolsVersion, sdkSha256}` |
| `sbpf` | string | |
| `sources` | array | `{path, sha256}` |
| `generatedC` | object | `{sha256}` |
| `binary` | object | `{path, sizeBytes, sha256}` |
| `idl` | object | `{sha256, spec}` |
| `createdAt` | string | omitted when `SOURCE_DATE_EPOCH` set (reproducibility) |

### 12.3 Template manifest (`templates/<id>/template.toml`)

| Field | Type | Description |
|---|---|---|
| `id`, `title`, `description` | string | |
| `level` | enum | beginner / intermediate / advanced |
| `concepts` | string[] | e.g., `["pda","cpi","spl-token"]` |
| `minPysolVersion` | semver | |
| `files` | string[] | files copied by `init` |
| `tests` | string | path to template test |
| `playground` | bool | exposed in gallery |
| `license` | string | SPDX (MIT) |

### 12.4 Playground session and snippet

```sql
-- Postgres (metadata only; no PII, no keys)
CREATE TABLE snippets (
  id            text PRIMARY KEY,           -- content-addressed
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_viewed   timestamptz,
  title         text,
  example_id    text,
  compiler_ver  text NOT NULL,
  size_bytes    int  NOT NULL,
  blob_key      text NOT NULL,              -- object store key
  delete_token_hash bytea,                  -- optional
  flagged       boolean NOT NULL DEFAULT false
);
CREATE TABLE compile_jobs (
  id            uuid PRIMARY KEY,
  cache_key     text NOT NULL,
  state         text NOT NULL CHECK (state IN ('queued','running','done','failed')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  duration_ms   int,
  error_code    text,
  artifact_key  text
);
CREATE INDEX ON compile_jobs (cache_key);
```

Client-side playground session (in-memory + `localStorage` draft; never uploaded unless shared):

```json
{
  "schema": "pysol.session/1",
  "files": {"programs/main.py": "…"},
  "selectedExample": "counter",
  "cluster": "devnet",
  "lastBuild": {"artifactId": "…", "sha256": "…", "diagnostics": []},
  "deployments": [{"programId": "…", "signature": "…", "slot": 0}],
  "ui": {"theme": "system", "tab": "idl"}
}
```

### 12.5 Gallery index (`gallery/index.json`)

`[{id, title, summary, level, concepts[], sourcePath, playgroundUrl, tests: "passing"}]` — generated in CI from `examples/` metadata headers; consumed by docs gallery and playground picker.

---

## 13. Security Model

### 13.1 Assets and threats

| Asset | Threat | Control |
|---|---|---|
| User private keys | Theft via playground/CLI | Playground never accepts secret keys (no import UI); wallet signs; CLI reads keypair files locally only; `0600` perms; secrets redacted in logs; `--show-secret` explicit |
| Compile infrastructure | Code execution, DoS, SSRF, crypto-mining | Parse-only (no exec); network-less sandbox; resource limits; generated-C-only compile; queue/rate limits |
| Generated programs | Miscompilation → exploitable contract | Differential/fuzz/golden tests, aliasing refusals, checked math, audit, `verify`, visible warnings |
| Supply chain (PyPI, npm, platform-tools, CI) | Malicious dependency/release | See §13.3 |
| Playground users | Phishing via shared snippet, XSS | Immutable snippets, strict CSP, escape/sanitize, no HTML in snippets, tx preview before signing, unaudited banner |
| Telemetry | Privacy leakage | Opt-in CLI; aggregate-only web; no source collection |

### 13.2 Key handling requirements

| ID | Requirement |
|---|---|
| TR-SEC-01 | Compiler and servers never execute user Python. |
| TR-SEC-02 | No server endpoint accepts, receives, logs, or stores private keys or seed phrases; CI includes a test that scans API schemas and logs for key-like fields. |
| TR-SEC-03 | clang is invoked only on compiler-generated C; user strings embedded in C (error messages, seeds) are escaped by a single audited `c_string()` function with fuzz tests. |
| TR-SEC-04 | Browser: CSP `default-src 'self'`; `script-src` with hashes; `connect-src` allow-list (API, RPC); `frame-ancestors 'none'`; Trusted Types where supported. |
| TR-SEC-05 | Transaction preview shows program IDs, account list, lamport movement, and requires explicit user action; no auto-sign. |
| TR-SEC-06 | Deployment to mainnet only via local CLI, requiring `--url mainnet-beta` and interactive confirm (or `--yes`). |

### 13.3 Supply-chain safeguards

| Control | Detail |
|---|---|
| Dependency pinning | `uv.lock`/hashes for compiler; `pnpm-lock` for web; Renovate/Dependabot with review |
| Auditing | `pip-audit`, `osv-scanner`, `npm audit` in CI; fail on high severity |
| Minimal deps | Compiler's runtime deps limited to stdlib + (optional) `click`; client deps: `solders`, `solana` |
| Toolchain pinning | Platform-tools downloaded by Solana's installer; PySol records and verifies sha256 against a pinned allow-list; `doctor` warns on unknown versions |
| Release integrity | PyPI Trusted Publishing (OIDC), no long-lived tokens; Sigstore signatures; SLSA provenance; CycloneDX SBOM attached to releases |
| CI hardening | Pin GitHub Actions by SHA, least-privilege `GITHUB_TOKEN`, branch protection, required reviews, CODEOWNERS for `runtime/` and `emit/` |
| Reproducible builds | Same source + toolchain ⇒ same `.so` bytes; `SOURCE_DATE_EPOCH`; manifest hashes; `pysol verify` |
| Vulnerability disclosure | `SECURITY.md`, private advisories, 90-day policy [ASSUMPTION] |

### 13.4 Security documentation

Docs page "Security model" must state what a compiled program can rely on (generated checks, error codes) versus what remains the developer's responsibility; plus an "Audit package" page (generated C samples, test inventory, known limitations) — modeled on Typesol's doc set **[VERIFIED: pages exist; content not read]**.

---

## 14. Testing Strategy

| Layer | What | Tooling | Gate |
|---|---|---|---|
| Unit | Parser/subset/type-checker/emitter functions; diagnostics (every rejected construct has a test) | pytest | ≥ 90% line coverage in `compiler/` |
| Golden | Generated C and IDL for every template/fixture pinned; update flow `UPDATE_GOLDEN=1` (as Typesol does for C **[VERIFIED]**) | pytest | Diff must be reviewed |
| Execution | Each language feature compiled and run in LiteSVM | pytest + litesvm | All pass |
| Conformance | Same instruction run in CPython reference runtime and SVM; outcomes and account bytes equal | hypothesis + `refrt` | 0 divergences |
| Property/fuzz | Arithmetic per width vs Python `int` oracle; stateful vault/escrow vs Python model; random programs from a grammar for compiler crash testing | hypothesis, atheris (optional) | No crashes; no divergences |
| Differential vs Anchor | counter/vault/escrow twins in Anchor build; identical tx sequences compared for outcome, state, balances (Typesol's approach **[VERIFIED]**) | CI job with Rust+Anchor (optional job, not required for contributors) | Pass on release |
| Security regression | Negative tests for each fixed vuln: missing signer, wrong owner, duplicate writable accounts, PDA mismatch, overflow | pytest | All pass |
| On-chain | Localnet smoke: deploy every example to `solana-test-validator`, drive via generated client; devnet nightly canary (counter) | script + pytest | Nightly green |
| Client | Round-trip encode/decode; IDL schema validation | pytest | Pass |
| CLI | Subprocess tests for every command, flag, exit code, `--json` shape | pytest | Pass |
| Playground E2E | Playwright: load, edit, diagnostics, compile (against staging service), mock wallet deploy on localnet-in-CI, invoke, share link | Playwright | Pass on PR to `web/` |
| Docs examples | Extracted code blocks compiled/checked (§10) | CI script | Pass |
| Accessibility | axe + Lighthouse a11y ≥ 95 | Playwright/axe | Pass |
| Performance | CU and binary size per example vs baseline; compile-time benchmark | bench script | Regression ≤ 5% |
| Load | Compile service load test with k6: 50 concurrent, p95 target | k6 | Meets §17 |

---

## 15. CI/CD, Packaging, Deployment, Observability

### 15.1 CI matrix

| Job | Trigger | Content |
|---|---|---|
| `lint` | PR | ruff, mypy (strict), pyright on stubs, prettier/eslint for web |
| `unit` | PR | Python 3.11/3.12/3.13 × Ubuntu/macOS |
| `toolchain` | PR | Install platform-tools (cached), run execution + golden tests |
| `docs` | PR | Build site, example tests, link check, axe, Lighthouse |
| `web-e2e` | PR touching `web/` | Playwright against preview deploy |
| `differential` | nightly + release | Anchor twins, fuzz long-run |
| `localnet-smoke` | nightly + release | `solana-test-validator` |
| `devnet-canary` | nightly | counter deploy+call; alert on failure |
| `release` | tag `v*` | Build wheels/sdist → SBOM → sign → TestPyPI → smoke install → PyPI (Trusted Publishing) → docs deploy → GitHub Release notes from changelog |

### 15.2 Packaging

- PyPI distributions: `pysol` (meta: CLI + compiler + SDK stubs), `pysol-client` (generated-client runtime helpers), `pysol-testing` (extra: `pip install pysol[test]`). Single version train.
- Pure-Python wheels (`py3-none-any`) + sdist; `py.typed`; entry point `pysol = pysol.cli:main`.
- Runtime header shipped inside the wheel at `pysol/runtime/pysol_rt.h`.
- Install paths documented: `pipx install pysol`, `uv tool install pysol`, `pip install pysol` in venv.

### 15.3 Deployment of web components

| Component | Deployment |
|---|---|
| Docs + playground shell | Static build to CDN on tag/main; preview per PR |
| Compile API + workers | Container images (distroless), IaC (Terraform) [ASSUMPTION], blue/green; workers auto-scale on queue depth |
| Snippet store | Managed Postgres + S3-compatible bucket |
| Secrets | Cloud secret manager; none user-related |

### 15.4 Observability

| Signal | Detail |
|---|---|
| Metrics | compile queue depth, wait/run time, cache hit rate, failure codes, sandbox kills, 429 rate, artifact size distribution |
| Logs | Structured JSON; no source code, no IPs beyond short-lived rate-limit keys (hashed, ≤ 24 h) |
| Traces | OpenTelemetry for API → queue → worker |
| Alerts | p95 compile > 20 s, error rate > 2%, queue depth > threshold, canary failure |
| Product analytics | Aggregate page/event counts via privacy-first tool (Plausible-style) [ASSUMPTION]; CLI telemetry opt-in with documented payload |
| Public status | Simple status page for playground |

---

## 16. Repository Structure and Coding Standards

### 16.1 Layout (monorepo)

```
pysol/
├─ src/pysol/
│  ├─ __init__.py, *.pyi, py.typed        # SDK surface (authoring types/decorators)
│  ├─ compiler/
│  │   ├─ parse.py resolve.py subset.py typecheck.py semantic.py model.py
│  │   ├─ idl.py manifest.py toolchain.py diagnostics.py errors.py
│  │   └─ emit/ (base.py storage.py expressions.py calls.py cpi.py create.py token.py statements.py function.py program.py)
│  ├─ runtime/pysol_rt.h                  # C runtime
│  ├─ cli/ (main.py, commands/*.py)
│  ├─ client/ (gen.py, runtime.py)        # client generator + helpers
│  ├─ testing/ (plugin.py, svm.py)        # pytest plugin
│  ├─ refrt/                              # CPython reference runtime
│  └─ templates/                          # init templates (copies of examples, test-verified)
├─ examples/                              # tested example programs + metadata
├─ test/ (language/ security/ examples/ client/ cli/ conformance/ verification/ golden/ fixtures/ anchor-twins/)
├─ docs/                                  # Starlight content
├─ web/ (playground/ site/ shared-tokens/)
├─ services/ (compile-api/ worker-image/ infra/)
├─ benchmarks/
├─ scripts/ (extract_examples.py, gen_tokens.py, smoke.py, localnet.sh)
├─ .github/ (workflows/ ISSUE_TEMPLATE/ PULL_REQUEST_TEMPLATE.md CODEOWNERS)
├─ pyproject.toml  uv.lock  pnpm-workspace.yaml
├─ README.md CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md CHANGELOG.md LICENSE
```

(Directory ideas for `test/`, `golden/`, `anchor-twins/`, `benchmarks/` mirror Typesol's layout **[VERIFIED]**.)

### 16.2 Coding standards

| Area | Standard |
|---|---|
| Python | PEP 8 via ruff-format; full type hints; mypy `--strict` on `compiler/`, `cli/`, `client/`; no `Any` in public API; docstrings (Google style) on public symbols |
| C runtime | C11 subset, `static inline`, no libc dependency, `-Wall -Wextra -Werror`; every helper returns `uint64_t` status; byte-wise loops forbidden where word-wise helpers exist [mirrors Typesol rules **VERIFIED**] |
| Emitter invariants | Document in `docs/architecture.md`: JS/Python evaluation order preserved via temporaries; references alias account data; every buffer write after a variable-size piece is bounds-checked; runtime messages carry source location; bounded heap |
| Web | TypeScript strict, ESLint, Prettier, a11y lint (jsx-a11y), no `any` |
| Commits/PRs | Conventional Commits; PR template with checklist (tests, docs, changelog, golden diff reviewed); 1 maintainer review (2 for `runtime/` and `emit/`) |
| Errors/diagnostics | Stable codes `PS####`; each code has a docs page and a negative test; changing a code is a breaking change |
| Changelog | Keep a Changelog; "Breaking" section mandatory pre-1.0 |
| Refactor safety | `scripts/codegen_snapshot.py`: generated C + IDL for all examples/fixtures byte-compared before/after (inspired by Typesol **[VERIFIED]**) |

---

## 17. Performance Targets and Scalability

| Area | Target [ASSUMPTION] | How |
|---|---|---|
| `pysol check` (500 LOC) | ≤ 1 s | Single-pass checks; no clang |
| `pysol build` counter | ≤ 10 s cold / ≤ 3 s warm | Build cache; per-function sections, `--gc-sections`, `--strip-all` (as Typesol **[VERIFIED]**) |
| Program size | counter ≤ 20 KB; vault ≤ 30 KB; escrow ≤ 40 KB at v1.0 | Header-only runtime; dead-code elimination; CI size gate |
| CU | within 120% of Anchor-twin CU worst case at MVP; goal ≤ Anchor at v1.0 | Benchmarks in CI; report in docs |
| Playground check latency | ≤ 500 ms after pause (warm Pyodide) | Worker, debounce, incremental re-check |
| Pyodide cold start | ≤ 6 s on broadband, cached afterward | CDN, compressed wheel, prefetch on hover |
| Compile service | p95 ≤ 15 s; sustained 20 compiles/s with 40 workers at ~2 s each [ASSUMPTION] | Warm sandbox pool, cache by content hash, queue |
| Cache hit target | ≥ 60% (examples dominate traffic) | Content-addressed artifacts |
| Docs | LCP ≤ 2.5 s mobile; ≤ 150 KB JS on content pages | Static HTML, islands only for interactive parts |
| Scaling | Stateless API; horizontal worker autoscale on queue depth; artifacts on CDN; snippet reads cached | — |
| Cost control | Idle workers scale to zero; budget alarms; per-IP and global caps | — |

---

## 18. Phase-by-Phase Implementation Plan (for an AI Coding Agent)

General rules for the agent for **every** phase:
1. Work on a branch; keep commits small; run `ruff`, `mypy`, `pytest` before each commit.
2. Never mark a phase done until every acceptance check passes **and** is automated in CI.
3. When an [ASSUMPTION] is touched (e.g., LiteSVM bindings API, solders API), first write a short spike test proving it; record the outcome in `docs/decisions/ADR-xxxx.md`.
4. Never execute user program code in compiler paths; never add network access to the sandbox; never add key-handling to servers.
5. Update docs and CHANGELOG in the same PR as the feature.

### Phase 0 — Foundations and decisions
**Deliverables:** monorepo skeleton (§16), `pyproject.toml`, ruff/mypy config, GitHub Actions `lint` + `unit`, LICENSE, CONTRIBUTING/CODE_OF_CONDUCT/SECURITY, ADRs for: name, license, DSL syntax (OQ-1), Python-based compiler (OQ-2), Starlight choice.
**Acceptance:** `pip install -e .` works on 3.11–3.13; `pytest` runs (empty suite passes); CI green on Linux/macOS; ADRs merged.

### Phase 1 — Toolchain spike and `doctor`
**Deliverables:** `toolchain.py` locating Agave platform-tools (`PYSOL_SBF_SDK`, default install path, `cargo-build-sbf` on PATH); hand-written C hello-world compiled to `.so` by clang/lld with SBF flags; LiteSVM spike (load `.so`, send tx); `pysol doctor`.
**Acceptance:** CI job compiles a trivial C program to `.so` and executes it in LiteSVM, returning success; `pysol doctor` prints ✓/✗ lines and fix commands; documented fallback if LiteSVM bindings differ.

### Phase 2 — Front-end: parse, subset check, type check
**Deliverables:** `parse/resolve/subset/typecheck/diagnostics`; SDK surface (`pysol/__init__.py`, `.pyi`) with types `u8…u128, i8…i128, bool, Pubkey, Signer, Mut, Init, Account, SystemProgram, require, @instruction, @account, @error`; `pysol check` with `--json`; diagnostics codes `PS1xxx/PS2xxx`.
**Acceptance:** counter program checks OK; ≥ 40 negative fixtures each yield the expected code and file:line:col; mypy `--strict` and pyright accept the counter against shipped stubs; fuzz test (random ASTs) never crashes the checker with an uncaught exception.

### Phase 3 — ProgramModel, IDL, runtime header, C emitter (counter-level)
**Deliverables:** `model.py`; `idl.py` + JSON Schema; `runtime/pysol_rt.h` (entry point, deserialize, signer/mut/owner/discriminator checks, checked u64 math, Borsh read/write, error/log with source location); emitter supporting counter (init with PDA via System CPI, require, checked add); golden C/IDL tests; `pysol emit-c`, `pysol build` producing `.so`, IDL, manifest.
**Acceptance:** counter builds; runs in LiteSVM: initialize then increment(5) gives count 5; unauthorized increment fails with code 6000 and log containing `(counter.py:LINE)`; overflow test aborts; IDL validates and loads in Anchor TS client in an optional CI job; two consecutive builds yield identical sha256.

### Phase 4 — Language breadth
**Deliverables:** all integer widths incl. `u128/i128`, casts, floor-div/mod semantics, enums (unit + data), `Option`, `FixedArray`, `FixedString`, `Vec`, nested structs, control flow (`if/for range/while/match`), helper functions, multi-file projects; constraints `Seeds/HasOne/CloseTo/Address/Owner`; aliasing refusal; events; errors; System/SPL Token/Token-2022/ATA CPIs; `vault` and `escrow` programs.
**Acceptance:** per-feature execution tests in LiteSVM; arithmetic property tests per width vs Python `int` (≥ 10k cases/width, 0 divergences); vault/escrow differential tests vs Anchor twins identical in outcome, state, and balances; every rejected construct has a negative test; conformance tests (CPython `refrt` vs SVM) for all examples.

### Phase 5 — Client generation and testing plugin
**Deliverables:** `client/gen.py` + helpers; `pysol-testing` pytest plugin (fixtures, name-based accounts, `expect_error`, logs/CU); `pysol test`; build cache.
**Acceptance:** generated client for counter/vault/escrow passes round-trip tests; template tests use only plugin helpers (no byte packing); second `pysol test` run skips clang (cache hit asserted); client module imports without importing `pysol.compiler`.

### Phase 6 — CLI completion, wallet/faucet, deploy, templates
**Deliverables:** `init` with 3 templates, `deploy` (via `solana program deploy` first; own loader client later), `faucet`, `wallet`, `idl build`, `client`, config parsing, `--json` everywhere, exit codes; localnet mode for tests; smoke script.
**Acceptance:** from empty directory in clean container: `pip install` → `pysol init` → `pytest` → `pysol build` passes; `localnet-smoke` job deploys and drives all templates through generated client; deploy refuses mainnet without explicit flag; wallet files have mode 0600 (tested); every command has help text and tests for exit codes 0/1/2.

### Phase 7 — Docs site (MVP)
**Deliverables:** Starlight site with theme system (§11), tokens pipeline, copy buttons, Pagefind search, example extraction/testing in CI, page inventory (PRD §5.3) for MVP, API reference generation, "Edit on GitHub", version stamp, CHANGELOG/roadmap pages.
**Acceptance:** Lighthouse a11y ≥ 95 and axe 0 violations in both themes; theme persists across reload/navigation with no flash (Playwright test); breaking a `test` code block fails CI; search finds `PS2104` and "PDA"; docs deployed to preview and production.
**Release MVP v0.1 after this phase:** tag, PyPI publish via Trusted Publishing, release notes; run 5 moderated usability sessions and record time-to-first-deploy.

### Phase 8 — Playground (Beta)
**Deliverables:** Pyodide worker running compiler front-end; CodeMirror editor with diagnostics; output tabs (C, IDL, client, logs); compile API + queue + sandbox workers + cache + rate limits (§9); Wallet Standard connect (devnet only); deploy panel; invoke panel; faucet button; examples picker; snippet sharing; observability dashboards.
**Acceptance:** Playwright E2E: load → pick counter → edit with injected error shows diagnostic ≤ 500 ms → fix → compile ≤ 15 s p95 against staging → deploy to localnet using mock wallet → invoke increment → logs show; sandbox tests prove: no network egress, memory/time limits enforced, fork bomb contained; load test with 50 concurrent users meets p95; security tests: no API field accepts secrets, CSP blocks inline script injection in snippet render; a11y checks pass.

### Phase 9 — Community, gallery, migration (Beta)
**Deliverables:** 8 templates and ≥ 20 examples with metadata; gallery and showcase pages; Anchor→PySol migration guide, native Rust guide, escrow case study with differential results; `pysol port`; issue/PR templates; Discord/Discussions linked; public roadmap board; "good first issue" labelling; contributor guide with architecture walkthrough ("add a built-in", "add a constraint", "add an error code" recipes).
**Acceptance:** all gallery entries pass tests weekly in CI; `port` on the Anchor escrow IDL generates a program skeleton that, once completed, passes the differential test; docs guides' code tested; 50 external beta testers onboarded and feedback triaged.

### Phase 10 — Hardening toward v1.0
**Deliverables:** `verify`, `profile`, `idl publish`, `cpi`; Metaplex/oracle bindings (prioritized by demand); VS Code integration (diagnostics via `pysol check --json --files`); benchmarks page and CI size/CU gates; security model + audit package docs; fuzzing campaign; independent review/audit engagement; language spec freeze and semver policy; docs versioning.
**Acceptance:** `verify` exit 0 on a deployed counter and exit 3 after source change (CI against localnet); no open P0/P1 correctness issues; fuzz run ≥ 24 h with no crash/divergence; benchmark regression gate active; audit report published or status clearly documented; v1.0 release checklist complete (changelog "Breaking" reviewed, docs versioned, migration notes).

### Phase 11 — Post-1.0 backlog (not scheduled)
Docs i18n, comprehension syntax support, optional IR/second backend (only if a documented trigger from §4.2 is met), WASM-based in-browser SBF compile (if OQ-3 spike succeeds), Windows-native support.
