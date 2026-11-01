"""Vercel Python serverless functions for the PythSol playground.

Each ``api/*.py`` exposes a WSGI ``app`` and reuses the same check/emit
helpers as the loopback server, so browser check / emit behave identically.
Compile is handled as explicit user education: the endpoint answers 403 with
the Docker one-liner instead of importing the toolchain.
"""

from __future__ import annotations

import json

__all__ = ["_read_body", "_json_response", "_source_of", "_denied"]


_MAX_BODY = 256 * 1024


def _read_body(environ: dict) -> tuple[dict, None] | tuple[None, dict]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = 0
    if length <= 0 or length > _MAX_BODY:
        return None, {"ok": False, "error": "body must be 1..262144 bytes"}
    raw = environ["wsgi.input"].read(length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, {"ok": False, "error": "body must be JSON"}
    if not isinstance(payload, dict):
        return None, {"ok": False, "error": "body must be a JSON object"}
    return payload, None


def _json_response(start_response, status: int, body: dict) -> list[bytes]:
    raw = json.dumps(body).encode("utf-8")
    start_response(
        f"{status} _",
        [
            ("content-type", "application/json; charset=utf-8"),
            ("content-length", str(len(raw))),
            ("cache-control", "no-store"),
        ],
    )
    return [raw]


def _source_of(payload: dict) -> tuple[str, str] | None:
    source = payload.get("source")
    filename = payload.get("filename") or "program.py"
    if not isinstance(source, str) or not isinstance(filename, str):
        return None
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    return source, filename
