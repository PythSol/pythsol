# Project status

This is the hostable surface. A checked box is in the tree and covered by a test or a local build. An empty box is not done.

The next agent should read **`docs/HANDOFF.md`** (goal, built, left, traps).
A short pointer is `AGENTS.md` at the repo root.

## Working now

- [x] Typed Python subset, checked with `pythsol check`
- [x] Native SBF `.so`, IDL, and solders client from `pythsol build`
- [x] LiteSVM tests for counter, ledger, vault, escrow, and the purse fixture
- [x] `pythsol test`, build cache, wallet, faucet, deploy, port, verify, profile
- [x] Hosted playground, browser check and emit: deployed to Vercel (`https://pythsol.vercel.app`) as one project with the docs; check and emit served as serverless Python, compile answers 403 with Docker guidance
- [x] Hosted docs: served under `/docs` of the same project (`https://pythsol.vercel.app/docs`), Starlight `base: /docs`
- [x] `pythsol.com` and `www.pythsol.com` are attached to the project — they go live as soon as the user points DNS (A `@` → `76.76.21.21`, CNAME `www` → `cname.vercel-dns.com`); the domain name itself is not registered yet
- [x] Hosted full-compile playground: staged on Render (`deploy/Dockerfile`, `starter` plan) — creation is blocked on a payment card in the Render dashboard
- [x] `Vec[T, N]`, fixed-width data enums, PDA lamport moves
- [x] Local playground: check, emit, and compile on loopback
- [x] Public playground: `pythsol serve --public` checks and emits, and does not compile until `--allow-compile`
- [x] Hosted deploy configs: `deploy/Dockerfile` (sha256-pinned platform-tools), Fly.io and Render blueprints, guide `docs/guides/hosting.md`
- [x] Playground layout follows the TypeSol split (source, then compiler output) in a light Python and Solana palette. See `docs/comparison-typesol.md`
- [x] Docs site builds with `npm run build` in `web/docs` (static files in `dist/`)
- [x] Windows is a supported developer machine for the compiler and LiteSVM

## Not done

- [ ] Unbounded `Vec[T]` (a value with no capacity would move later account fields)
- [ ] In-browser SBF compile (no WASM clang in this tree)
- [ ] A second compiler IR
- [ ] Translated docs
- [ ] List comprehensions
- [ ] Twenty gallery examples (four programs are real: counter, ledger, vault, escrow)
- [ ] Published audit
- [ ] PyPI release (version is still 0.1.0)
- [ ] Lighthouse score for the docs site

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
