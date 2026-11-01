"""GET /examples and /examples/<name> — the init templates."""

from __future__ import annotations

from urllib.parse import parse_qs

from wsgi_common import _json_response


def _names() -> list[str]:
    from pythsol.playground.server import _examples

    names, _loader = _examples()
    return list(names)


def _load(name: str) -> str | None:
    from pythsol.playground.server import _examples

    names, loader = _examples()
    if name not in names:
        return None
    return loader(name)


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    if method != "GET":
        return _json_response(start_response, 405, {"ok": False, "error": "GET only"})
    query = parse_qs(environ.get("QUERY_STRING", ""))
    name = (query.get("name") or [None])[0]
    if name is None:
        return _json_response(start_response, 200, {"examples": _names()})
    text = _load(name)
    if text is None:
        return _json_response(start_response, 404, {"ok": False, "error": "unknown example"})
    raw = text.encode("utf-8")
    start_response(
        "200 _",
        [
            ("content-type", "text/plain; charset=utf-8"),
            ("content-length", str(len(raw))),
            ("cache-control", "no-store"),
        ],
    )
    return [raw]
