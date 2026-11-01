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
