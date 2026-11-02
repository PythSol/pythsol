"""Smoke-test the staged one-project deployment tree (WSGI, offline)."""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import traceback

root = pathlib.Path(r"C:\Users\monkey\Desktop\Project Launch\PythSol")
stage = root / "target" / "vercel_stage"
sys.path.insert(0, str(stage))
os.chdir(stage)
for key in [k for k in list(sys.modules) if k.split(".")[0] in ("index", "wsgi_common", "pythsol")]:
    del sys.modules[key]
import index as m  # noqa: E402


def run(path: str, body: bytes = b"", method: str = "GET") -> tuple[str, bytes, dict]:
    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(body)),
        "QUERY_STRING": "",
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(),
    }
    out: dict = {}

    def sr(status, headers):
        out["status"] = status
        out["headers"] = {h[0].lower(): h[1] for h in headers}

    try:
        result = m.app(env, sr)
    except Exception:
        traceback.print_exc()
        return "EXC", b"", {}
    if "status" not in out or result is None:
        print("!! start_response never called for", path, "| result:", result)
        import inspect

        print("app file:", inspect.getsourcefile(m.app))
        return "NOSTART", b"", {}
    return out["status"].split(" ")[0], b"".join(result), out["headers"]


src = (root / "examples/counter/programs/counter.py").read_text(encoding="utf-8")
cases = [
    ("/", b"", "GET"),
    ("/playground", b"", "GET"),
    ("/favicon.svg", b"", "GET"),
    ("/favicon.ico", b"", "GET"),
    ("/favicon-32.png", b"", "GET"),
    ("/apple-touch-icon.png", b"", "GET"),
    ("/hero-bg.webp", b"", "GET"),
    ("/site-bg.svg", b"", "GET"),
    ("/docs", b"", "GET"),
    ("/docs/quickstart", b"", "GET"),
    ("/docs/site-bg.svg", b"", "GET"),
    ("/v1/check", json.dumps({"source": src, "filename": "c.py"}).encode(), "POST"),
]
for path, body, method in cases:
    st, raw, hdrs = run(path, body, method)
    ct = hdrs.get("content-type", "")[:24]
    print("%-16s %s %7dB %s" % (path, st, len(raw), ct))

st, raw, _ = run("/")
st, fav, _ = run("/favicon.svg")
st, ico, _ = run("/favicon.ico")
st, png32, _ = run("/favicon-32.png")
st, apple, _ = run("/apple-touch-icon.png")
st, hero_bg, _ = run("/hero-bg.webp")
st, site_bg, _ = run("/site-bg.svg")
st, docs_bg, docs_hdrs = run("/docs/site-bg.svg")
print("landing headline OK:", b"Write Solana programs in Python." in raw)
print("landing gradient span OK:", b'class="so"' in raw)
print("landing hero bg OK:", b'class="hero hero-landing"' in raw and b'href="/hero-bg.webp"' in raw)
print("favicon svg OK:", fav.startswith(b"<svg"))
print("favicon ico OK:", ico.startswith(b"\x00\x00\x01\x00"))
print("favicon png OK:", png32.startswith(b"\x89PNG"))
print("apple touch icon OK:", apple.startswith(b"\x89PNG"))
print("hero bg webp OK:", hero_bg.startswith(b"RIFF") and hero_bg[8:12] == b"WEBP", len(hero_bg), "bytes")
print("site bg svg OK:", site_bg.startswith(b"<svg"), len(site_bg), "bytes")
print(
    "docs site bg svg OK:",
    st == "200" and docs_bg.startswith(b"<svg"),
    len(docs_bg),
    "bytes",
    docs_hdrs.get("content-type", ""),
)
