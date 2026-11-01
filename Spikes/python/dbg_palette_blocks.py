"""Print every :root-ish block that defines --sl-color-* from the built CSS."""
from __future__ import annotations

import re
import pathlib

css = ""
for path in sorted(pathlib.Path(r"web\docs\dist\_astro").glob("*.css")):
    css += path.read_text(encoding="utf-8", errors="replace")

blocks = re.findall(r"(?::root[^{}]{0,140}|\[data-theme[^\]]{0,60}\])\{([^}]*--sl-color-white[^}]*)\}", css)
for i, body in enumerate(blocks):
    vars_ = re.findall(r"--sl-color-[\w-]+:[^;{}]+", body)
    print(f"=== block {i} ({len(vars_)} vars)")
    for v in dict.fromkeys(vars_):
        print("  " + v)
