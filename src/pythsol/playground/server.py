"""HTTP playground. Bind it to loopback. User source is parsed, never executed.

``/v1/compile`` runs the same clang build as ``pythsol build`` on generated C.
It does not run the program.
"""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = ["RateLimiter", "bind"]

_MAX_BODY = 256 * 1024
_SECRET_KEYS = {
    "keypair",
    "mnemonic",
    "private_key",
    "privatekey",
    "secret",
    "seed_phrase",
}
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_ASSETS = Path(__file__).resolve().parent


class RateLimiter:
    """At most ``max_per_minute`` POSTs. Extra calls get HTTP 429."""

    def __init__(self, max_per_minute: int = 30) -> None:
        self.max_per_minute = max_per_minute
        self._hits: list[float] = []

    def allow(self) -> bool:
        now = time.monotonic()
        self._hits = [stamp for stamp in self._hits if now - stamp < 60]
        if len(self._hits) >= self.max_per_minute:
            return False
        self._hits.append(now)
        return True


def _has_secret(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).replace("-", "_").lower() in _SECRET_KEYS or _has_secret(item):
                return True
        return False
    if isinstance(value, list):
        return any(_has_secret(item) for item in value)
    return False


def _asset(name: str) -> bytes:
    return (_ASSETS / name).read_bytes()


def _check(source: str, filename: str) -> dict[str, Any]:
    from pythsol.compiler.front import check_source

    diagnostics = check_source(source, file=filename)
    return {
        "ok": not diagnostics,
        "diagnostics": [item.as_dict() for item in diagnostics],
    }


def _emit(source: str, filename: str) -> tuple[int, dict[str, Any]]:
    from pythsol.client.gen import render_client
    from pythsol.compiler.idl import idl_json
    from pythsol.compiler.pipeline import emit_program

    generated = emit_program(source, Path(filename))
    if not generated.ok or generated.generated is None:
        return 400, {
            "ok": False,
            "diagnostics": [item.as_dict() for item in generated.diagnostics],
        }
    return 200, {
        "ok": True,
        "c": generated.c_text,
        "idl": idl_json(generated.generated),
        "client": render_client(generated.generated),
    }


def _compile(source: str, filename: str) -> tuple[int, dict[str, Any]]:
    """Build a ``.so`` in a temp directory. Clang runs only on generated C."""
    from pythsol.cli.commands.build import BuildFailed, build_program
    from pythsol.compiler.diagnostics import PysolError

    stem = Path(filename).stem or "program"
    if stem in {"", ".", ".."}:
        return 400, {"ok": False, "error": "filename must be a single program name"}
    try:
        with tempfile.TemporaryDirectory(prefix="pythsol-serve-") as tmp:
            root = Path(tmp)
            path = root / f"{stem}.py"
            path.write_text(source, encoding="utf-8", newline="\n")
            try:
                built = build_program(path, out=root / "out", name=stem)
            except BuildFailed as failed:
                return 400, {
                    "ok": False,
                    "diagnostics": [item.as_dict() for item in failed.diagnostics],
                }
            except PysolError as error:
                return 400, {"ok": False, "error": error.message, "code": error.code}
            blob = built.so_path.read_bytes()
            return 200, {
                "ok": True,
                "cache": built.cache,
                "so_sha256": hashlib.sha256(blob).hexdigest(),
                "so_base64": base64.b64encode(blob).decode("ascii"),
                "idl": built.idl_path.read_text(encoding="utf-8"),
                "client": built.client_path.read_text(encoding="utf-8"),
            }
    except OSError as os_error:
        return 400, {"ok": False, "error": str(os_error)}


def _read_json(handler: BaseHTTPRequestHandler, limiter: RateLimiter) -> dict[str, Any] | None:
    if not limiter.allow():
        _send(handler, 429, {"ok": False, "error": "rate limited"}, retry_after="60")
        return None
    length = int(handler.headers.get("content-length") or "0")
    if length <= 0 or length > _MAX_BODY:
        _send(handler, 413, {"ok": False, "error": "body must be 1..262144 bytes"})
        return None
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        _send(handler, 400, {"ok": False, "error": "body must be JSON"})
        return None
    if not isinstance(payload, dict):
        _send(handler, 400, {"ok": False, "error": "body must be a JSON object"})
        return None
    if _has_secret(payload):
        _send(handler, 400, {"ok": False, "error": "request must not carry a secret"})
        return None
    return payload


def _source_of(payload: dict[str, Any]) -> tuple[str, str] | None:
    source = payload.get("source")
    filename = payload.get("filename") or "program.py"
    if not isinstance(source, str) or not isinstance(filename, str):
        return None
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    return source, filename


def _send(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: dict[str, Any] | bytes,
    *,
    content_type: str = "application/json; charset=utf-8",
    retry_after: str | None = None,
) -> None:
    raw = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body
    handler.send_response(status)
    handler.send_header("content-type", content_type)
    handler.send_header("content-length", str(len(raw)))
    handler.send_header("content-security-policy", "default-src 'self'")
    handler.send_header("cache-control", "no-store")
    if retry_after is not None:
        handler.send_header("retry-after", retry_after)
    handler.end_headers()
    handler.wfile.write(raw)


def _examples() -> tuple[tuple[str, ...], Callable[[str], str]]:
    """Load templates lazily so this module does not import the CLI package."""
    from pythsol.cli.templates import TEMPLATES, program_source

    return TEMPLATES, program_source


def make_handler(
    limiter: RateLimiter,
    *,
    compile_enabled: bool = True,
) -> type[BaseHTTPRequestHandler]:
    """Request handler closed over ``limiter``."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                _send(self, 200, _asset("landing.html"), content_type="text/html; charset=utf-8")
                return
            if path == "/index.html":
                _send(self, 200, _asset("index.html"), content_type="text/html; charset=utf-8")
                return
            if path in {"/playground", "/playground.html"}:
                _send(
                    self,
                    200,
                    _asset("playground.html"),
                    content_type="text/html; charset=utf-8",
                )
                return
            if path in {"/docs", "/docs.html"}:
                _send(self, 200, _asset("docs.html"), content_type="text/html; charset=utf-8")
                return
            if path == "/site.css":
                _send(self, 200, _asset("site.css"), content_type="text/css; charset=utf-8")
                return
            if path == "/app.css":
                _send(self, 200, _asset("app.css"), content_type="text/css; charset=utf-8")
                return
            if path == "/app.js":
                _send(
                    self,
                    200,
                    _asset("app.js"),
                    content_type="text/javascript; charset=utf-8",
                )
                return
            if path == "/favicon.svg":
                _send(self, 200, _asset("favicon.svg"), content_type="image/svg+xml")
                return
            if path == "/favicon.ico":
                _send(self, 200, _asset("favicon.ico"), content_type="image/x-icon")
                return
            if path == "/favicon-32.png":
                _send(self, 200, _asset("favicon-32.png"), content_type="image/png")
                return
            if path == "/apple-touch-icon.png":
                _send(self, 200, _asset("apple-touch-icon.png"), content_type="image/png")
                return
            if path == "/hero-bg.webp":
                _send(self, 200, _asset("hero-bg.webp"), content_type="image/webp")
                return
            if path == "/site-bg.svg":
                _send(self, 200, _asset("site-bg.svg"), content_type="image/svg+xml")
                return
            if path == "/healthz":
                _send(self, 200, {"ok": True, "compile": compile_enabled})
                return
            if path == "/examples":
                names, _load = _examples()
                _send(self, 200, {"examples": list(names)})
                return
            if path.startswith("/examples/"):
                names, load = _examples()
                name = path.removeprefix("/examples/")
                if name not in names:
                    _send(self, 404, {"ok": False, "error": "unknown example"})
                    return
                _send(
                    self,
                    200,
                    load(name).encode("utf-8"),
                    content_type="text/plain; charset=utf-8",
                )
                return
            _send(self, 404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            payload = _read_json(self, limiter)
            if payload is None:
                return
            parsed = _source_of(payload)
            if parsed is None:
                _send(self, 400, {"ok": False, "error": "source must be a string"})
                return
            source, filename = parsed
            if path == "/v1/check":
                _send(self, 200, _check(source, filename))
                return
            if path == "/v1/emit":
                status, body = _emit(source, filename)
                _send(self, status, body)
                return
            if path == "/v1/compile":
                if not compile_enabled:
                    _send(
                        self,
                        403,
                        {
                            "ok": False,
                            "error": "compile stays on the machine that has the SBF tools",
                        },
                    )
                    return
                status, body = _compile(source, filename)
                _send(self, status, body)
                return
            _send(self, 404, {"ok": False, "error": "not found"})

    return Handler


def bind(
    host: str,
    port: int,
    limiter: RateLimiter | None = None,
    *,
    public: bool = False,
    allow_compile: bool = False,
) -> ThreadingHTTPServer:
    """Listen on loopback. ``public`` allows another host and turns compile off.

    Check and emit only parse source. Compile runs clang, so a public bind
    does not offer it unless ``allow_compile`` says so explicitly. With the
    opt-in, clang still only ever sees compiler-generated C, never source
    the visitor wrote in C.
    """
    if host not in _LOOPBACK and not public:
        raise ValueError("the playground binds to loopback only")
    handler: Callable[..., BaseHTTPRequestHandler] = make_handler(
        limiter or RateLimiter(),
        compile_enabled=(not public) or allow_compile,
    )
    return ThreadingHTTPServer((host, port), handler)
