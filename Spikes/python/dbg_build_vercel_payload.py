"""Build the Vercel inline-deploy payload for the built docs dist.

Output: target/vercel_dist_payload.json = {"files": [{file, data, encoding}...]}
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

DIST = Path(r"C:\Users\monkey\Desktop\Project Launch\PythSol\web\docs\dist")
OUT = Path(r"C:\Users\monkey\Desktop\Project Launch\PythSol\target")

files = []
for path in sorted(DIST.rglob("*")):
    if not path.is_file():
        continue
    rel = path.relative_to(DIST).as_posix()
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    files.append({"file": rel, "data": data, "encoding": "base64"})

# serve the dist root as the deployment output (frameworkless static)
files.append({
    "file": "vercel.json",
    "data": json.dumps({"outputDirectory": "."}, separators=(",", ":")),
    "encoding": "utf-8",
})

OUT.mkdir(parents=True, exist_ok=True)
payload = {"files": files}
(OUT / "vercel_dist_payload.json").write_text(
    json.dumps(payload, separators=(",", ":")), encoding="ascii"
)
total = sum(len(item["data"]) for item in files)
print(f"files: {len(files)}, base64 payload: {total/1_000_000:.2f} MB")
