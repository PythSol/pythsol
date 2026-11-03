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
