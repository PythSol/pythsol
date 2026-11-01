"""Events: emit(Name(...)) logs a fixed-width payload. It is not account data."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pythsol.client.gen import render_client
from pythsol.compiler.front import check_source
from pythsol.compiler.idl import build_idl, validate_idl
from pythsol.compiler.model import event_discriminator
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
BELL = ROOT / "tests" / "fixtures" / "bell.py"
COUNTER = ROOT / "examples" / "counter" / "programs" / "counter.py"


def _codes(source: str) -> list[tuple[str, str]]:
    return [(diag.code, diag.message) for diag in check_source(source, "prog.py")]


def test_bell_event_lowers_and_counter_stays() -> None:
    source = BELL.read_text(encoding="utf-8")
    gen = emit_program(source, BELL)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert gen.generated is not None
    event = next(item for item in gen.generated.events if item.name == "Bumped")
    assert event.discriminator == hashlib.sha256(b"event:Bumped").digest()[:8]
    assert event.discriminator == event_discriminator("Bumped")
    assert event.size == 8
    assert "rt_log_event(" in gen.c_text
    disc = ", ".join(f"{byte:#x}u" for byte in event.discriminator)
    assert disc.split(", ")[0] in gen.c_text
    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    assert idl["events"] == [
        {
            "name": "Bumped",
            "discriminator": list(event.discriminator),
            "fields": [{"name": "amount", "type": "u64", "index": False}],
        }
    ]
    client = render_client(gen.generated)
    assert "def decode_event(" in client
    assert "import pythsol" not in client
    namespace: dict[str, object] = {}
    exec(client, namespace)
    payload = event.discriminator + (5).to_bytes(8, "little")
    decode = namespace["decode_event"]
    assert callable(decode)
    assert decode(payload) == {"name": "Bumped", "fields": {"amount": 5}}

    counter = emit_program(COUNTER.read_text(encoding="utf-8"), COUNTER)
    assert counter.ok and counter.generated is not None
    assert counter.generated.events == []
    assert "rt_log_event(" not in counter.c_text
    assert build_idl(counter.generated)["events"] == []
    assert "return 0u; /* RT_OK */" in counter.c_text


def test_event_shapes_are_rejected() -> None:
    missing = """from pythsol import emit, event, instruction, u64

@event
class Bumped:
    amount: u64

@instruction
def ring(amount: u64) -> None:
    emit(Missing(amount))
"""
    assert any(code == "PS2001" and "unknown event" in message for code, message in _codes(missing))
    arity = """from pythsol import emit, event, instruction, u64

@event
class Bumped:
    amount: u64

@instruction
def ring(amount: u64) -> None:
    emit(Bumped())
"""
    assert any(code == "PS3001" and "takes 1 field" in message for code, message in _codes(arity))
    stored = """from pythsol import Mut, account, event, instruction, u64

@event
class Bumped:
    amount: u64

@account
class Bell:
    note: Bumped

@instruction
def ring(bell: Mut[Bell]) -> None:
    pass
"""
    assert any(code == "PS3001" and "logged, not stored" in message for code, message in _codes(stored))
    wide = """from pythsol import emit, event, instruction

@event
class Wide:
""" + "\n".join(f"    f{index}: u64" for index in range(128)) + """

@instruction
def ring() -> None:
    emit(Wide(""" + ", ".join("1" for _ in range(128)) + """))
"""
    # u64 must be imported; the wide case is a model error, so import it.
    wide = wide.replace("from pythsol import emit, event, instruction", "from pythsol import emit, event, instruction, u64")
    gen = emit_program(wide, Path("wide.py"))
    assert not gen.ok
    assert any(diag.code == "PS4001" and "payload cap" in diag.message for diag in gen.diagnostics)
