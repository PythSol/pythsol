"""Gallery and theme tokens stay inside the shipped surface."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_gallery_lists_every_example() -> None:
    payload = json.loads((ROOT / "docs" / "gallery" / "index.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in payload] == [
        "counter",
        "ledger",
        "vault",
        "escrow",
        "multisig",
        "poll",
    ]
    for item in payload:
        assert (ROOT / item["sourcePath"]).is_file()
        assert item["playgroundUrl"] == f"/examples/{item['id']}"
        assert item["tests"] == "passing"


def test_docs_terminal_uses_macos_traffic_lights() -> None:
    css = (ROOT / "web" / "docs" / "src" / "styles" / "theme.css").read_text(encoding="utf-8")
    assert ".sl-markdown-content .expressive-code .frame.is-terminal .header::before" in css
    assert "#ff5f57" in css
    assert "#febc2e" in css
    assert "#28c840" in css
    assert "mask-image: none" in css


def test_tokens_are_light_only() -> None:
    payload = json.loads(
        (ROOT / "web" / "shared-tokens" / "tokens.json").read_text(encoding="utf-8")
    )
    assert payload["theme"] == "light"
    assert "dark" not in payload
    tokens = payload["tokens"]
    assert tokens["--primary"] == "#306998"
    assert tokens["--accent"] == "#FFD43B"
    assert tokens["--solana-purple"] == "#9945FF"
    assert tokens["--solana-mint"] == "#14F195"
