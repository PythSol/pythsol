# Agent notes

Full handoff for the next model: **`docs/HANDOFF.md`**.

Read that before compiler, playground, or docs work. Version stays 0.1.0.
Use `.venv\Scripts\python.exe`. PowerShell: `;` not `&&`. Do not reformat
`src/pythsol/compiler/emit.py`. Theme is light (Python blue / yellow, Solana
mint / purple accents). TypeSol is inspiration; do not copy their CU table
or token.

# InsForge backend

Backend for the hosted site is InsForge, project `pythsol` (appkey is in
`.insforge/project.json`). Linked 2026-11-01; agent skills `insforge`,
`insforge-cli`, `insforge-debug`, `insforge-integrations` are installed.
Backend is empty: no tables, buckets, or functions yet; auth has GitHub /
Google OAuth enabled plus email.

Rules: run the CLI as `npx -y @insforge/cli ...` (its own `-y`/`--yes`
flag skips confirmations). `.insforge/project.json` holds a full-admin
API key — server-only, never commit or share. `.env.local` holds the
public URL + anon key. Both are git-ignored. For backend infra use the
`insforge-cli` skill; for app code use the `insforge` skill. Project
agent memory: `npx -y @insforge/cli memory ...` list/recall/remember.
(This memory needs a paid InsForge plan on our free tier; unused.)

# Hosting — live site

`https://www.pythsol.com` verified live 2026-11-01 (200 OK,
title "PythSol — Solana programs in typed Python"). Domain registered
at NameCheap, zone on Cloudflare (may/tadeo.ns.cloudflare.com), apex
A -> 216.198.79.1, www CNAME -> 4ef91b6d76096047.vercel-dns-017.com.
Host: Vercel project `pythsol` (team rehmandakat67-3497), auto-deploys
from GitHub `PythSol/pythsol` main; InsForge is the backend, not the
host. Do not advertise other URLs as live. Item 4 in docs/HANDOFF.md
line ~91 refers to this host and URL.
