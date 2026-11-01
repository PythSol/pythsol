"""Single Python entrypoint for Vercel: the entire playground backend + UI.

The GA Python runtime routes every request to this one WSGI app, so it must
also serve the static bundle files. Reuses the exact check/emit helpers as
``pythsol.playground.server`` — diagnostics without ever executing code.
"""

from __future__ import annotations

import json
import os
import pathlib
from urllib.parse import parse_qs, unquote

from wsgi_common import _json_response, _read_body, _source_of

from pythsol.playground.server import _check, _emit, _examples


__all__ = ["app"]


_UI_FILES: dict[str, str] = {
    "playground.html": "text/html; charset=utf-8",
    "landing.html": "text/html; charset=utf-8",
    "docs.html": "text/html; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "site.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
}

_PAGE_ROUTES: dict[str, str] = {
    "/": "landing.html",
    "/playground": "playground.html",
}

_DOCS_TYPES: dict[str, str] = {
    "html": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "js": "text/javascript; charset=utf-8",
    "mjs": "text/javascript; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "xml": "application/xml; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "ico": "image/x-icon",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "wasm": "application/wasm",
    "map": "application/json; charset=utf-8",
    "webmanifest": "application/manifest+json",
}


def _not_found_404(start_response) -> list[bytes]:
    raw = b"not found"
    start_response(
        "404 _",
        [
            ("content-type", "text/plain; charset=utf-8"),
            ("content-length", str(len(raw))),
        ],
    )
    return [raw]


def _serve_ui(start_response, rel: str) -> list[bytes]:
    ctype = _UI_FILES.get(rel)
    if ctype is None:
        return _not_found_404(start_response)
    base = os.path.basename(rel)
    try:
        with open(base, "rb") as handle:
            raw = handle.read()
    except OSError:
        return _not_found_404(start_response)
    start_response(
        "200 _",
        [
            ("content-type", ctype),
            ("content-length", str(len(raw))),
            ("cache-control", "no-store"),
        ],
    )
    return [raw]


def _docs_static(start_response, path: str) -> list[bytes] | None:
    """Serve the Starlight build under /docs; None means not-a-docs-file."""
    if path == "/docs" or path == "/docs/":
        rel_parts: list[str] = []
    elif path.startswith("/docs/"):
        rel = unquote(path[len("/docs/"):])
        rel_parts = [part for part in rel.split("/") if part and part != "."]
    else:
        return None
    if ".." in rel_parts:
        return _not_found_404(start_response)

    doc_root = (pathlib.Path(os.environ.get("PYTHSOL_DOCS_DIR", "docs"))).resolve()
    candidates: list[pathlib.Path] = []
    if rel_parts:
        joined = doc_root.joinpath(*rel_parts)
        candidates = [joined / "index.html", joined.with_name(joined.name + ".html"), joined]
    else:
        candidates = [doc_root / "index.html"]
    target: pathlib.Path | None = None
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if doc_root not in resolved.parents and resolved != doc_root:
            continue
        if resolved.is_file():
            target = resolved
            break
    if target is None:
        return _not_found_404(start_response)

    suffix = target.suffix.lstrip(".").lower()
    ctype = _DOCS_TYPES.get(suffix, "application/octet-stream")
    try:
        raw = target.read_bytes()
    except OSError:
        return _not_found_404(start_response)

    rel_posix = target.relative_to(doc_root).as_posix()
    if "/_astro/" in f"/{rel_posix}" or "/pagefind/" in f"/{rel_posix}":
        cache = "public, max-age=31536000, immutable"
    elif suffix in _DOCS_TYPES and suffix != "html":
        cache = "public, max-age=300"
    else:
        cache = "public, max-age=60, must-revalidate"
    start_response(
        "200 _",
        [
            ("content-type", ctype),
            ("content-length", str(len(raw))),
            ("cache-control", cache),
        ],
    )
    return [raw]


def app(environ, start_response):
    """Dispatch on the browser path (UI pages, then examples/API)."""
    query = parse_qs(environ.get("QUERY_STRING", ""))
    path = unquote((query.get("pathname") or [environ.get("PATH_INFO", "/")])[0])
    method = environ.get("REQUEST_METHOD", "GET")

    docs_response = _docs_static(start_response, path)
    if docs_response is not None:
        return docs_response

    if path in _PAGE_ROUTES:
        return _serve_ui(start_response, _PAGE_ROUTES[path])

    if path == "/healthz":
        return _json_response(
            start_response,
            200,
            {
                "ok": True,
                "compile": False,
                "note": "compile runs on a machine with the SBF tools (pythsol build / Docker)",
            },
        )

    if path.startswith("/v1/check"):
        payload, error = _read_body(environ)
        if error is not None:
            return _json_response(start_response, 400, error)
        parsed = _source_of(payload)
        if parsed is None:
            return _json_response(
                start_response, 400, {"ok": False, "error": "source must be a string"}
            )
        source, filename = parsed
        return _json_response(start_response, 200, _check(source, filename))

    if path.startswith("/v1/emit"):
        payload, error = _read_body(environ)
        if error is not None:
            return _json_response(start_response, 400, error)
        parsed = _source_of(payload)
        if parsed is None:
            return _json_response(
                start_response, 400, {"ok": False, "error": "source must be a string"}
            )
        source, filename = parsed
        status, body = _emit(source, filename)
        return _json_response(start_response, status, body)

    if path.startswith("/v1/compile"):
        return _json_response(
            start_response,
            403,
            {
                "ok": False,
                "error": (
                    "Compile needs the SBF toolchain, which serverless hosting does "
                    "not ship. Run it yourself with Docker: "
                    "`docker run --rm -p 8080:8080 ghcr.io/OWNER/pythsol-playground` "
                    "(see deploy/Dockerfile in the PythSol repo) — or use the CLI: "
                    "`pip install pythsol` then `pythsol build program.py`."
                ),
            },
        )

    if path == "/examples" and method == "GET":
        names, _loader = _examples()
        return _json_response(start_response, 200, {"examples": list(names)})

    if path.startswith("/examples/") and method == "GET":
        name = path.rsplit("/", 1)[1]
        names, loader = _examples()
        if name not in names:
            return _json_response(
                start_response, 404, {"ok": False, "error": "unknown example"}
            )
        raw = loader(name).encode("utf-8")
        start_response(
            "200 _",
            [
                ("content-type", "text/plain; charset=utf-8"),
                ("content-length", str(len(raw))),
                ("cache-control", "no-store"),
            ],
        )
        return [raw]

    rel = path.lstrip("/")
    if rel in _UI_FILES:  # direct asset path e.g. /app.css
        return _serve_ui(start_response, rel)

    return _json_response(
        start_response, 404, {"ok": False, "error": f"unknown endpoint: {path}"}
    )
