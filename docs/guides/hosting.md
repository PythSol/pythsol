# Hosting the playground on the public internet

`pythsol serve` is the product: visitors write typed Python in the browser,
the server **parses** it (AST, never executed), and returns errors, generated
C, IDL, a solders client, and — with compile enabled — a ready Solana
program (`.so`), IDL and client.

## What is actually served

| Endpoint | Public default | `--allow-compile` |
|---|---|---|
| `GET /`, `/docs`, `/playground` | yes | yes |
| `POST /v1/check`, `/v1/emit` | yes | yes |
| `POST /v1/compile` | **403** | yes (.opt-in) |
| `GET /healthz`, `/examples*` | yes | yes |

Guards already in the server: 262 KB body cap, 30 requests/minute global rate
limit, secret-sniffing (keypair/mnemonic/seed words → HTTP 400), CSP
`default-src 'self'`, every compile in a fresh temp dir, clang sees only
compiler-generated C, and no user source is ever executed.

## What is deployed right now (2026-11-01)

| URL | What runs there | Made by |
|---|---|---|
| https://pythsol-docs-rehmandakat67-3497.vercel.app | Starlight docs (static) | Vercel CLI deploy of `web/docs/dist` |
| https://pythsol-playground.vercel.app | browser check + emit as one Python function; `POST /v1/compile` answers 403 with Docker guidance | Vercel CLI deploy of `deploy/vercel` tree |
| Render `pythsol-playground` | **not yet** — API account needs a card (see below) | `Spikes/tools/render-service.ps1` |

## Deploying to Vercel (check + emit, no compile)

The GA Python runtime wants **one** entrypoint file that exports
`def app(environ, start_response):` (exact signature — no default arguments,
or the interface detector rejects it), and it routes **every** request to
that function, so:

- `deploy/vercel/index.py` dispatches on `PATH_INFO`, serves the static UI
  files itself (`playground.html`, `app.css`, … they don't take priority
  over the function), and answers `404` JSON for unknown paths.
- Legacy multi-file `api/*.py` handlers are no longer auto-detected, and
  legacy `routes` in `vercel.json` are ignored. Keep
  `deploy/vercel/api/*` as the reference implementation for other hosts.
- `requirements.txt` needs `click>=8.1` because `_examples()` loads CLI
  templates. The bundle needs `pythsol/`, the UI files, and `wsgi_common.py`.

Commands (CLI is Vercel-authenticated on this Windows machine; token lives
in `%APPDATA%\com.vercel.cli\Data\auth.json` — never commit it):

```powershell
# stage then deploy (Spikes/tools/stage-vercel-play.ps1 builds the tree)
.\.venv\Scripts\python.exe Spikes\python\dbg_build_vercel_play_payload.py
powershell -NoProfile -ExecutionPolicy Bypass -File Spikes\tools\stage-vercel-play.ps1
target\cli\node_modules\.bin\vercel.cmd deploy target\vercel_play_stage `
  --prod --yes --scope rehmandakat67-3497 --name pythsol-playground
```

Traps learned here:

1. **New projects get Deployment Protection ON** (`ssoProtection:
   all_except_custom_domains`) — every URL 302s to a Vercel SSO page. Turn
   it off per project: Dashboard → Settings → Deployment Protection, or API
   `PATCH /v9/projects/{name}?teamId=…` with body `{"ssoProtection": null}`
   (`Spikes/tools/vercel-unprotect.ps1`). `deploymentType: "none"` is not a
   valid value; `null` is.
2. `--name` is deprecated but still creates/uses the named project;
   "Failed to link PythSol/pythsol … Login Connection" afterwards is
   ignorable noise — the deploy still completes when the name target exists.
3. PS 5.1's `Invoke-WebRequest` does not follow Vercel's `308` redirects —
   verify with `curl.exe -L` and a final-slash path.
4. The first build failed `PYTHON_ENTRYPOINT_NOT_FOUND` for
   `api.check:app`; see the entrypoint contract above — `index.py` at
   root fixed it.

## Render (full compile — blocked on billing)

The service creation body is done (`Spikes/tools/render-service.ps1`):
`type=web_service`, repo URL `https://github.com/PythSol/pythsol`, branch
`main`, `dockerfilePath=deploy/Dockerfile`, `healthCheckPath=/healthz`,
plan `starter`, region `oregon`. The API is reachable and the key is valid;
creative attempt returns **"Payment information is required"** — add a card
at <https://dashboard.render.com/billing>, then run the script again.
Source repo: `github.com/PythSol/pythsol` (branch `main`).

## Docker (the reference deploy)

`deploy/Dockerfile` builds a container with Python 3.12 plus the official
Anza platform-tools (v1.58, sha256-pinned, Rust toolchain stripped —
PythSol compiles C only). Final image ≈ 1.2 GB.

```powershell
docker build -f deploy/Dockerfile -t pythsol-playground .
docker run --rm -p 8080:8080 pythsol-playground
# open http://localhost:8080/playground
```

The container runs as a non-root user, exposes `/healthz` for the
orchestrator, and honours `PORT` (default 8080).

## Fly.io

```powershell
cd deploy
flyctl launch --copy-config   # rename the app in fly.toml first
flyctl deploy
```

`fly.toml` sets 1 shared CPU / 1 GB, HTTPS enforced, one ledger machine.

## Render

```powershell
render blueprint create   # uses deploy/render.yaml
```

Pick the `starter` plan; the free tier may refuse the ~1.2 GB image.

## Any VPS (Hetzner, DigitalOcean, …)

```bash
sudo apt-get install -y docker.io
sudo docker run -d --name pythsol --restart always \
  -p 80:8080 pythsol-playground
```

Put Caddy/nginx in front for automatic TLS, e.g.
`your-domain.com { reverse_proxy 127.0.0.1:80 }`.

## Static docs site

`web/docs` is a separate Starlight build. `npm install && npm run build` in
`web/docs`, then host `dist/` on any static CDN — or serve it with the
playground at a second subdomain (`docs.your-domain.com`).

## Rate limiting at scale

The in-process limiter is global (30 POSTs/min). Multiple replicas increase
capacity linearly; put Cloudflare or nginx `limit_req` in front for a global
ceiling. Known follow-ups: per-IP limiting and a compile queue.
