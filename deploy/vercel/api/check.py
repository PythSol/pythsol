"""POST /v1/check — front-end diagnostics, no execution."""

from __future__ import annotations

from wsgi_common import _json_response, _read_body, _source_of

from pythsol.playground.server import _check


def app(environ, start_response):
    payload, error = _read_body(environ)
    if error is not None:
        return _json_response(start_response, 400, error)
    parsed = _source_of(payload)
    if parsed is None:
        return _json_response(start_response, 400, {"ok": False, "error": "source must be a string"})
    source, filename = parsed
    return _json_response(start_response, 200, _check(source, filename))
