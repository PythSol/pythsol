"""GET /healthz — compile is reportably off; the button hides itself."""

from __future__ import annotations

from wsgi_common import _json_response


def app(environ, start_response):
    return _json_response(
        start_response,
        200,
        {
            "ok": True,
            "compile": False,
            "note": "compile runs on a machine with the SBF tools (pythsol build / Docker)",
        },
    )
