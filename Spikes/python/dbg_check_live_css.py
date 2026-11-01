"""Fetch the live docs site's built CSS and assert the round-3 contrast fixes."""
from __future__ import annotations

import re
import urllib.request

BASE = "https://www.pythsol.com"

html = urllib.request.urlopen(BASE + "/docs", timeout=60).read().decode("utf-8", "replace")
hrefs = sorted(
    {
        m
        for m in re.findall(r'href="((?:https://www\.pythsol\.com)?/docs/_astro/[^"]+\.css)"', html)
        if "/ec." not in m
    }
)
css = ""
for href in hrefs:
    url = BASE + (href if href.startswith("/") else "/" + href)
    css += urllib.request.urlopen(url, timeout=60).read().decode("utf-8", "replace")

checks: list[str] = [
    "--sl-color-gray-1:#23262f",
    "--sl-color-gray-1:#edeef3",
    "--sl-color-gray-5:#353841",
    "--sl-color-text-invert:#fff",
    "--sl-color-text-invert:#14171f",
    "--sl-color-bg-inline-code:var(--chip-bg)",
    "--sl-color-hairline-shade:var(--border)",
    ".meta{color:var(--text-muted)",
    ".meta a,.meta a:hover{color:var(--sl-color-text-accent)",
    ".pagination-links :where(a)>span{color:var(--text-muted)",
    ".pagination-links :where(a)>span :where(.link-title){color:var(--text);font-weight:600",
    "a[aria-current=page]:hover{color:var(--sl-color-text-invert)",
]
missing = [c for c in checks if c not in css]
print("live docs css checks:", "all present" if not missing else "MISSING")
for m in missing:
    print("  missing:", m)
