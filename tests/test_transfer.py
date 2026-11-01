"""System transfer CPI. The counter client still appends System only for Init."""

from __future__ import annotations

from pathlib import Path

from pythsol.client.gen import render_client
from pythsol.compiler.front import check_source
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
PAY = ROOT / "tests" / "fixtures" / "pay.py"
COUNTER = ROOT / "examples" / "counter" / "programs" / "counter.py"


def _codes(source: str) -> list[tuple[str, str]]:
    return [(diag.code, diag.message) for diag in check_source(source, "prog.py")]


def test_pay_lowers_and_counter_client_stays() -> None:
    gen = emit_program(PAY.read_text(encoding="utf-8"), PAY)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.generated is not None
    pay = gen.generated.instruction("pay")
    assert pay is not None and pay.needs_system
    assert all(param.funds and param.writable for param in pay.account_params)
    assert "rt_system_transfer(" in gen.c_text
    client = render_client(gen.generated)
    assert client.count("_SYSTEM_PROGRAM") >= 2
    assert "is_writable=True" in client
    assert "import pythsol" not in client

    counter = emit_program(COUNTER.read_text(encoding="utf-8"), COUNTER)
    assert counter.ok and counter.generated is not None
    increment = counter.generated.instruction("increment")
    assert increment is not None and not increment.needs_system
    text = render_client(counter.generated)
    increment_fn = text.split("def increment(", 1)[1].split("def ", 1)[0]
    assert "_SYSTEM_PROGRAM" not in increment_fn
    assert "return 0u; /* RT_OK */" in counter.c_text
    assert "rt_system_transfer(" not in counter.c_text


def test_transfer_shapes_are_rejected() -> None:
    same = """from pythsol import Signer, instruction, system_transfer, u64

@instruction
def pay(payer: Signer, amount: u64) -> None:
    system_transfer(payer, payer, amount)
"""
    assert any("must differ" in message for _code, message in _codes(same))
    helper = """from pythsol import Signer, system_transfer, u64

def send(payer: Signer, dest: Signer, amount: u64) -> None:
    system_transfer(payer, dest, amount)
"""
    assert any(
        code == "PS3001" and "belongs in an instruction" in message
        for code, message in _codes(helper)
    )
