"""Vault and escrow examples lower to C without the SBF toolchain."""

from __future__ import annotations

from pathlib import Path

from pythsol.compiler.front import check_source
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
VAULT = ROOT / "examples" / "vault" / "programs" / "vault.py"
ESCROW = ROOT / "examples" / "escrow" / "programs" / "escrow.py"


def test_vault_and_escrow_examples_compile() -> None:
    for path, seed in ((VAULT, "vault"), (ESCROW, "escrow")):
        source = path.read_text(encoding="utf-8")
        diagnostics = check_source(source, str(path))
        assert diagnostics == [], [item.render() for item in diagnostics]
        generated = emit_program(source, path)
        assert generated.ok, [item.render() for item in generated.diagnostics]
        assert f'(const uint8_t *)"{seed}"' in generated.c_text
        assert "rt_system_transfer(" in generated.c_text
