# PRD — PySol: A Python Framework for Solana Programs

| Field | Value |
|---|---|
| Working name | **PySol** [ASSUMPTION — name, PyPI package and domain availability must be checked before launch] |
| Document | Product Requirements Document (PRD), companion to `TRD.md` |
| Version / date | 0.1 draft — 30 Oct 2026 |
| License target | MIT or Apache-2.0 (see §6.5) |
| Status | Draft for review |

Conventions: **[VERIFIED]** = observed directly in a fetched source. **[ASSUMPTION]** = not verified; needs confirmation.

---

## 0. Research Summary (Step 1)

### 0.1 Source access log

| Source | Status | Notes |
|---|---|---|
| GitHub repo `typesol/typesol` | **Accessible** | README, file tree, tooling table, benchmark table, status section read. Repo page showed 0 stars, 0 forks, 35 commits, 1 open PR at fetch time. Individual files (`docs/language.md`, `CONTRIBUTING.md`, `SECURITY.md`) were **not** opened. |
| Docs `typesol.com/docs/` | **Accessible** (Introduction, Architecture pages read) | Sidebar structure captured. Other pages (Language, CLI, Client, Security model, Audit, Runtime, Mainnet, Case studies) were listed but **not read**; their content below is inferred from the README and marked. |
| Landing `typesol.com/` | **Accessible** | Hero, animated compile demo, benchmark charts, roadmap, token section read. |
| Playground `typesol.com/play/` | **Partially accessible** | Only HTML metadata was returned (page is client-rendered). Observed: description says users "write a Solana program in TypeScript and see the C, Anchor IDL and TypeScript client TypeSOL generates, compiled in your browser." Editor, layout, deploy flow and examples dropdown were **not observed**. All playground UX details in this PRD are [ASSUMPTION]. |

### 0.2 Key facts extracted

| Area | Finding |
|---|---|
| Positioning | "Write Solana programs in TypeScript. Ship native SBF." Compiles a TypeScript **subset** straight to Solana bytecode. **[VERIFIED]** |
| Architecture | `.ts` → `tsc` typecheck → subset check → lower to **C** + header-only runtime `typesol_rt.h` → Agave platform-tools `clang -target sbf` + `ld.lld` → `.so`. No interpreter/VM on chain, **no Rust generated**. Also emits Anchor-compatible IDL (spec 0.1.0), generated C, build manifest (sha256 of sources and binary). **[VERIFIED]** |
| Language subset | Rejects floats, classes, closures, `any`, foreign imports with `file:line:col` diagnostics ("nothing is half-supported"). Types: `u8…u128`, `i8…i128`, `boolean`, `Pubkey`, structs, enums, `Option`, `Vec`, `FixedArray`, `FixedString`. Account wrappers: `Signer`, `Account<T>`, `Mut<T>`, `Init<T>`, `InitIfNeeded<T>`, `Zeroed<T>`; constraints `HasOne`, `Seeds`, `CloseTo`, `Ata`, `Address`, `Owner`, `Executable`. **[VERIFIED]** |
| Safety defaults | Checked arithmetic everywhere; owner/discriminator/signer/writability/aliasing checks generated from parameter types; Anchor error codes reused. Runtime errors map back to source lines (`Error 6000 Unauthorized (counter.ts:21)`). **[VERIFIED]** |
| CPI / ecosystem | System, SPL Token, Token-2022, ATA, Metaplex Token Metadata/Core/Bubblegum, generic `invoke`, events (`emit`, `emitCpi`), hashes, signature checks, Pyth/Switchboard. **[VERIFIED]** |
| CLI | `init` (templates: counter, vault, escrow), `build`, `check`, `deploy` (`--dry-run`), `doctor`, `idl publish`, `cpi`, `client`, `port` (Anchor IDL → skeleton), `verify`, `profile` (CU per source line), `emit-c`. Exit codes 0/1/2/3. **[VERIFIED]** from README/architecture; flags beyond those shown are unknown. |
| Testing DX | Tests in the same language via `typesol/testing` on **LiteSVM** (in-process runtime). Differential tests against Anchor "twins"; fuzz tests vs BigInt/TS model; golden C tests; localnet smoke test. **[VERIFIED]** |
| Docs structure | Sidebar groups: *Start* (Introduction, Migrate from Anchor, three case studies, Test your program, Deploy to mainnet), *Reference* (Language, CLI, TypeScript client, Error codes, Troubleshooting), *Project* (Testing, Architecture, Security model, Audit package, C runtime, Changelog). "Edit this page on GitHub", on-page TOC, Prev/Next, version + commit stamp in footer. **[VERIFIED]** |
| Landing UX | Dark-first (`theme-color #07080c`), animated compile walkthrough (TS ↔ generated C, 6 annotated steps), interactive benchmark charts, "Built in public" milestone list (Compiler on npm, Client SDK, Playground, Verified builds = released; AI-native, Audit & 1.0 = planned). **[VERIFIED]** A light theme was **not observed**. |
| Community | MIT license, CONTRIBUTING.md, SECURITY.md, CHANGELOG.md, `/report` page, X account, issue/PR tabs. No Discord/forum link observed. The landing page also promotes a **project token ($TS)**. **[VERIFIED]** |
| Limitations | Pre-1.0; **not independently audited** (project warns not to put significant value behind programs); macOS/Linux only (Windows via WSL2); requires Agave CLI/platform-tools; "Not supported yet" list exists in `docs/language.md` (not read). **[VERIFIED]** |
| Data inconsistencies | Version strings disagree across pages (README badge `0.10.0-rc`, README text `0.11`, docs footers `v0.31.0` / `v0.32.0`), suggesting very fast release cadence or stale text. Performance claims (5–46% of Anchor CU, ~10× smaller binaries) are **project-reported benchmarks**, not independently verified by us. |

### 0.3 Implication for PySol

Typesol's strongest idea is **"typed subset → C → LLVM/SBF, with Anchor-compatible IDL"**: it removes Rust from the developer's machine and gives small, cheap programs. PySol adopts the same architecture for Python (rationale in TRD §4) rather than the earlier Poseidon-style "transpile to Anchor Rust" approach. The Python-specific challenge is that Python is dynamically typed with unbounded integers; PySol therefore requires full type annotations and defines integer semantics explicitly.

---

## 1. Executive Summary and Product Vision

**Product.** PySol is an open-source framework that lets Python developers write, test, deploy and call Solana programs in a statically-typed **subset of Python**, compiled ahead of time to native Solana SBF bytecode, with Anchor-compatible IDLs and generated Python clients.

**Vision.** *A Python developer ships their first Solana program to devnet in under 15 minutes, without installing Rust.*

**Product pillars**

1. **Familiar** — real Python syntax; editors, linters (mypy/pyright/ruff) and pytest work.
2. **Safe by default** — checked arithmetic and generated account checks from types.
3. **Interoperable** — Anchor-compatible IDL; programs are indistinguishable on-chain from Anchor/native programs.
4. **Learnable** — playground, tutorials, Anchor/Rust migration guides, templates.
5. **Open and honest** — MIT/Apache, public roadmap, clearly stated limitations and audit status.

**Deliverables**: Python package + CLI (`pysol`), compiler, runtime header, generated Python client, local test harness, browser playground, docs site, template/example gallery, community infrastructure.

---

## 2. Problem Statement

Python is among the most-used languages in the world and dominates data science, ML, scripting and education. Solana programs, however, are written almost exclusively in Rust. For Python developers this means:

| # | Pain point | Effect |
|---|---|---|
| P1 | Two new things at once: Rust (ownership, lifetimes, macros) and Solana's account model. | Learners cannot separate "is my Solana logic wrong or is my Rust wrong?" |
| P2 | Heavy toolchain: Rust, Cargo, Solana CLI, Anchor, Node for tests. | Long, failure-prone setup; first deploy takes hours. |
| P3 | Anchor's macro-heavy DSL hides what runs on-chain. | Opaque errors; steep learning curve. |
| P4 | Client and test code in TypeScript while programs are in Rust. | Three languages for a first app. |
| P5 | Python Solana libraries (solders, solana-py) cover **clients only**, not on-chain code. | Python devs can send transactions but cannot author programs. |
| P6 | No interactive environment to experiment. | Slow feedback; weak for teaching. |

Prior art: Poseidon (TypeScript → Anchor Rust transpiler, Turbin3) and Typesol (TypeScript subset → C → SBF) show demand for non-Rust authoring. **No equivalent exists for Python** [ASSUMPTION — a short landscape scan must be repeated before launch].

---

## 3. Target Users and Personas

| Persona | Profile | Needs | Success looks like |
|---|---|---|---|
| **P1 Priya — Python backend/web dev** | 3–8 yrs Django/FastAPI; curious about Web3 | Familiar syntax, pip install, clear errors | Deploys a counter + calls it from a FastAPI service same day |
| **P2 Ben — Blockchain beginner** | Student/bootcamp; knows basic Python, no Rust | Guided tutorials, playground, no install | Completes tutorial 1 in browser, then installs locally |
| **P3 Dana — Data/ML engineer entering Web3** | Pandas/PyTorch; wants on-chain attestation, oracles, payouts | Typed accounts, oracle (Pyth) bindings, scripting-friendly client | Writes a payout/attestation program and automates it from a notebook |
| **P4 Prof. Lee — Educator** | Teaches blockchain course | Reproducible templates, zero-setup playground, shareable links, autograding via pytest | Runs a 40-student workshop with one URL |
| **P5 Sam — Solana/Rust developer (secondary)** | Experienced Anchor dev | Fast prototyping, migration guide, `verify`, CU profiling | Uses PySol for prototypes; contributes compiler features |

---

## 4. Goals, Non-Goals and Success Metrics

### 4.1 Goals

| ID | Goal |
|---|---|
| G1 | Reduce time from zero to first devnet deploy for a Python dev to ≤ 15 min locally and ≤ 5 min in the playground. |
| G2 | Produce programs whose on-chain behavior is equivalent to Anchor equivalents (same IDL, account layout, error codes). |
| G3 | Make unsafe patterns hard to write (checked math, generated account validation). |
| G4 | Offer a complete learning path (docs, tutorials, playground, templates). |
| G5 | Build a healthy open-source community. |

### 4.2 Non-Goals

| ID | Non-goal | Reason |
|---|---|---|
| NG1 | Running a Python interpreter/VM on-chain | Cost, size, determinism. |
| NG2 | Supporting full Python (floats, `eval`, dynamic typing, arbitrary imports, classes with inheritance, exceptions) | Not representable in deterministic SBF. Unsupported constructs are rejected, never half-supported. |
| NG3 | Replacing Rust/Anchor for audited, high-value production programs at v1.0 | No independent audit by then (see risk R1). |
| NG4 | Issuing or promoting a project token | Out of scope; avoids financial/regulatory complexity [ASSUMPTION — product decision]. |
| NG5 | Hosting or custodying user keys or funds | Security principle. |
| NG6 | Mainnet-beta deployment from the playground | Devnet only in playground; mainnet via local CLI. |
| NG7 | Non-Solana chains | Focus. |

### 4.3 Success metrics (KPIs)

All targets are [ASSUMPTION] and are for the first 6 months after beta unless stated.

| KPI | Definition | Target |
|---|---|---|
| Time-to-first-deploy (local) | Median time from `pip install` to confirmed devnet deploy, measured in moderated usability tests (n ≥ 10) | ≤ 15 min |
| Time-to-first-deploy (playground) | Page load → devnet deploy confirmed | ≤ 5 min |
| Docs engagement | Median session ≥ 3 pages; Getting Started completion (reached "Deploy" page) | ≥ 40% |
| Docs search success | Search sessions followed by a click within 30 s | ≥ 70% |
| Playground usage | Weekly active sessions; % of sessions that compile; % that deploy | 1,000 WAS; 70% compile; 15% deploy |
| Package adoption | PyPI downloads (non-mirror) / month | 5,000 by v1.0 |
| GitHub stars | Public count | 1,000 by v1.0 |
| Contributors | Unique non-maintainer contributors with merged PR | ≥ 25 by v1.0 |
| Issue health | Median time to first maintainer response | ≤ 48 h |
| Correctness | Differential tests vs. Anchor twins passing; open P0 correctness bugs | 100% pass; 0 |
| Templates/examples | Count of tested templates + examples | ≥ 8 templates, ≥ 20 examples by v1.0 |

Analytics must be privacy-preserving and opt-out (see NFR-SEC-4).

---

## 5. Core Features (MoSCoW)

### 5.1 Prioritization overview

| ID | Feature | MoSCoW | Milestone |
|---|---|---|---|
| F-01 | Typed Python DSL/SDK for programs (accounts, instructions, errors, events) | **Must** | MVP |
| F-02 | Compiler: Python subset → SBF `.so` + diagnostics | **Must** | MVP |
| F-03 | IDL generation (Anchor-compatible) | **Must** | MVP |
| F-04 | CLI: `init`, `check`, `build`, `test`, `deploy`, `doctor` | **Must** | MVP |
| F-05 | Local test environment (in-process SVM) + pytest helpers | **Must** | MVP |
| F-06 | Python client generation | **Must** | MVP |
| F-07 | Docs site: getting started, API reference, search, copy buttons | **Must** | MVP |
| F-08 | Light and dark themes (incl. Python-inspired light theme) | **Must** | MVP (docs), Beta (playground) |
| F-09 | Browser playground (edit, compile, deploy to devnet, run tx, logs) | **Should** | Beta |
| F-10 | Wallet integration + devnet faucet helpers | **Should** | Beta (playground), MVP (CLI faucet) |
| F-11 | Mock validator / localnet support (`solana-test-validator`) | **Should** | Beta |
| F-12 | Templates library + `init --template` | **Should** | MVP (3), Beta (8) |
| F-13 | Example gallery + showcase page | **Should** | Beta |
| F-14 | Migration guides from Rust/Anchor + `port` command | **Should** | Beta |
| F-15 | Community: CONTRIBUTING, issue templates, Discord/forum, changelog, roadmap | **Should** | MVP (files), Beta (chat) |
| F-16 | `verify` (reproducible builds) and `profile` (CU per line) | **Could** | v1.0 |
| F-17 | `idl publish`, `cpi` (typed CPI from IDL) | **Could** | Beta/v1.0 |
| F-18 | Shared-snippet links in playground | **Could** | Beta |
| F-19 | i18n of docs (translations) | **Could** | Post-1.0 (readiness in MVP) |
| F-20 | VS Code extension / language server plugin | **Could** | v1.0 |
| F-21 | Python subset runtime on-chain / interpreters | **Won't** | — |
| F-22 | Mainnet deploy from playground | **Won't** | — |
| F-23 | Custom project token | **Won't** | — |
| F-24 | Hosted key custody / server-side signing | **Won't** | — |

### 5.2 Feature specifications

#### F-01 Typed Python authoring DSL/SDK — Must

Programs are `.py` files importing from `pysol`. Types come from annotations; the module `pysol` ships `.pyi`/`py.typed` so standard type checkers work.

Illustrative target syntax [ASSUMPTION — final syntax is an open question, §8.3]:

```python
from pysol import (Account, Init, Mut, Pubkey, Signer, SystemProgram,
                   u8, u64, instruction, account, error, require)

@account
class Counter:
    authority: Pubkey
    count: u64
    bump: u8

@error
class CounterError:
    UNAUTHORIZED = "Only the counter's authority can change it"

@instruction
def initialize(authority: Mut[Signer], counter: Init[Counter],
               system_program: SystemProgram) -> None:
    counter.bump = counter.create(authority, ["counter", authority.key])
    counter.authority = authority.key
    counter.count = 0

@instruction
def increment(authority: Signer, counter: Mut[Counter], by: u64) -> None:
    require(counter.authority == authority.key, CounterError.UNAUTHORIZED)
    counter.count += by   # overflow-checked
```

**User stories & acceptance criteria**

| ID | Story | Acceptance criteria |
|---|---|---|
| F-01-a | As Priya, I define account structs with typed fields. | Fixed-width ints (`u8…u128`, `i8…i128`), `bool`, `Pubkey`, nested structs, fixed arrays/strings, `Option`, enums are supported; unsupported types yield `file:line:col` diagnostics. |
| F-01-b | I declare instruction accounts via type wrappers. | `Signer`, `Mut[T]`, `Init[T]`, `Account[T]`, program/sysvar types supported; constraints (`Seeds`, `HasOne`, `CloseTo`, `Address`, `Owner`) emit checks before body runs and appear in IDL. |
| F-01-c | I get overflow safety without thinking about it. | All arithmetic on typed ints is checked; overflow aborts the instruction with a documented error; tests prove behavior at every width. |
| F-01-d | My editor and mypy/pyright understand my program. | `pysol` ships type stubs; sample project type-checks clean with mypy `--strict` and pyright. |
| F-01-e | I can't accidentally use Python features that don't compile. | Floats, `try/except`, classes beyond declared account/enum types, `*args`, dynamic imports, `eval/exec`, recursion beyond limit are rejected with an explanatory error and docs link. |

#### F-02 Compiler — Must

| Story | Acceptance criteria |
|---|---|
| Developer builds a program into an SBF `.so`. | `pysol build` on each shipped template produces a `.so` that loads and executes in the local SVM; build is deterministic (identical sha256 on repeat builds with same toolchain). |
| Developer maps runtime errors to source. | Failing instruction logs contain `(file.py:line)`. |
| Developer needs no Rust. | Documented path requires only Python 3.11+ and Solana platform-tools; CI proves a clean Linux/macOS container without `rustc` builds the counter. |

#### F-03 IDL generation — Must

Emits Anchor-compatible IDL JSON (spec version pinned in docs). Acceptance: IDL of the counter template is accepted unchanged by the Anchor TypeScript client and by PySol's own Python client generator; schema-validated in CI.

#### F-04 CLI — Must

Commands and flags are specified in TRD §7. Acceptance: every command has `--help`, strict option parsing, documented exit codes, `--json` for machine output; `pysol doctor` identifies missing Python version, platform-tools, Solana CLI, keypair, RPC and prints the fix command.

#### F-05 Local testing environment — Must

Developer runs `pytest` (or `pysol test`) to build and execute instructions in an in-process SVM with account helpers addressed by name. Acceptance: template tests pass offline; one test executes in < 2 s excluding first build [ASSUMPTION]; failing tests show program logs and source line.

#### F-06 Python client generation — Must

`pysol build` writes a typed Python client (`<name>_client.py`) from the IDL: instruction builders, account decoders, PDA helpers, error enums. Acceptance: round-trip test (client builds tx → local SVM executes → client decodes account) passes for all templates.

#### F-07 Documentation site — Must

| Requirement | Acceptance |
|---|---|
| Structure: Start (Introduction, Quickstart, Tutorials, Migrate from Rust/Anchor), Reference (Language, CLI, Python API, Client, Errors), Project (Architecture, Security model, Testing, Changelog, Roadmap) | All sections present at MVP except those marked Beta. |
| Code snippets with copy button | Every `<pre>` has a keyboard-accessible copy button and announces "Copied" to screen readers. |
| Search across docs | Full-text, client-side index; results < 200 ms for p95 on desktop [ASSUMPTION]; keyboard shortcut `/`. |
| Examples tested | Every code block tagged `test` is compiled in CI; a broken example fails the build. |
| Edit on GitHub, prev/next, TOC, version stamp | Present on each page. |

#### F-08 Themes — Must

| Requirement | Acceptance |
|---|---|
| Light and dark modes, plus "system" | Toggle in header; choice persists across reloads and across docs/playground; no flash of wrong theme on load. |
| **Python-inspired light theme** (default light) | Palette derived from Python blue (`#3776AB`/`#306998`) and Python yellow (`#FFD43B`) on neutral surfaces. Blue is used for primary actions/links; yellow only as accent/highlight/selection (never for body text on white). Meets WCAG 2.1 AA contrast (4.5:1 text, 3:1 UI). |
| Dark theme | Near-black surface (Typesol uses `#07080c` for theme-color [VERIFIED]; PySol uses its own token set) with the same accents adjusted for contrast. |
| Code highlighting | Both themes have syntax themes that pass AA contrast. |

Token specification: TRD §11.

#### F-09 Browser playground — Should

| ID | Story | Acceptance criteria |
|---|---|---|
| F-09-a | Ben edits PySol code in the browser with highlighting, inline diagnostics and examples picker. | Editor loads < 3 s on broadband [ASSUMPTION]; diagnostics appear ≤ 500 ms after typing stops; examples dropdown lists all gallery examples. |
| F-09-b | He sees what is generated. | Tabs for Generated C, IDL, Python client, Build log, Program logs. |
| F-09-c | He compiles to a real `.so`. | Compile of the counter ≤ 15 s p95 [ASSUMPTION]; errors map to editor lines. |
| F-09-d | He deploys to devnet with his own wallet. | Deploy only via wallet signature in browser; server never receives keys; shows program ID, signatures, explorer links, and cost estimate before signing. |
| F-09-e | He invokes instructions and sees logs. | Form generated from IDL for args/accounts; result displays logs, compute units, and decoded account state. |
| F-09-f | He shares a link. (Could) | Immutable snippet URL; opens with code + selected example. |

Playground is a *teaching and prototyping* environment; the UI states that deployed programs are unaudited.

#### F-10 Wallet and faucet helpers — Should

Wallet Standard connection (Phantom, Solflare, Backpack etc. [ASSUMPTION]) in playground; `pysol faucet` and `pysol wallet new|address|balance` for CLI. Acceptance: faucet helper retries with backoff and falls back to printing the web-faucet URL on rate-limit; keypairs written with `0600` permissions; never printed unless `--show-secret`.

#### F-11 Mock validator / localnet — Should

`pysol test --localnet` starts/uses `solana-test-validator`, deploys, and runs pytest against RPC. Acceptance: smoke test drives every example end to end in CI.

#### F-12 Templates library — Should

`pysol init my-app --template <name>`. MVP: `counter`, `vault`, `escrow`. Beta adds `token-mint`, `voting`, `nft-mint`, `oracle-reader`, `multisig`. Acceptance: each template has a passing test and a README; CI builds all weekly against latest platform-tools.

#### F-13 Example gallery + showcase page — Should

Searchable gallery (tag, difficulty, concepts). Showcase page lists community projects submitted via PR to a `showcase.yml`. Acceptance: gallery entries link to playground with code preloaded; showcase submissions require build-passing link to repo.

#### F-14 Migration guides — Should

Guides: "Anchor → PySol" (construct mapping table), "Native Rust → PySol", and a case study porting Anchor's escrow. `pysol port <idl.json>` creates a skeleton. Acceptance: each guide's code tested in CI; case study shows differential test outcome vs Anchor binary.

#### F-15 Community features — Should

| Item | Acceptance |
|---|---|
| CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md | Present at repo root before first public release. |
| Issue/PR templates (bug, feature, docs, security redirect) | In `.github/`. |
| Discord and/or GitHub Discussions | Linked in docs footer and README [ASSUMPTION — channel choice open]. |
| Changelog | Keep-a-Changelog format, linked from docs; release notes auto-assembled. |
| Public roadmap | Docs page + GitHub Project board; milestones mirror §7. |
| Showcase | See F-13. |

#### F-16–F-20 Could-haves (summary)

| ID | Acceptance (summary) |
|---|---|
| F-16 | `verify` rebuilds and compares to deployed ELF (exit 3 on mismatch); `profile` reports CU per Python line from `--profile` build logs. |
| F-17 | `idl publish` writes IDL on-chain via Program Metadata program [ASSUMPTION: same mechanism as Typesol]; `cpi` generates typed helpers from any Anchor IDL. |
| F-18 | Shared snippets immutable, content-addressed, 90-day retention for unviewed snippets [ASSUMPTION]. |
| F-19 | All docs strings externalized; one non-English locale proof-of-concept builds. |
| F-20 | Language-server diagnostics from `pysol check` surfaced in VS Code. |

### 5.3 Docs-site "page inventory" (MVP)

Introduction · Quickstart (local) · Quickstart (playground) · Tutorial 1: Counter · Tutorial 2: Vault (SOL) · Tutorial 3: Escrow (SPL tokens) · Concepts: Solana accounts for Python devs · Language reference · Python API reference (auto-generated) · CLI reference · Client reference · Error codes · Troubleshooting · Migrate from Anchor · Security model · Architecture · Testing · Changelog · Roadmap · Contributing.

---

## 6. Non-Functional Requirements

### 6.1 Performance

| ID | Requirement |
|---|---|
| NFR-PERF-1 | `pysol check` on a 500-line program ≤ 1 s; `pysol build` of the counter ≤ 10 s cold, ≤ 3 s warm [ASSUMPTION]. |
| NFR-PERF-2 | Docs pages: LCP ≤ 2.5 s on a mid-tier mobile profile; JS ≤ 150 KB gzip on non-playground pages. |
| NFR-PERF-3 | Playground compile service p95 ≤ 15 s; queue wait p95 ≤ 5 s under nominal load. |
| NFR-PERF-4 | Generated programs: CU and binary size tracked in CI benchmark vs Anchor twins; regression > 5% blocks release. |

### 6.2 Accessibility (WCAG 2.1 AA)

| ID | Requirement |
|---|---|
| NFR-A11Y-1 | All docs and playground UI meet WCAG 2.1 AA; automated axe checks in CI plus a manual keyboard/screen-reader pass per release. |
| NFR-A11Y-2 | Both themes meet 4.5:1 text and 3:1 non-text contrast; focus indicators visible; respects `prefers-reduced-motion` and `prefers-color-scheme`. |
| NFR-A11Y-3 | Editor is keyboard-operable with an escape from focus trap; diagnostics exposed via ARIA live region; all buttons labelled. |
| NFR-A11Y-4 | No information conveyed by color alone (e.g., diagnostics have icons + text). |

### 6.3 Internationalization readiness

UTF-8 throughout; docs strings and UI strings externalized; locale-aware routing (`/en/…`) reserved from day one; right-to-left layout not blocked by CSS (logical properties); diagnostics use message IDs with English text so they can be translated later; no concatenated sentences.

### 6.4 Security

| ID | Requirement |
|---|---|
| NFR-SEC-1 | **Private keys are never sent to or stored on any PySol server.** Playground signs only via the user's wallet; CLI keypairs stay on disk. |
| NFR-SEC-2 | User code is never executed on servers; it is parsed and compiled in a network-less sandbox with resource limits. |
| NFR-SEC-3 | Releases published through PyPI Trusted Publishing with SBOM and provenance attestations; dependencies audited in CI. |
| NFR-SEC-4 | Telemetry is opt-in for the CLI and cookie-less/aggregate for the web; no source code leaves the browser except to the compile service explicitly invoked by the user. |
| NFR-SEC-5 | Clear, visible statement of audit status on README, docs home and playground until an independent audit is published. |

### 6.5 Licensing

[ASSUMPTION] **Apache-2.0** for compiler/CLI/runtime (explicit patent grant helps with the generated-code runtime header), **CC BY 4.0** for docs text, MIT for templates/examples so users can relicense generated projects freely. Typesol uses MIT [VERIFIED]; MIT-only is an acceptable alternative (open question OQ-6). Runtime header redistributed inside user binaries must carry a permissive license. Third-party binaries used in tests (e.g., Metaplex programs) are fetched, not redistributed.

### 6.6 Compatibility

Python 3.11, 3.12, 3.13 on Linux (x86-64, arm64) and macOS (arm64, x86-64); Windows via WSL2 [ASSUMPTION — mirrors Typesol's stated support]. Solana: Agave stable platform-tools, tested against two latest minor releases.

---

## 7. Release Plan

| Milestone | Target [ASSUMPTION] | Scope | Exit criteria |
|---|---|---|---|
| **M0 — Foundation** | Month 0–1 | Repo, CI, license, name check, language spec draft, docs skeleton | Spec reviewed by ≥ 3 external reviewers; counter compiles to C. |
| **MVP (v0.1)** | Month 3 | F-01…F-08 (core), 3 templates, CLI faucet, basic docs, `pip install` | Time-to-first-deploy ≤ 15 min in 5 usability sessions; counter/vault/escrow differential tests vs Anchor pass; docs site live. |
| **Beta (v0.5)** | Month 6 | Playground, wallet, localnet, 8 templates, example gallery, migration guide + `port`, community channels, public roadmap | 50 external beta users; WCAG automated checks pass; playground abuse/rate-limit tests pass; no P0 bugs open. |
| **v1.0 RC** | Month 9–10 | `verify`, `profile`, `idl publish`, `cpi`, VS Code integration, hardened security docs, benchmark page | Independent security review commissioned; language spec frozen under semver. |
| **v1.0** | Month 12 | Stable language/CLI/IDL, versioned docs, long-term support policy | Independent audit **report published** (or clearly documented as pending with scope); 25+ contributors; KPI targets reviewed. |

Versioning: SemVer; pre-1.0 minor bumps may break, always listed under "Breaking" in the changelog. Docs versioned per minor.

---

## 8. Risks, Dependencies and Open Questions

### 8.1 Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Compiler bug produces incorrect/unsafe on-chain code | Med | **Critical** | Differential testing vs Anchor/native twins, fuzzing, golden tests, generated-code readability, `emit-c`, external audit before 1.0, prominent warnings. |
| R2 | Python semantics mismatch (unbounded ints, `//` vs `/`, truthiness, mutable aliasing) confuses users or causes bugs | High | High | Explicit spec; mandatory annotations; reject ambiguous constructs; conformance tests running the program both in CPython (with `pysol` reference runtime) and on SVM. |
| R3 | Dependence on Agave platform-tools (clang/lld) packaging and licensing changes | Med | High | Pin hashes; `doctor` command; document alternative LLVM; keep backend interface abstract. |
| R4 | Playground abuse (compile-bomb, crypto-mining, spam deploys) | High | Med | Sandboxing, limits, rate limiting, no network, queue, abuse monitoring. |
| R5 | Wallet/phishing risk via playground shared snippets | Med | High | Immutable snippets; unaudited-code banner; transaction preview; never auto-sign; CSP; no remote code in snippets. |
| R6 | Scope too large for small team | High | Med | Strict MoSCoW; MVP excludes playground. |
| R7 | Solana ecosystem changes (SBF versions, Token-2022, loader v4) | Med | Med | Version matrix in CI; adopt features behind flags. |
| R8 | Community fragmentation / low contributor traction | Med | Med | Good-first-issues, architecture doc, mentorship, public roadmap. |
| R9 | Trademark/name collision | Med | Low | Name search before public announcement. |
| R10 | Perceived hype due to token associations seen in similar projects | Low | Med | Explicit non-goal NG4; communications policy. |

### 8.2 Dependencies

| Dependency | Use | Risk note |
|---|---|---|
| Solana/Agave platform-tools (clang, lld) | SBF code generation | External release cadence |
| solders / solana-py [ASSUMPTION] | Python client/tx building | Maintenance status to verify |
| LiteSVM Python bindings [ASSUMPTION: package `litesvm` exists on PyPI — verify] | In-process testing | API stability |
| Pyodide [ASSUMPTION] | In-browser analysis/codegen | WASM size, startup time |
| Anchor IDL spec | Interoperability | Spec changes between Anchor versions |
| Wallet Standard | Playground wallets | Wallet-specific bugs |
| Hosting (compile service, CDN, DB) | Playground | Cost; abuse |

### 8.3 Open questions

| ID | Question | Owner / decision needed by |
|---|---|---|
| OQ-1 | Final DSL syntax: decorators + annotated wrappers (`Mut[Signer]`) vs. class-based `Accounts` contexts like Anchor? | Language WG, before M0 exit |
| OQ-2 | Should the compiler itself be written in Python (easier for contributors, runs in Pyodide) — and is Pyodide-hosted analysis fast enough? | Tech lead, M0 |
| OQ-3 | Can the playground compile to `.so` fully in-browser (WASM clang with SBF backend)? Default plan: server-side compile. | Spike, M1 |
| OQ-4 | Which loader (v3 upgradeable vs v4) should be the default deploy path for browser deploy? | Spike, Beta |
| OQ-5 | Discord vs GitHub Discussions vs forum for community. | Community lead, MVP |
| OQ-6 | Apache-2.0 vs MIT. | Maintainers, M0 |
| OQ-7 | Funding/hosting model for playground compute. | Sponsors, Beta |
| OQ-8 | Do we support Windows natively or only WSL2? | Beta |
| OQ-9 | Is an `async`-style or `with`-block pattern needed for CPI signer seeds, or are function calls sufficient? | Language WG |
| OQ-10 | Exact Typesol playground and `docs/language.md` details (unobserved here) should be reviewed manually to align feature parity. | PM, M0 |
