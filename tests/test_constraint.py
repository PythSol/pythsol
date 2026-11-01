"""Account constraints: Seeds, HasOne, Address, Owner, CloseTo.

Checks run before the body (CloseTo runs after a successful body).
The counter program's PDA seed stays the account name.
"""

from __future__ import annotations

from pathlib import Path

from pythsol.compiler.front import check_source
from pythsol.compiler.idl import build_idl, validate_idl
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
VAULT = ROOT / "tests" / "fixtures" / "vault.py"
COUNTER = ROOT / "examples" / "counter" / "programs" / "counter.py"


def _messages(source: str) -> list[tuple[str, str]]:
    return [(diag.code, diag.message) for diag in check_source(source, "prog.py")]


def test_vault_constraints_lower_and_counter_stays() -> None:
    source = VAULT.read_text(encoding="utf-8")
    gen = emit_program(source, VAULT)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    text = gen.c_text
    assert '(const uint8_t *)"box", 3u,' in text
    assert '(const uint8_t *)"vault"' not in text
    assert "has one: vault.authority" in text
    assert "acc_vault->data + 8u" in text
    assert "address: vault" in text
    assert "&dp_expected" in text
    assert "owner: vault" in text
    assert "rt_owner_eq(acc_vault, rt->program_id)" not in text.split("pyf_own")[1].split(
        "pyf_close"
    )[0]
    assert "*acc_authority->lamports" in text
    assert "rt_st_u64(acc_vault->data - 8, 0u, 0u);" in text
    assert "1014u" in text
    assert gen.generated is not None
    init = gen.generated.instruction("initialize")
    assert init is not None
    vault = next(param for param in init.account_params if param.name == "vault")
    assert vault.seed == "box"
    close = gen.generated.instruction("close")
    assert close is not None
    payer = next(param for param in close.account_params if param.name == "authority")
    assert payer.lamport_dest and payer.writable
    idl = build_idl(gen.generated)
    assert validate_idl(idl) == []
    by_name = {instr["name"]: instr for instr in idl["instructions"]}
    note = {item["name"]: item for item in by_name["note"]["accounts"]}
    assert note["vault"]["relations"] == ["authority"]
    assert note["vault"]["constraints"] == [{"kind": "has_one", "field": "authority"}]
    assert by_name["initialize"]["accounts"][1]["constraints"] == [
        {"kind": "seeds", "seed": "box"}
    ]
    assert "constraints" not in by_name["retarget"]["accounts"][0]

    counter = emit_program(COUNTER.read_text(encoding="utf-8"), COUNTER)
    assert counter.ok
    assert '(const uint8_t *)"counter", 7u,' in counter.c_text
    assert "1014u" not in counter.c_text
    assert "return 0u; /* RT_OK */" in counter.c_text


def test_constraint_shapes_are_rejected() -> None:
    seeds = """from pythsol import Init, Mut, Seeds, Signer, account, instruction, u8, u64

@account
class Vault:
    balance: u64
    bump: u8

@instruction
def initialize(payer: Signer, vault: Seeds[Mut[Vault], "box"], bump: u8) -> None:
    vault.balance = 0
"""
    assert any(
        code == "PS3001" and "Seeds" in message and "Init" in message
        for code, message in _messages(seeds)
    )
    late = """from pythsol import HasOne, Mut, Pubkey, Signer, account, instruction, u64

@account
class Vault:
    authority: Pubkey
    balance: u64

@instruction
def note(vault: HasOne[Mut[Vault], "authority"], authority: Signer) -> None:
    vault.balance = 1
"""
    assert any(
        code == "PS3001" and "declared before" in message for code, message in _messages(late)
    )
    missing = """from pythsol import HasOne, Mut, Pubkey, Signer, account, instruction, u64

@account
class Vault:
    authority: Pubkey
    balance: u64

@instruction
def note(authority: Signer, vault: HasOne[Mut[Vault], "missing"]) -> None:
    vault.balance = 1
"""
    assert any(code == "PS2001" and "no field" in message for code, message in _messages(missing))
    closed = """from pythsol import CloseTo, Mut, Signer, account, instruction, u64

@account
class Vault:
    balance: u64

@instruction
def shut(authority: Signer, vault: CloseTo[Mut[Vault], authority]) -> None:
    return
"""
    assert any(
        code == "PS3001" and "has a `return`" in message for code, message in _messages(closed)
    )
    helper = """from pythsol import HasOne, Mut, Pubkey, account, instruction, u64

@account
class Vault:
    authority: Pubkey
    balance: u64

def touch(vault: HasOne[Mut[Vault], "authority"]) -> None:
    vault.balance = 1

@instruction
def note(vault: Mut[Vault]) -> None:
    touch(vault)
"""
    assert any(
        code == "PS3001" and "instruction accounts" in message
        for code, message in _messages(helper)
    )


def test_constraint_wrappers_still_refuse_aliases() -> None:
    """HasOne and Seeds hide Mut/Init; the alias check peels that wrapper."""
    aliased = """from pythsol import HasOne, Mut, Pubkey, Signer, account, instruction, u64

@account
class Vault:
    authority: Pubkey
    balance: u64

@instruction
def note(
    authority: Signer,
    left: HasOne[Mut[Vault], "authority"],
    right: HasOne[Mut[Vault], "authority"],
) -> None:
    left.balance = 1
"""
    assert any(
        code == "PS3000" and "Vault" in message and "right" in message
        for code, message in _messages(aliased)
    )
    twice = """from pythsol import Init, Seeds, Signer, account, instruction, u8, u64

@account
class Vault:
    balance: u64
    bump: u8

@instruction
def open_a(payer: Signer, vault: Seeds[Init[Vault], "box"], bump: u8) -> None:
    vault.balance = 0

@instruction
def open_b(payer: Signer, vault: Seeds[Init[Vault], "box"], bump: u8) -> None:
    vault.balance = 0
"""
    assert any(
        code == "PS3001" and "only one Init" in message for code, message in _messages(twice)
    )
