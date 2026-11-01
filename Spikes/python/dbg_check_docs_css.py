"""Assert the built docs CSS carries the round-3 contrast fixes."""
from __future__ import annotations

import pathlib

css = ""
for path in sorted(pathlib.Path(r"web\docs\dist\_astro").glob("*.css")):
    css += path.read_text(encoding="utf-8", errors="replace")

checks: list[str] = [
    # Palette stock ramps per mode
    "--sl-color-gray-1:#23262f",  # light: darkest first
    "--sl-color-gray-6:#edeef3",  # light: chip-light last but one
    "--sl-color-gray-2:#353841",  # light sidebar-link tone
    "--sl-color-gray-1:#edeef3",  # dark: lightest first
    "--sl-color-gray-5:#353841",  # dark inline-code bg ramp
    "--sl-color-gray-6:#23262f",  # dark: darkest last
    # Invert + chip + hairlines
    "--sl-color-text-invert:#fff",  # minifier short-hex
    "--sl-color-text-invert:#14171f",
    "--sl-color-bg-inline-code:var(--chip-bg)",
    "--sl-color-hairline-shade:var(--border)",
    # Targeted rules
    ".meta{color:var(--text-muted)",
    ".meta a,.meta a:hover{color:var(--sl-color-text-accent)",
    ".pagination-links :where(a)>span{color:var(--text-muted)",
    ".pagination-links :where(a)>span :where(.link-title){color:var(--text);font-weight:600",
    # Minifier unquotes attribute selectors and merges the pill selectors
    "a[aria-current=page]:hover{color:var(--sl-color-text-invert)",
]
missing = [c for c in checks if c not in css]
print("docs css checks:", "all present" if not missing else "MISSING")
for m in missing:
    print("  missing:", m)
