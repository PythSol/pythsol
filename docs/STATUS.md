# Project status

This is the hostable surface. A checked box is in the tree and covered by a test or a local build. An empty box is not done.

The next agent should read **`docs/HANDOFF.md`** (goal, built, left, traps).
A short pointer is `AGENTS.md` at the repo root.

## Working now

- [x] Typed Python subset, checked with `pythsol check`
- [x] Native SBF `.so`, IDL, and solders client from `pythsol build`
- [x] LiteSVM tests for all six examples (counter, ledger, vault, escrow, multisig, poll) and the purse fixture
- [x] Fixed-range list comprehensions (`[x for i in range(4)]` → `FixedArray`)
- [x] `pythsol test`, build cache, wallet, faucet, deploy, port, verify, profile
- [x] Hosted playground, browser check and emit: live at `https://www.pythsol.com/playground`; check and emit are served as serverless Python, compile answers 403 with Docker guidance
- [x] Hosted docs: live under `/docs` of the same project (`https://www.pythsol.com/docs`), Starlight `base: /docs`
- [x] `pythsol.com` and `www.pythsol.com` are live (verified 2026-11-02): domain at NameCheap, DNS on Cloudflare, apex A → `216.198.79.1`, `www` CNAME → `4ef91b6d76096047.vercel-dns-017.com`
- [x] `Vec[T, N]`, fixed-width data enums, PDA lamport moves
- [x] Local playground: check, emit, and compile on loopback
- [x] Public playground: `pythsol serve --public` checks and emits, and does not compile until `--allow-compile`
- [x] Hosted deploy configs: `deploy/Dockerfile` (sha256-pinned platform-tools), Fly.io and Render blueprints, guide `docs/guides/hosting.md`
- [x] Playground layout follows the TypeSol split (source, then compiler output) in a light Python and Solana palette. See `docs/comparison-typesol.md`
- [x] Docs site builds with `npm run build` in `web/docs` (static files in `dist/`)
- [x] Windows is a supported developer machine for the compiler and LiteSVM

## Build queue

The order the project is being completed in. Tick only with a command, a
test, or a live URL. Details and blockers live in `docs/HANDOFF.md`.

1. **PyPI release** — packaging is verified end to end; upload is the only
   step left and needs the PyPI API token. Steps: `docs/guides/release.md`.
   - [x] `python -m build` produces sdist + wheel, `twine check` passes
   - [x] clean-venv wheel install runs `init`, `check`, `emit-c`, native
     `build`, and `serve` (landing, playground, check endpoint)
   - [x] every playground asset is force-included; `tests/test_packaging.py`
   - [ ] `twine upload`, then `pip install "pythsol[test]"` from PyPI
2. **Hosted full compile (Render)** — staged, blocked on the Render billing
   card. Then run `Spikes/tools/render-service.ps1`.
3. **Deploy-to-Devnet button** — after Render is live; browser wallet,
   devnet RPC, program + IDL.
4. **Compiler gaps** — `[expr for i in range(<int>)]` now lowers to a
   `FixedArray[T, N]` local (`tests/test_listcomp.py`, including a LiteSVM
   run). PDA-signed `system_transfer` already uses `rt_move_lamports`
   (`tests/test_vec_pda.py`). Unbounded `Vec[T]` stays rejected by design.
   - [x] list comprehensions with a constant `range` length
   - [x] PDA-signed System Transfer
   - [x] unbounded `Vec[T]` diagnosed with the account-layout reason
5. **More examples** — six real programs now: counter, ledger, vault,
   escrow, multisig, poll. Each one compiles
   (`tests/test_examples.py`); the stateful and lamport ones run in LiteSVM
   (`tests/test_examples_litesvm.py`). `multisig` and `poll` are also CLI
   templates, exercised by `tests/test_testing_plugin.py`. Do not add stubs.
6. **Proof, not claims** — published audit (external), measured LiteSVM CU
   benchmarks, Lighthouse on the live site. Never copy another project's
   numbers.
7. **InsForge backend** — linked but empty; build tables/functions only for
   a real feature, not as a demo.
8. **Deploy automation** — pushing to `main` does not deploy. Add a GitHub
   Action (or a Vercel root build) that stages and deploys; until then use
   the CLI staging flow.

Not scheduled: in-browser SBF/WASM clang, a second intermediate
representation, translated docs (`i18n` intentionally empty).

## Hosting

Live as of 2026-11-01 — **one Vercel project, one domain**:

| Path | What runs there |
|---|---|
| `/` | Landing page (`landing.html`) |
| `/playground` | Editor: check + show C (serverless Python) |
| `/docs`, `/docs/...` | Starlight docs build (`web/docs`, `base: /docs`) |
| `/v1/check`, `/v1/emit` | Browser diagnostics / generated C, IDL, client |
| `/v1/compile` | 403 with Docker guidance (compile needs the SBF toolchain) |
| `/healthz`, `/examples*` | Health, init templates |

- Live on **`https://www.pythsol.com`** (verified 2026-11-01: domain at
  NameCheap, DNS on Cloudflare, `www` CNAME → the Vercel project). The
  Vercel alias `https://pythsol.vercel.app` still resolves.
- The single Vercel project is `pythsol` (the older `pythsol-docs` and
  `pythsol-playground` projects were deleted after the merge). Deploy the
  whole site with `Spikes/tools/stage-vercel-one.ps1` then
  `vercel deploy target\vercel_stage --prod --yes --scope
  rehmandakat67-3497 --name pythsol`. New deployments need the SSO
  protection toggle only once per project (`Spikes/tools/unprotect-pythsol.ps1`).
- Full-compile container playground: **Render** — blocked on a payment card
  at <https://dashboard.render.com/billing>; the create-service script is
  `Spikes/tools/render-service.ps1` (type `web_service`, repo
  `https://github.com/PythSol/pythsol`, branch `main`, Dockerfile
  `deploy/Dockerfile`, health check `/healthz`, plan `starter`).

Deploy notes and traps: `docs/guides/hosting.md`.

Rebuilding:

Static docs: from `web/docs`, run `npm install` and `npm run build`. Serve the `dist/` directory.

Playground on a server: `pythsol serve --public --host 0.0.0.0 --port 8765`. That process parses source. It does not run user code. Compile is off on a public bind unless you also pass `--allow-compile` — clang then runs on compiler-generated C only. `deploy/Dockerfile` packages the server with the sha256-pinned Anza platform-tools; guide: `docs/guides/hosting.md`.
