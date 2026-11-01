"""POST /v1/emit — generated C, IDL and solders client. No clang, no run."""

from __future__ import annotations

from wsgi_common import _json_response, _read_body, _source_of

from pythsol.playground.server import _emit


def app(environ, start_response):
    payload, error = _read_body(environ)
    if error is not None:
        return _json_response(start_response, 400, error)
    parsed = _source_of(payload)
    if parsed is None:
        return _json_response(start_response, 400, {"ok": False, "error": "source must be a string"})
    source, filename = parsed
    status, body = _emit(source, filename)
    return _json_response(start_response, status, body)
