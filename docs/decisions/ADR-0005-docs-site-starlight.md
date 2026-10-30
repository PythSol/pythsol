# ADR-0005 — Documentation site: Astro Starlight

- **Status:** accepted (Phase 0; implementation is Phase 7)
- **Date:** 2026-10-30
- **Deciders:** PythSol contributors

## Context

TRD §3 picks **Astro Starlight** for the docs site. Before Phase 7 we should confirm
both the *current* Starlight release and its capacity for what the PRD needs:
Pagefind search, per-version builds, `<Playground>` MDX embeds, tokens.

## Decision

**Astro Starlight** remains the docs system of record.

- Starlight `0.42.7` and Astro `7.4.4` are current as of 2026-10-30. Pin those plus
  a companion Starlight plugin for Pagefind? **Not needed** — Starlight already
  integrates Pagefind and Starlight 0.42 has a docs search widget.
- Same-HTML static pages for the whole project (this repo ships `docs/` as content
  for Starlight later). No server-side rendering.
- Theming via `web/shared-tokens/tokens.json`, compiled once into CSS variables
  and consumed by Starlight, Shiki and CodeMirror (PRD F-08).

## Verification

- Checked the npm registry: `@astrojs/starlight` latest is 0.42.7 (2026-10-30) and
  `astro` latest is 7.4.4. Both are publish-installable from `npm`.
- Starlight is used by many Python/DS docs sites; the "i18n per‑tag build" and
  `<Playground>` embeds require an integration we build in Phase 7.

## Consequences

- We split docs content (`docs/`) from theme tokens (`web/shared-tokens/`).
- Phase 7 will vault the page inventory from PRD §5.3 into Starlight config.
- If Starlight can't host the playground embed cleanly, the fallback is
  MkDocs Material (no decision needed before Phase 7).
