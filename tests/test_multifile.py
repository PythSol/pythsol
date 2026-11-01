"""Project modules: sibling files are parsed, never executed."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from pythsol.cli.main import cli
from pythsol.compiler.front import check_source
from pythsol.compiler.pipeline import emit_program

ACCT = """\
from pythsol import Pubkey, account, u64, u8

@account
class Counter:
    authority: Pubkey
    count: u64
    bump: u8

@account
class Vault:
    owner: Pubkey
"""

MATHS = """\
from pythsol import u64

def add_one(value: u64) -> u64:
    return value + 1
"""

OPS = """\
from pythsol import Mut, account, instruction, u64

@account
class Counter:
    count: u64

@instruction
def increment(counter: Mut[Counter], by: u64) -> None:
    counter.count += by
"""

ENTRY = """\
from pythsol import Init, Mut, Signer, instruction, u64, u8
from acct import Counter
from maths import add_one

@instruction
def initialize(authority: Signer, counter: Init[Counter], bump: u8) -> None:
    counter.authority = authority.key
    counter.count = 0
    counter.bump = bump

@instruction
def increment(counter: Mut[Counter], by: u64) -> None:
    counter.count += add_one(by)
"""


def _mods() -> dict[str, str]:
    return {"acct": ACCT, "maths": MATHS}


def _files() -> dict[str, str]:
    return {"acct": "acct.py", "maths": "maths.py"}


def test_sibling_account_and_helper_typecheck_and_emit() -> None:
    diagnostics = check_source(ENTRY, "prog.py", modules=_mods(), module_files=_files())
    assert diagnostics == []
    generated = emit_program(
        ENTRY,
        Path("prog.py"),
        modules=_mods(),
        module_files=_files(),
    )
    assert generated.ok, [item.message for item in generated.diagnostics]
    text = generated.c_text
    assert "pyf_initialize" in text
    assert "pyf_increment" in text
    assert "do {" in text
    assert "maths.py" in text
    assert generated.generated is not None
    names = [item.name for item in generated.generated.instructions]
    assert names == ["initialize", "increment"]


def test_imported_instruction_joins_the_program() -> None:
    entry = "from ops import increment\n"
    modules = {"ops": OPS}
    files = {"ops": "ops.py"}
    diagnostics = check_source(entry, "prog.py", modules=modules, module_files=files)
    assert diagnostics == []
    generated = emit_program(entry, Path("prog.py"), modules=modules, module_files=files)
    assert generated.ok, [item.message for item in generated.diagnostics]
    assert "pyf_increment" in generated.c_text
    assert "ops.py" in generated.c_text
    assert generated.generated is not None
    assert [item.name for item in generated.generated.instructions] == ["increment"]


def test_unimported_name_stays_unknown() -> None:
    source = (
        "from pythsol import Account, instruction\n"
        "from acct import Counter\n"
        "\n"
        "@instruction\n"
        "def look(vault: Account[Vault]) -> None:\n"
        "    pass\n"
    )
    diagnostics = check_source(source, "prog.py", modules=_mods(), module_files=_files())
    assert any(
        item.code == "PS2001" and "Vault" in item.message and item.file == "prog.py"
        for item in diagnostics
    )


def test_missing_export_is_ps1001() -> None:
    source = "from acct import Nope\n"
    diagnostics = check_source(source, "prog.py", modules=_mods(), module_files=_files())
    assert [(item.code, item.line, item.col) for item in diagnostics] == [("PS1001", 1, 18)]
    assert "does not define `Nope`" in diagnostics[0].message


def test_stdlib_and_aliases_stay_rejected() -> None:
    modules = _mods()
    files = _files()
    cases = [
        ("from typing import Any\n", 1, 1),
        ("import os\n", 1, 1),
        ("from os import path\n", 1, 1),
        ("from . import x\n", 1, 1),
        ("from acct import *\n", 1, 18),
        ("from acct import Counter as C\n", 1, 18),
    ]
    for source, line, col in cases:
        diagnostics = check_source(source, "prog.py", modules=modules, module_files=files)
        assert (line, col) in {(item.line, item.col) for item in diagnostics if item.code == "PS1001"}
        assert any(item.code == "PS1001" for item in diagnostics)


def test_duplicate_declaration_across_files() -> None:
    source = (
        "from pythsol import Pubkey, account, u64, u8\n"
        "from acct import Counter\n"
        "\n"
        "@account\n"
        "class Counter:\n"
        "    authority: Pubkey\n"
        "    count: u64\n"
        "    bump: u8\n"
    )
    diagnostics = check_source(source, "prog.py", modules=_mods(), module_files=_files())
    assert any(
        item.code == "PS2001" and item.file == "acct.py" and "Counter" in item.message
        for item in diagnostics
    )


def test_import_cycle_is_reported() -> None:
    amod = (
        "from pythsol import account, u64\n"
        "from bmod import Other\n"
        "\n"
        "@account\n"
        "class Box:\n"
        "    n: u64\n"
    )
    bmod = (
        "from pythsol import account, u64\n"
        "from amod import Box\n"
        "\n"
        "@account\n"
        "class Other:\n"
        "    n: u64\n"
    )
    diagnostics = check_source(
        "from amod import Box\n",
        "prog.py",
        modules={"amod": amod, "bmod": bmod},
        module_files={"amod": "amod.py", "bmod": "bmod.py"},
    )
    assert any(
        item.code == "PS1001" and "cycle" in item.message and item.file == "bmod.py"
        for item in diagnostics
    )


def test_a_module_cannot_import_itself() -> None:
    diagnostics = check_source(
        "from prog import Counter\n",
        "prog.py",
        modules={"acct": ACCT},
        module_files={"acct": "acct.py"},
    )
    assert any(item.code == "PS1001" and "itself" in item.message for item in diagnostics)


def test_cli_check_reads_siblings(tmp_path: Path) -> None:
    folder = tmp_path / "programs"
    folder.mkdir()
    (folder / "acct.py").write_text(ACCT, encoding="utf-8", newline="\n")
    (folder / "maths.py").write_text(MATHS, encoding="utf-8", newline="\n")
    (folder / "prog.py").write_text(ENTRY, encoding="utf-8", newline="\n")
    (folder / "_skip.py").write_text("this is not a module\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", str(folder / "prog.py")])
    assert result.exit_code == 0, result.stdout + result.stderr
