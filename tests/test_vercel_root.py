"""The repo-root Vercel build serves the site through one Python function."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]


def _app() -> Any:
    spec = importlib.util.spec_from_file_location("root_vercel_app", ROOT / "api" / "index.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


def _get(app: Any, path: str) -> tuple[str, bytes]:
    status: list[str] = []

    def start_response(state: str, headers: list[tuple[str, str]]) -> None:
        status.append(state)

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
    }
    body = b"".join(app(environ, start_response))
    return status[0], body


def test_root_vercel_config_builds_docs_and_routes_to_the_function() -> None:
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config["buildCommand"] == "npm --prefix web/docs ci && npm --prefix web/docs run build"
    assert config["rewrites"] == [{"source": "/(.*)", "destination": "/api/index?pathname=/$1"}]
    function = config["functions"]["api/index.py"]
    assert "src/pythsol/**" in function["includeFiles"]
    assert "web/docs/dist/**" in function["includeFiles"]
    assert "deploy/vercel/**" in function["includeFiles"]
    assert len(function["excludeFiles"]) <= 256
    assert "target/**" in function["excludeFiles"]
    assert "Spikes/**" in function["excludeFiles"]
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"


def test_root_vercel_app_serves_pages_and_robots() -> None:
    if not (ROOT / "web" / "docs" / "dist").is_dir():
        pytest.skip("web/docs/dist is not built; run npm run build in web/docs")
    app = _app()
    status, body = _get(app, "/")
    assert status.startswith("200")
    assert b'class="hero hero-landing"' in body
    assert b"Multisig treasury" in body
    status, robots = _get(app, "/robots.txt")
    assert status.startswith("200")
    assert b"Sitemap: https://www.pythsol.com/docs/sitemap-index.xml" in robots
    status, docs = _get(app, "/docs")
    assert status.startswith("200")
    assert b"PythSol" in docs
