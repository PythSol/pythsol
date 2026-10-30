# ADR-0008 — Framing & docs theme: light-only (Python blue/yellow + Solana accents)

- **Status:** accepted (scope change from PRD/TRD)
- **Date:** 2026-10-30
- **Deciders:** PythSol contributors (product decision from the project owner)

## Context

PRD F-08 / TRD §11 require "light and dark modes, plus system", with the light
theme derived from Python blue/yellow. The user's brief for this repository
overrides the *dark* mode: **"no dark color", use Python + Solana colors,
light theme only**. Because the docs site is Phase 7 territory, this ADR records
the project direction so Phase 7 doesn't have to guess.

## Decision

Implement a **single, light** design system:

- Palette: Python blue `#306998` / yellow `#FFD43B` (Python logo colors)
  **+ Solana accents** purple `#9945FF` and mint `#14F195` (used for small
  UI details such as hyperlink dots, badges, and the logo underline).
- No alternate "dark" tokens are shipped. Documentation will render a light page
  with one default `data-theme="light"` declaration.
- The tokens file `web/shared-tokens/tokens.json` keeps the token names TRD §11.2
  specified (`--bg`, `--text`, `--primary`, `--accent`, …) so future Phase 7 CSS
  and editor themes can latch on without layout Indies.
- WCAG 2.1 AA contrast is preserved (we'll add a contrast fixture in the docs job).

Deviation from PRD F-08/TDR §11.1: **dark mode is intentionally not implemented**,
per the product owner. Adding it later only requires adding tokens — Phase 7 CSS
and the docs theme pick up the same keys.

## Verification

- `web/shared-tokens/tokens.json` will land in Phase 7 along with the CSS comp.
  Nothing in Phase 0–3 depends on it.
