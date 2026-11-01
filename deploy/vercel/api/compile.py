"""POST /v1/compile — deliberately not served here.

Serverless runtimes have no SBF clang. The loopback/Docker playground does
(`deploy/Dockerfile`). This answers 403 with that guidance so the browser
tells the visitor where compile lives.
"""

from __future__ import annotations

from wsgi_common import _json_response

_COMPILER = (
    "Compile needs the SBF toolchain, which serverless hosting does not ship. "
    "Run it yourself with Docker: "
    "`docker run --rm -p 8080:8080 ghcr.io/OWNER/pythsol-playground` "
    "(see deploy/Dockerfile in the PythSol repo) — or grab the CLI: "
    "`pip install pythsol` then `pythsol build program.py`."
)


def app(environ, start_response):
    return _json_response(
        start_response,
        403,
        {"ok": False, "error": _COMPILER},
    )
