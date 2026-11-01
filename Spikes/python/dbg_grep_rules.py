"""Extract the exact built rules for the round-3 contrast fixes."""
from __future__ import annotations

import pathlib
import re

css = pathlib.Path(r"web\docs\dist\_astro\common.BdzTE204.css").read_text(
    encoding="utf-8", errors="replace"
)

for token in [
    r"\.meta[^{}]*\{[^}]*\}",
    r"\.pagination-links[^{}]*span[^{}]*\{[^}]*\}",
    r"\.sidebar-content a\[aria-current[^{}]*\{[^}]*\}",
]:
    hits = re.findall(token, css)
    print("###", token)
    for h in dict.fromkeys(hits):
        print("  ", h[:260])
    if not hits:
        print("   (none)")

print("### pill bg rule")
for h in dict.fromkeys(re.findall(r"\[aria-current=page\][^{}]*\{[^}]*\}", css)):
    print("  ", h[:300])
