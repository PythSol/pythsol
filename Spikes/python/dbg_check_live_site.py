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
    # Visuals added this round
    'class="bytebar"',
    "RT_SIZE_COUNTER",
    'class="seg seg-auth"',
    'class="artifacts reveal"',
    "manifest.json",
    'class="h2-mark"',
    'class="tile tile-counter"',
    'class="mock-browser"',
    "www.pythsol.com/playground",
    'id="copy-qs"',
    'class="cmd-card"',
    'id="copy-install"',
    'id="install-cmds"',
    'class="cmd-text"',
    "pythsol init my-program",
    "pip install git+https://github.com/PythSol/pythsol.git",
    'class="viz-artifacts"',
    'class="ln"',
    'href="#i-github"',
    'class="cta-ico"',
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
    # Action icons added this round
    'class="lbl"',
    'href="#i-check"',
    'href="#i-rotate"',
    'href="#i-copy"',
    'class="nav-ico"',
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
    ".tabs[hidden] { display: none; }",  # hidden attribute must win over flex
    "button[hidden] { display: none; }",  # compile button hides on the host
    # Icons added this round
    "button .ico",
    ".pane-head .ico",
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
    # Visuals and motion added this round
    ".hero::before",  # dot grid + brand washes
    "@keyframes line-in",  # hero code stagger
    "pipe-nudge",  # pipeline flow arrows
    "prefers-reduced-motion",  # motion is opt-in
    ".bytebar",  # Counter account byte map
    ".seg-auth",
    ".artifacts",  # build artifact shelf
    ".tile-counter",  # example icon tiles
    ".mock-browser",  # browser chrome on the teaser
    ".copy-cmd",  # quickstart copy affordance
    ".cmd-card",  # hero install commands
    ".cmd-pre",
    ".cmd-line",
]
missing_site = [c for c in site_checks if c not in site]
print("site.css:", "all present" if not missing_site else "MISSING")
for m in missing_site:
    print("  missing:", m)

# Favicon: letterform-only pS — no background plate anywhere in the file.
fav = get("/favicon.svg")
fav_have = [
    'viewBox="0 0 32 32"',  # letterform spec, not the old 64 plate canvas
    "#ffd43b",  # Python yellow start (p)
    "#e8a20c",  # amber end: contrast on a white tab strip
    "#14f195",  # Solana mint (S)
    "#9945ff",  # Solana purple (S)
    "paint-order",  # outline sits behind the fill
]
fav_missing = [c for c in fav_have if c not in fav]
plate_gone = "<rect" not in fav
print("favicon:", "all present" if not fav_missing and plate_gone else "PROBLEM")
if not plate_gone:
    print("  plate <rect> still present")
for m in fav_missing:
    print("  missing:", m)

# The docs copy must be byte-identical to the route copy it shadows.
try:
    docs_fav = urllib.request.urlopen(
        urllib.request.Request(
            "https://www.pythsol.com/docs/favicon.svg",
            headers={"User-Agent": "pythsol-check/1"},
        ),
        timeout=60,
    ).read()
    same = docs_fav == get("/favicon.svg").encode("utf-8")
    print("docs favicon identical:", same)
except Exception as exc:  # noqa: BLE001 - diagnostic script prints the reason
    print("docs favicon fetch failed:", exc)
