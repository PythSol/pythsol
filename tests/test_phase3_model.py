"""Phase 3 unit tests: ``ProgramModel`` elaboration, IDL, and negatives.

Covers (TRD §18 Phase 3, minus the toolchain-dependent parts):

* discriminators match an *independent* hashlib cross-check;
* the counter's Borsh layout (49 bytes, exact field offsets);
* custom error codes (6000 + index, declared member values kept as docs);
* ``idl.build_idl``/``validate_idl`` and deterministic ``idl_json``;
* negatives: phase-4 types (u128) rejected with PS4001 and ``Init[...]``
  missing its bump/payer rejected with PS5003.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pythsol.compiler.diagnostics import PS4001, PS5003, Diagnostic
from pythsol.compiler.idl import build_idl, idl_json, validate_idl
from pythsol.compiler.model import (
    ACCOUNT_DATA_OFFSET,
    CUSTOM_ERROR_BASE,
    ProgramModel,
    snake_case,
)
from pythsol.compiler.pipeline import emit_program

PROGRAM_DIR = Path(__file__).parents[1] / "examples" / "counter" / "programs"
COUNTER_PATH = PROGRAM_DIR / "counter.py"

_INITIALIZE_DISC = hashlib.sha256(b"global:initialize").digest()[:8]
_INCREMENT_DISC = hashlib.sha256(b"global:increment").digest()[:8]
_COUNTER_DISC = hashlib.sha256(b"account:Counter").digest()[:8]


@pytest.fixture(scope="module")
def counter_model() -> ProgramModel:
    """The elaborated counter model (pure Python pipeline; no toolchain)."""
    generated = emit_program(COUNTER_PATH.read_text(encoding="utf-8"), COUNTER_PATH)
    assert generated.ok, "\n".join(diag.render() for diag in generated.diagnostics)
    assert generated.generated is not None
    return generated.generated


# ---------------------------------------------------------------------------
# discriminators + layout
# ---------------------------------------------------------------------------


def _sha256_panama(prefix: bytes, name: str) -> bytes:
    """Independent mirror of Anchor's discriminator recipe (no model code)."""
    return hashlib.sha256(prefix + name.encode()).digest()[:8]


def test_account_discriminator_independent_cross_check(
    counter_model: ProgramModel,
) -> None:
    counter = counter_model.account("Counter")
    assert counter is not None
    assert counter.discriminator == _sha256_panama(b"account:", "Counter")
    assert counter.discriminator == _COUNTER_DISC


def test_instruction_discriminators_independent_cross_check(
    counter_model: ProgramModel,
) -> None:
    initialize = counter_model.instruction("initialize")
    increment = counter_model.instruction("increment")
    assert initialize is not None and increment is not None
    assert initialize.discriminator == _sha256_panama(b"global:", "initialize")
    assert increment.discriminator == _INCREMENT_DISC
    assert initialize.snake_name == "initialize"
    assert increment.snake_name == "increment"
    # Anchor dispatch names are snake_cased; two instructions must never collide.
    assert _INITIALIZE_DISC != _INCREMENT_DISC


def test_counter_layout_is_49_bytes_with_exact_offsets(
    counter_model: ProgramModel,
) -> None:
    counter = counter_model.account("Counter")
    assert counter is not None

    # disc(8) + authority(32) + count(8) + bump(1)
    assert counter.size == 49
    assert ACCOUNT_DATA_OFFSET == 8

    fields = {field.name: field for field in counter.fields}
    assert set(fields) == {"authority", "count", "bump"}
    authority = fields["authority"]
    count = fields["count"]
    bump = fields["bump"]
    assert (authority.c_type, authority.size, authority.offset) == ("SolPubkey", 32, 0)
    assert (count.c_type, count.size, count.offset) == ("uint64_t", 8, 32)
    assert (bump.c_type, bump.size, bump.offset) == ("uint8_t", 1, 40)

    # Absolute on-chain offsets: the last field ends exactly at `size`.
    assert ACCOUNT_DATA_OFFSET + authority.offset == 8
    assert ACCOUNT_DATA_OFFSET + count.offset == 40
    assert ACCOUNT_DATA_OFFSET + bump.offset == 48
    assert ACCOUNT_DATA_OFFSET + bump.offset + bump.size == counter.size


def test_instruction_params_keep_roles_and_borsh_widths(
    counter_model: ProgramModel,
) -> None:
    initialize = counter_model.instruction("initialize")
    increment = counter_model.instruction("increment")
    assert initialize is not None and increment is not None

    assert [(p.name, p.kind, p.index) for p in initialize.account_params] == [
        ("authority", "signer", 0),
        ("counter", "init", 1),
    ]
    assert [(p.name, p.c_type, p.size) for p in initialize.data_params] == [("bump", "uint8_t", 1)]

    assert [(p.name, p.kind) for p in increment.account_params] == [
        ("authority", "signer"),
        ("counter", "mut"),
    ]
    assert [(p.name, p.c_type, p.size) for p in increment.data_params] == [("by", "uint64_t", 8)]
    # Mut accounts must be writable; signer-only accounts must not be.
    for param in increment.account_params:
        if param.kind == "signer":
            assert not param.writable
        else:
            assert param.writable


def test_error_codes_are_6000_plus_index(counter_model: ProgramModel) -> None:
    assert CUSTOM_ERROR_BASE == 6000
    assert [(error.name, error.code, error.declared_value) for error in counter_model.errors] == [
        ("Unauthorized", 6000, 100),
        ("Overflow", 6001, 101),
    ]
    assert all(error.owner == "CounterError" for error in counter_model.errors)
    assert [error.code for error in counter_model.errors] == [
        CUSTOM_ERROR_BASE + error.index for error in counter_model.errors
    ]


def test_snake_case_matches_anchor_dispatch_naming() -> None:
    assert snake_case("initialize") == "initialize"
    assert snake_case("MyProgram") == "my_program"
    assert snake_case("GetDataURL") == "get_data_url"


# ---------------------------------------------------------------------------
# IDL
# ---------------------------------------------------------------------------


def test_idl_builds_and_validates_clean(counter_model: ProgramModel) -> None:
    idl = build_idl(counter_model)
    assert validate_idl(idl) == [], "a minimal valid program must have no IDL issues"

    assert idl["name"] == "counter"
    assert idl["version"] == "0.1.0" and idl["spec"] == "0.1.0"
    assert [instr["name"] for instr in idl["instructions"]] == [
        "initialize",
        "increment",
    ]
    by_name = {instr["name"]: instr for instr in idl["instructions"]}
    assert by_name["initialize"]["discriminator"] == list(_INITIALIZE_DISC)
    assert by_name["increment"]["discriminator"] == list(_INCREMENT_DISC)
    assert [account["name"] for account in idl["accounts"]] == ["Counter"]
    counter_entry = idl["accounts"][0]
    assert counter_entry["discriminator"] == list(_COUNTER_DISC)
    assert counter_entry["type"]["kind"] == "struct"
    fields = [field["name"] for field in counter_entry["type"]["fields"]]
    assert fields == ["authority", "count", "bump"]
    assert [error["name"] for error in idl["errors"]] == ["Unauthorized", "Overflow"]
    assert [error["code"] for error in idl["errors"]] == [6000, 6001]
    assert by_name["initialize"]["args"] == [{"name": "bump", "type": "u8"}]
    assert by_name["increment"]["args"] == [{"name": "by", "type": "u64"}]


def test_idl_json_is_deterministic_and_round_trips(
    counter_model: ProgramModel,
) -> None:
    first = idl_json(counter_model)
    second = idl_json(counter_model)
    assert first == second, "IDL JSON must be byte-stable across builds"
    assert first.endswith("\n")
    parsed = json.loads(first)
    assert json.dumps(parsed, indent=2, sort_keys=True) + "\n" == first
    assert validate_idl(parsed) == []


# ---------------------------------------------------------------------------
# negatives (full pipeline: diagnostics, no exceptions)
# ---------------------------------------------------------------------------


def _diag_codes(gen: object) -> list[str]:
    return [diagnostic.code for diagnostic in gen.diagnostics]  # type: ignore[attr-defined]


def _assert_has(gen: object, code: str, fragment: str) -> Diagnostic:
    matches = [
        diagnostic
        for diagnostic in gen.diagnostics  # type: ignore[attr-defined]
        if diagnostic.code == code and fragment in diagnostic.message
    ]
    assert matches, (
        f"expected {code} mentioning `{fragment}`, got: "
        f"{[(diagnostic.code, diagnostic.message) for diagnostic in gen.diagnostics]}"  # type: ignore[attr-defined]
    )
    return matches[0]  # type: ignore[return-value]


def test_u128_account_field_is_rejected_with_ps4001(tmp_path: Path) -> None:
    source = (
        "from pythsol import Mut, account, instruction, u64, u128\n"
        "\n"
        "@account\n"
        "class Big:\n"
        "    big: u128\n"
        "    small: u64\n"
        "\n"
        "@instruction\n"
        "def touch(acc: Mut[Big]) -> None:\n"
        "    acc.small = 1\n"
    )
    path = tmp_path / "big.py"
    path.write_text(source, encoding="utf-8", newline="\n")
    gen = emit_program(source, path)
    assert not gen.ok
    diagnostic = _assert_has(gen, PS4001, "field `big` has an unsupported type `u128`")
    assert diagnostic.line == 5  # the u128 annotation line


def test_u128_instruction_param_is_rejected_with_ps4001(tmp_path: Path) -> None:
    source = (
        "from pythsol import Mut, account, instruction, u64, u128\n"
        "\n"
        "@account\n"
        "class Small:\n"
        "    n: u64\n"
        "\n"
        "@instruction\n"
        "def touch(acc: Mut[Small], big: u128) -> None:\n"
        "    acc.n = 1\n"
    )
    path = tmp_path / "small.py"
    path.write_text(source, encoding="utf-8", newline="\n")
    gen = emit_program(source, path)
    assert not gen.ok
    diagnostic = _assert_has(gen, PS4001, "data parameter `big` has unsupported type `u128`")
    assert diagnostic.line == 8


def test_init_without_bump_is_rejected_with_ps5003(tmp_path: Path) -> None:
    source = (
        "from pythsol import Init, Signer, account, instruction, u64\n"
        "\n"
        "@account\n"
        "class Cnt:\n"
        "    n: u64\n"
        "\n"
        "@instruction\n"
        "def make(authority: Signer, cnt: Init[Cnt]) -> None:\n"
        "    cnt.n = 0\n"
    )
    path = tmp_path / "nobump.py"
    path.write_text(source, encoding="utf-8", newline="\n")
    gen = emit_program(source, path)
    assert not gen.ok
    _assert_has(gen, PS5003, "bump: u8")


def test_init_without_payer_signer_is_rejected_with_ps5003(tmp_path: Path) -> None:
    source = (
        "from pythsol import Init, account, instruction, u8, u64\n"
        "\n"
        "@account\n"
        "class Cnt:\n"
        "    n: u64\n"
        "\n"
        "@instruction\n"
        "def make(cnt: Init[Cnt], bump: u8) -> None:\n"
        "    cnt.n = 0\n"
    )
    path = tmp_path / "nopayer.py"
    path.write_text(source, encoding="utf-8", newline="\n")
    gen = emit_program(source, path)
    assert not gen.ok
    _assert_has(gen, PS5003, "Signer")
