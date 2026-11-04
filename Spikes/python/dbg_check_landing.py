"""Check the staged landing page contains the new sections."""
from __future__ import annotations

import pathlib

h = pathlib.Path(r"target\vercel_stage\landing.html").read_text(encoding="utf-8")
checks = [
    # Hero + install honesty
    'class="hero hero-landing"',
    'class="hero-grid"',
    "hero-viz",
    'href="/hero-bg.webp"',
    "From PyPI",
    'href="/playground"',
    'href="/docs/quickstart"',
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
    'class="split stack-card"',
    'class="bytes stack-card"',
    "--stack-p",
    # Favicon formats + cache-busted SVG link
    'href="/favicon.ico"',
    'href="/favicon.svg?v=2"',
    'href="/favicon-32.png"',
    'href="/apple-touch-icon.png"',
    # Pipeline walkthrough
    'class="pipeline"',
    "checked at every step",
    # Real code pair
    "counter.py",
    "counter.c — excerpt",
    "pyf_increment",
    # Capabilities with where-it-runs tags
    'class="card"',
    "tag-web",
    "tag-cli",
    # Try in browser mock
    "Try it in the browser",
    'class="try-mock"',
    'href="/docs/playground"',
    # Example cards with real walk-through links
    "Learn from working programs",
    'href="/docs/tutorial-counter"',
    'href="/docs/tutorial-vault"',
    'href="/docs/tutorial-escrow"',
    'href="/docs/language"',
    'href="/examples/vault"',
    # Local dev + trust + FAQ
    "Local development",
    "pythsol doctor",
    'href="/docs/cli"',
    "What PythSol is",
    "What it isn't",
    'id="faq"',
    'class="reveal panel token" id="token"',
    'class="reveal panel roadmap" id="roadmap"',
    'class="milestone now"',
    'id="token-ca"',
    'id="copy-ca"',
    'href="https://pump.fun"',
    "Fees fund development",
    "pythsol test</code> executes the real program bytecode",
    # Footer columns
    "foot-grid",
    'href="/docs/security"',
    'href="/docs/architecture"',
    "target=\"_blank\"",
    # Reveal animation kept
    "IntersectionObserver",
    'class="reveal',
    # Visuals added this round
    'class="bytebar"',
    'aria-label="Counter account layout',
    "RT_SIZE_COUNTER",
    'class="seg seg-auth"',
    'class="artifacts reveal"',
    "manifest.json",
    'class="h2-mark"',
    'class="tile tile-counter"',
    'class="tile tile-ledger"',
    'class="tile tile-vault"',
    'class="tile tile-escrow"',
    'class="mock-browser"',
    "www.pythsol.com/playground",
    'id="copy-qs"',
    'id="qs-cmds"',
    'class="cmd-card"',
    'id="copy-install"',
    'id="install-cmds"',
    'class="cmd-text"',
    "pythsol init my-program",
    "pip install pythsol",
    'class="viz-artifacts"',
    'class="ok-ico"',
    'class="ln"',
    'href="#i-github"',
    'class="nav-ico"',
    'class="cta-ico"',
]
ok = all(c in h for c in checks)
print("landing sections all present:", ok)
print("missing:", [c for c in checks if c not in h])
# stray tags must not exist
print("no stray </main> in hero:", h.count("<main") == h.count("</main>"))
