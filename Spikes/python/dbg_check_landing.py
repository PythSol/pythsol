"""Check the staged landing page contains the new sections."""
from __future__ import annotations

import pathlib

h = pathlib.Path(r"target\vercel_stage\landing.html").read_text(encoding="utf-8")
checks = [
    'class="pipeline"',
    'class="stage"',
    'class="ribbon reveal"',
    'class="chrome"',
    'id="i-write"',
    'target="_blank"',
    "IntersectionObserver",
    'class="reveal',
    'class="cards reveal"',
    "Pick your road",
]
ok = all(c in h for c in checks)
print("landing sections all present:", ok)
print("missing:", [c for c in checks if c not in h])
# stray tags must not exist
print("no stray </main> in hero:", h.count("<main") == h.count("</main>"))
