"""Every shipped example passes the front end and lowers to C."""

from __future__ import annotations

from pathlib import Path

import pytest

from pythsol.compiler.front import check_source
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
NAMES = ("counter", "ledger", "vault", "escrow", "multisig", "poll")


def _example(name: str) -> Path:
    return ROOT / "examples" / name / "programs" / f"{name}.py"


@pytest.mark.parametrize("name", NAMES)
def test_every_example_checks_and_emits(name: str) -> None:
    path = _example(name)
    source = path.read_text(encoding="utf-8")
    diagnostics = check_source(source, str(path))
    assert diagnostics == [], [item.render() for item in diagnostics]
    generated = emit_program(source, path)
    assert generated.ok, [item.render() for item in generated.diagnostics]
    assert generated.generated is not None


def test_vault_and_escrow_keep_their_pda_transfers() -> None:
    for name, seed in (("vault", "vault"), ("escrow", "escrow")):
        path = _example(name)
        generated = emit_program(path.read_text(encoding="utf-8"), path)
        assert generated.ok
        assert f'(const uint8_t *)"{seed}"' in generated.c_text
        assert "rt_system_transfer(" in generated.c_text
