"""Local playground HTTP API. The server parses source and does not run it."""

from __future__ import annotations

import base64
import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from pythsol.playground.server import RateLimiter, bind

ROOT = Path(__file__).parents[1]
COUNTER = (ROOT / "examples" / "counter" / "programs" / "counter.py").read_text(encoding="utf-8")


@pytest.fixture
def playground():
    httpd = bind("127.0.0.1", 0, RateLimiter(30))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def _get(url: str) -> tuple[int, bytes]:
    with urlopen(url, timeout=10) as response:
        return int(response.status), response.read()


def _post(
    url: str,
    payload: dict[str, object],
    timeout: int = 20,
) -> tuple[int, dict[str, object]]:
    raw = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=raw,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return int(response.status), body
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "read"):
            detail = exc.read().decode("utf-8")  # type: ignore[attr-defined]
            return int(exc.code), json.loads(detail)  # type: ignore[attr-defined]
        raise


def test_playground_check_emit_and_rejects_secrets(playground: str) -> None:
    status, health = _get(playground + "/healthz")
    assert status == 200
    assert json.loads(health)["ok"] is True
    page, html = _get(playground + "/")
    assert page == 200
    assert b"PythSol" in html
    assert b'href="/docs"' in html
    assert b'href="/playground"' in html
    editor_status, editor = _get(playground + "/playground")
    assert editor_status == 200
    assert b'<script src="/app.js">' in editor or b'<script src="/app.js"></script>' in editor
    assert b'href="/app.css"' in editor
    docs_status, docs = _get(playground + "/docs")
    assert docs_status == 200
    assert b"Quick start" in docs
    assert b"hero-landing" not in docs
    css_status, css = _get(playground + "/app.css")
    assert css_status == 200
    assert b"--blue: #306998" in css
    site_css_status, site_css = _get(playground + "/site.css")
    assert site_css_status == 200
    assert b"body::before" in site_css
    assert b'url("/site-bg.svg")' in site_css
    assert b".landing-nav" in site_css
    assert b".hero-accent" in site_css
    assert b".stack-scene" in site_css
    assert b".stack-card" in site_css
    assert b"top: var(--stack-top)" in site_css
    assert b"min-height: calc(100svh - var(--nav-h))" in site_css
    assert b"--stack-p" in site_css
    site_bg_status, site_bg = _get(playground + "/site-bg.svg")
    assert site_bg_status == 200
    assert site_bg.startswith(b"<svg")
    assert b"glow-blue" in site_bg
    assert b'class="landing-page"' in html
    assert b'class="landing-nav"' in html
    assert b'class="nav-inner"' in html
    assert b'class="nav-links"' in html
    assert b'class="hero hero-landing"' in html
    assert b'class="hero-accent"' in html
    assert b'class="scroll-cue"' in html
    assert b'class="stack-scene"' in html
    assert b'class="panel stack-card"' in html
    assert b'class="split stack-card"' in html
    assert b'class="bytes stack-card"' in html
    assert b"--stack-p" in html
    assert b'href="/hero-bg.webp"' in html
    hero_status, hero_bg = _get(playground + "/hero-bg.webp")
    assert hero_status == 200
    assert hero_bg.startswith(b"RIFF") and hero_bg[8:12] == b"WEBP"
    fav_status, fav = _get(playground + "/favicon.svg")
    assert fav_status == 200
    assert b">P</text>" in fav and b">S</text>" in fav
    ico_status, ico = _get(playground + "/favicon.ico")
    assert ico_status == 200
    assert ico.startswith(b"\x00\x00\x01\x00")
    ok, body = _post(playground + "/v1/check", {"source": COUNTER, "filename": "counter.py"})
    assert ok == 200
    assert body["ok"] is True
    bad, failed = _post(playground + "/v1/check", {"source": "x = 1\n", "filename": "bad.py"})
    assert bad == 200
    assert failed["ok"] is False
    codes = [item["code"] for item in failed["diagnostics"]]  # type: ignore[index,union-attr]
    assert codes
    emitted, payload = _post(
        playground + "/v1/emit",
        {"source": COUNTER, "filename": "counter.py"},
    )
    assert emitted == 200
    assert payload["ok"] is True
    assert "entrypoint" in str(payload["c"])
    secret, denied = _post(
        playground + "/v1/check",
        {"source": "x", "keypair": [1, 2, 3]},
    )
    assert secret == 400
    assert denied["ok"] is False
    compiled, artifact = _post(
        playground + "/v1/compile",
        {"source": COUNTER, "filename": "counter.py"},
        timeout=180,
    )
    if compiled == 200:
        assert artifact["ok"] is True
        raw = base64.b64decode(str(artifact["so_base64"]))
        assert raw.startswith(b"\x7fELF")
        assert len(str(artifact["so_sha256"])) == 64
    else:
        assert compiled == 400
        assert artifact.get("code") == "PS4010"


def test_playground_rate_limit() -> None:
    httpd = bind("127.0.0.1", 0, RateLimiter(1))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    base = f"http://{host}:{port}"
    try:
        first, _body = _post(base + "/v1/check", {"source": "x = 1\n"})
        second, limited = _post(base + "/v1/check", {"source": "x = 1\n"})
        assert first == 200
        assert second == 429
        assert limited["error"] == "rate limited"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def test_playground_refuses_a_public_bind() -> None:
    with pytest.raises(ValueError):
        bind("0.0.0.0", 0)


def test_public_mode_checks_and_refuses_compile() -> None:
    httpd = bind("127.0.0.1", 0, RateLimiter(30), public=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    base = f"http://{host}:{port}"
    try:
        status, health = _get(base + "/healthz")
        assert status == 200
        body = json.loads(health)
        assert body["ok"] is True
        assert body["compile"] is False
        ok, checked = _post(base + "/v1/check", {"source": "x = 1\n", "filename": "bad.py"})
        assert ok == 200
        assert checked["ok"] is False
        denied, payload = _post(
            base + "/v1/compile",
            {"source": "x = 1\n", "filename": "bad.py"},
        )
        assert denied == 403
        assert payload["ok"] is False
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def test_public_mode_compile_is_an_explicit_opt_in() -> None:
    """`--allow-compile` re-enables /v1/compile on a public bind."""
    httpd = bind("127.0.0.1", 0, RateLimiter(30), public=True, allow_compile=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    base = f"http://{host}:{port}"
    try:
        status, health = _get(base + "/healthz")
        assert status == 200
        assert json.loads(health)["compile"] is True
        compiled, artifact = _post(
            base + "/v1/compile",
            {"source": COUNTER, "filename": "counter.py"},
            timeout=180,
        )
        # 200 with real SBF tools on this machine; 400 (PS4010 family) when
        # the toolchain is missing — either way the endpoint must be open.
        assert compiled != 403
        if compiled == 200:
            raw = base64.b64decode(str(artifact["so_base64"]))
            assert raw.startswith(b"\x7fELF")
        else:
            assert artifact["ok"] is False
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
