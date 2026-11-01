# Docs site scaffold

Astro `7.4.4` and Starlight `0.42.7`, pinned in `package.json` (ADR-0005).
The theme is light only (ADR-0008). Token values match
`web/shared-tokens/tokens.json`.

```bash
cd web/docs
npm install
npm run build
```

`npm run build` completed on this machine: 21 HTML pages and a Pagefind index.
The `i18n` content collection is not defined. Starlight prints a warning and
keeps its built-in English UI strings. Serve `dist/` from a static host.
Lighthouse and axe have not been run. Check and emit on a server with
`pythsol serve --public`. That mode does not compile. Compile is
`pythsol serve` on loopback.
