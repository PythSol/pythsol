"""Build the Vercel inline-deploy payload for the serverless playground.

Output: target/vercel_play_payload.json = {"files": [{file, data, encoding}...]}
Includes: vercel.json, requirements.txt, api functions, playground UI assets,
and the whole pythsol package (compiler + client + playground server + CLI
templates; click arrives via requirements.txt).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(r"C:\Users\monkey\Desktop\Project Launch\PythSol")
OUT = ROOT / "target"


def text(rel: str, source: Path | None = None) -> tuple[str, str]:
    src = (source or ROOT / rel).resolve()
    return rel, src.read_text(encoding="utf-8")


files: list[tuple[str, str]] = []

# build config
files.append(("vercel.json", (ROOT / "deploy" / "vercel" / "vercel.json").read_text("utf-8")))
files.append(("requirements.txt", "click>=8.1\n"))

# serverless functions
for name in ("common.py", "wsgi_common.py", "check.py", "emit.py", "compile.py", "health.py", "examples.py"):
    pass  # guard against typos below
for name in ("wsgi_common.py", "check.py", "emit.py", "compile.py", "health.py", "examples.py"):
    files.append((f"api/{name}", (ROOT / "deploy" / "vercel" / "api" / name).read_text("utf-8")))

# playground UI (root-level static)
for name in ("playground.html", "docs.html", "app.css", "app.js", "site.css"):
    files.append((name, (ROOT / "src" / "pythsol" / "playground" / name).read_text("utf-8")))

# the pythsol package
pkg = ROOT / "src" / "pythsol"
files2: list[tuple[str, str, bool]] = []
for path in sorted(pkg.rglob("*")):
    if path.is_dir():
        continue
    rel = path.relative_to(pkg.parent).as_posix()
    if "__pycache__" in rel or rel.endswith(".pyc"):
        continue
    try:
        files2.append((rel, path.read_text(encoding="utf-8"), False))
    except UnicodeDecodeError:
        files2.append((rel, base64.b64encode(path.read_bytes()).decode("ascii"), True))

files.extend((f, d) for f, d, _ in files2)

OUT.mkdir(parents=True, exist_ok=True)
payload = {"files": []}
for item in files:
    f, d = item
    binary = any(f2 == f and b for f2, _d, b in files2)
    payload["files"].append(
        {"file": f, "data": d, "encoding": "base64" if binary else "utf-8"}
    )

(OUT / "vercel_play_payload.json").write_text(
    json.dumps(payload, separators=(",", ":")), encoding="ascii"
)
print(f"files: {len(payload['files'])}, payload MB: {len(json.dumps(payload))/1_000_000:.2f}")
