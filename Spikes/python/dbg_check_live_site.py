"""Verify the live homepage and playground carry the redesign markers."""
from __future__ import annotations

import urllib.request


def get(path: str) -> str:
    base = "https://www.pythsol.com"
    req = urllib.request.Request(base + path, headers={"User-Agent": "pythsol-check/1"})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")


landing = get("/")
landing_checks: list[str] = [
    "hero-grid",
    "hero-viz",
    "viz-status",
    "not on PyPI yet",
    "checked at every step",
    "counter.c — excerpt",
    "tag-web",
    "tag-cli",
    "Try it in the browser",
    "try-mock",
    "Learn from working programs",
    '/docs/tutorial-counter',
    '/docs/tutorial-vault',
    '/docs/tutorial-escrow',
    '/docs/language',
    "/examples/counter",
    "Local development",
    "pythsol doctor",
    "What PythSol is",
    'id="faq"',
    "foot-grid",
    "/docs/security",
    "/docs/architecture",
    'target="_blank"',
]
missing = [c for c in landing_checks if c not in landing]
print("landing:", "all present" if not missing else "MISSING")
for m in missing:
    print("  missing:", m)

pg = get("/playground")
pg_checks = [
    'class="pane"',
    "pane-head",
    "Reset sample",
    'role="tablist"',
    'aria-controls="out"',
    'tabindex="0"',
    "aria-live=\"polite\"",
    '<script src="/app.js"></script>',
    'href="/app.css"',
]
missing_pg = [c for c in pg_checks if c not in pg]
print("playground:", "all present" if not missing_pg else "MISSING")
for m in missing_pg:
    print("  missing:", m)

css = get("/app.css")
css_checks = [
    "--blue: #306998",  # pinned by tests
    'height: clamp(420px',
    "pre.on-ok",
    "pre.on-diag",
    "pre.on-err",
]
missing_css = [c for c in css_checks if c not in css]
print("app.css:", "all present" if not missing_css else "MISSING")
for m in missing_css:
    print("  missing:", m)

site = get("/site.css")
site_checks = [
    "hero-grid",
    "try-mock",
    "foot-grid",
    "plus li::before",
    "flex-wrap",  # nav wrap for narrow screens
]
missing_site = [c for c in site_checks if c not in site]
print("site.css:", "all present" if not missing_site else "MISSING")
for m in missing_site:
    print("  missing:", m)
