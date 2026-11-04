"""Verify the live homepage and playground carry the redesign markers."""
from __future__ import annotations

import time
import urllib.error
import urllib.request

BASE = "https://www.pythsol.com"


def _fetch(path: str) -> bytes:
    """Read a live URL, retrying the transient resets/timeouts this host sees."""
    last: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(BASE + path, headers={"User-Agent": "pythsol-check/1"})
        try:
            return urllib.request.urlopen(req, timeout=60).read()
        except urllib.error.HTTPError:
            raise
        except (TimeoutError, ConnectionError, urllib.error.URLError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    assert last is not None
    raise last


def get(path: str) -> str:
    return _fetch(path).decode("utf-8", "replace")


def get_bytes(path: str) -> bytes:
    return _fetch(path)


landing = get("/")
landing_checks: list[str] = [
    "hero-grid",
    "hero-viz",
    "viz-status",
    'href="/favicon.ico"',
    'href="/favicon.svg?v=2"',
    'href="/favicon-32.png"',
    'href="/apple-touch-icon.png"',
    # Landing-only dark hero + supplied backdrop
    'class="hero hero-landing"',
    'href="/hero-bg.webp"',
    # Full-cover hero + sticky story stack
    'class="landing-page"',
    'class="landing-nav"',
    'class="nav-inner"',
    'class="nav-links"',
    'class="nav-end"',
    'id="i-x"',
    'href="https://x.com/"',
    'href="#token"',
    'href="#roadmap"',
    'class="hero-accent"',
    'class="scroll-cue"',
    'class="stack-scene"',
    'class="panel stack-card"',
    "--stack-p",
    "From PyPI",
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
    'class="reveal panel token" id="token"',
    'class="reveal panel roadmap" id="roadmap"',
    'class="milestone now"',
    'id="token-ca"',
    'id="copy-ca"',
    'href="https://pump.fun"',
    "Fees fund development",
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
    "pip install pythsol",
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
    ".hero.hero-landing",  # dark backdrop scoped to the landing hero
    'url("/hero-bg.webp")',  # supplied neon art
    ".landing-nav",  # glass nav over the cover
    "nav.landing-nav .nav-end",  # X + GitHub cluster on the right rail
    ".token-grid",  # $PS token panel
    ".token-buy",  # Pump.fun exit
    ".milestones",  # milestone roadmap, no dates
    ".hero-accent",  # gradient "Python."
    ".stack-scene",  # sticky story stack
    ".stack-card",  # pinned story cards
    "position: sticky",  # stack pins on desktop
    "top: var(--stack-top)",  # shared pin line below the nav
    "--stack-p",  # scroll progress supplied by landing.html
    "min-height: calc(100svh - var(--nav-h))",  # full-cover hero
    "body::before",  # site-wide ambient canvas layer
    'url("/site-bg.svg")',  # generated vector backdrop
]
missing_site = [c for c in site_checks if c not in site]
print("site.css:", "all present" if not missing_site else "MISSING")
for m in missing_site:
    print("  missing:", m)

# Favicon: letterform-only PS — no background plate anywhere in the file.
fav = get("/favicon.svg")
fav_have = [
    'viewBox="0 0 32 32"',  # letterform spec, not the old 64 plate canvas
    ">P</text>",  # uppercase P and S, both cap height
    ">S</text>",
    "#ffd43b",  # Python yellow start (P)
    "#e8a20c",  # amber end: contrast on a white tab strip
    "#14f195",  # Solana mint (S)
    "#9945ff",  # Solana purple (S)
    "paint-order",  # outline sits behind the fill
]
fav_missing = [c for c in fav_have if c not in fav]
plate_gone = "<rect" not in fav
same_width = fav.count('textLength="14.6"') == 2
print("favicon:", "all present" if not fav_missing and plate_gone and same_width else "PROBLEM")
if not plate_gone:
    print("  plate <rect> still present")
if not same_width:
    print("  P and S letter widths differ")
for m in fav_missing:
    print("  missing:", m)

ico = get_bytes("/favicon.ico")
png32 = get_bytes("/favicon-32.png")
apple = get_bytes("/apple-touch-icon.png")
hero_bg = get_bytes("/hero-bg.webp")
site_bg = get_bytes("/site-bg.svg")
print("favicon ico:", "OK" if ico.startswith(b"\x00\x00\x01\x00") else "PROBLEM")
print("favicon png:", "OK" if png32.startswith(b"\x89PNG") else "PROBLEM")
print("apple touch icon:", "OK" if apple.startswith(b"\x89PNG") else "PROBLEM")
print(
    "hero bg webp:",
    "OK" if hero_bg.startswith(b"RIFF") and hero_bg[8:12] == b"WEBP" else "PROBLEM",
    len(hero_bg),
    "bytes",
)
print("site bg svg:", "OK" if site_bg.startswith(b"<svg") else "PROBLEM", len(site_bg), "bytes")

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
