"""Phase 4 unit tests: control flow, arrays, casts, client, init, and idl.

No SBF toolchain. The ledger program is the flagship: if/else, for-range,
FixedArray index updates, and checked add/sub.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from pythsol.cli.main import cli
from pythsol.cli.templates import program_source
from pythsol.client.gen import render_client
from pythsol.compiler.front import check_source
from pythsol.compiler.idl import build_idl
from pythsol.compiler.pipeline import GeneratedProgram, emit_program

ROOT = Path(__file__).parents[1]
LEDGER_PATH = ROOT / "examples" / "ledger" / "programs" / "ledger.py"
COUNTER_PATH = ROOT / "examples" / "counter" / "programs" / "counter.py"


def _emit(source: str, name: str = "prog.py") -> GeneratedProgram:
    return emit_program(source, Path(name))


def test_ledger_example_matches_the_init_template() -> None:
    assert LEDGER_PATH.read_text(encoding="utf-8") == program_source("ledger")
    assert COUNTER_PATH.read_text(encoding="utf-8") == program_source("counter")
    vault = ROOT / "examples" / "vault" / "programs" / "vault.py"
    escrow = ROOT / "examples" / "escrow" / "programs" / "escrow.py"
    assert vault.read_text(encoding="utf-8") == program_source("vault")
    assert escrow.read_text(encoding="utf-8") == program_source("escrow")


def test_ledger_lowers_control_flow_arrays_and_checked_math() -> None:
    source = LEDGER_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, LEDGER_PATH)
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    text = gen.c_text
    assert "RT_SIZE_LEDGER 81u" in text
    assert "if (" in text
    assert "rt_h1:" in text
    assert "rt_checked_add_u64" in text
    assert "rt_checked_sub_u64" in text
    assert 'rt_fail_log(1006u' in text
    assert "index out of bounds" in text
    assert gen.generated is not None
    idl = build_idl(gen.generated)
    ledger = next(account for account in idl["accounts"] if account["name"] == "Ledger")
    fields = {field["name"]: field["type"] for field in ledger["type"]["fields"]}
    assert fields["slots"] == {"array": ["u64", 4]}
    assert {item["name"] for item in idl["instructions"]} == {
        "initialize",
        "deposit",
        "apply",
        "fill",
    }
    codes = {err["name"]: err["code"] for err in idl["errors"]}
    assert codes == {"Unauthorized": 6000, "BadSlot": 6001, "Insufficient": 6002}


def test_client_builders_do_not_import_the_compiler() -> None:
    source = LEDGER_PATH.read_text(encoding="utf-8")
    gen = emit_program(source, LEDGER_PATH)
    assert gen.ok and gen.generated is not None
    text = render_client(gen.generated)
    assert "struct.pack" in text
    assert "def decode_ledger" in text
    assert "import pythsol" not in text
    assert "pythsol.compiler" not in text
    initialize, deposit = text.split("def deposit", 1)
    assert "is_signer=True, is_writable=True" in initialize
    assert "_SYSTEM_PROGRAM" in initialize
    assert "is_signer=True, is_writable=False" in deposit


def test_u8_plus_300_is_ps2007() -> None:
    source = (
        "from pythsol import Mut, account, instruction, u8, u64\n"
        "\n"
        "@account\n"
        "class Box:\n"
        "    v: u64\n"
        "\n"
        "@instruction\n"
        "def bad(box: Mut[Box]) -> None:\n"
        "    x: u8 = 1\n"
        "    y: u8 = x + 300\n"
        "    box.v = y\n"
    )
    diagnostics = check_source(source, file="wide.py")
    assert any(item.code == "PS2007" for item in diagnostics)


def test_narrowing_cast_is_checked_and_fitting_literals_are_not() -> None:
    narrow = _emit(
        "from pythsol import Mut, account, instruction, u8, u64\n"
        "\n"
        "@account\n"
        "class Box:\n"
        "    v: u64\n"
        "\n"
        "@instruction\n"
        "def narrow(box: Mut[Box], n: u64) -> None:\n"
        "    small: u8 = u8(n)\n"
        "    box.v = small\n",
        "narrow.py",
    )
    assert narrow.ok, "\n".join(diag.render() for diag in narrow.diagnostics)
    assert "cast out of range" in narrow.c_text

    literal = _emit(
        "from pythsol import Mut, account, instruction, u8, u64\n"
        "\n"
        "@account\n"
        "class Box:\n"
        "    v: u64\n"
        "\n"
        "@instruction\n"
        "def narrow(box: Mut[Box]) -> None:\n"
        "    small: u8 = u8(3)\n"
        "    box.v = small\n",
        "literal.py",
    )
    assert literal.ok, "\n".join(diag.render() for diag in literal.diagnostics)
    assert "cast out of range" not in literal.c_text


def test_while_else_break_and_for_continue_lower() -> None:
    source = (
        "from pythsol import Mut, account, instruction, u64\n"
        "\n"
        "@account\n"
        "class Box:\n"
        "    v: u64\n"
        "\n"
        "@instruction\n"
        "def tick(box: Mut[Box], k: u64) -> None:\n"
        "    i: u64 = 0\n"
        "    while i < k:\n"
        "        if i == 2:\n"
        "            break\n"
        "        i += 1\n"
        "    else:\n"
        "        box.v = i\n"
        "\n"
        "@instruction\n"
        "def skip(box: Mut[Box]) -> None:\n"
        "    for i in range(4):\n"
        "        if i == 1:\n"
        "            continue\n"
        "        box.v = box.v + 1\n"
    )
    gen = _emit(source, "loops.py")
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert "rt_broke_1" in gen.c_text
    assert "goto rt_c1" in gen.c_text or "goto rt_c2" in gen.c_text
    assert "rt_checked_shl" not in gen.c_text


def test_bitwise_and_shift_lower() -> None:
    source = (
        "from pythsol import Mut, account, instruction, u8, u64\n"
        "\n"
        "@account\n"
        "class Box:\n"
        "    v: u64\n"
        "\n"
        "@instruction\n"
        "def bits(box: Mut[Box]) -> None:\n"
        "    x: u8 = 3\n"
        "    y: u8 = x & 1\n"
        "    z: u8 = y << 1\n"
        "    box.v = z\n"
    )
    gen = _emit(source, "bits.py")
    assert gen.ok, "\n".join(diag.render() for diag in gen.diagnostics)
    assert "&" in gen.c_text
    assert "rt_checked_shl_u8" in gen.c_text


def test_bad_range_step_and_bare_break_are_diagnostics() -> None:
    stepped = _emit(
        "from pythsol import Mut, account, instruction, u64\n"
        "\n"
        "@account\n"
        "class Box:\n"
        "    v: u64\n"
        "\n"
        "@instruction\n"
        "def down(box: Mut[Box]) -> None:\n"
        "    for i in range(3, 0, -1):\n"
        "        box.v = i\n",
        "down.py",
    )
    assert any(item.code == "PS5002" for item in stepped.diagnostics)

    broken = _emit(
        "from pythsol import Mut, account, instruction, u64\n"
        "\n"
        "@account\n"
        "class Box:\n"
        "    v: u64\n"
        "\n"
        "@instruction\n"
        "def bare(box: Mut[Box]) -> None:\n"
        "    break\n",
        "bare.py",
    )
    assert any(item.code == "PS5001" for item in broken.diagnostics)


def test_init_writes_a_clean_project_and_idl_prints_json(tmp_path: Path) -> None:
    runner = CliRunner()
    dest = tmp_path / "app"
    created = runner.invoke(
        cli,
        ["init", str(dest), "--template", "ledger", "--name", "ledger"],
    )
    assert created.exit_code == 0, created.stderr
    program = dest / "programs" / "ledger.py"
    assert program.is_file()
    assert (dest / "pysol.toml").is_file()
    assert (dest / "pyproject.toml").is_file()
    assert (dest / "README.md").is_file()

    checked = runner.invoke(cli, ["check", str(program)])
    assert checked.exit_code == 0, checked.stdout + checked.stderr

    again = runner.invoke(cli, ["init", str(dest), "--name", "ledger"])
    assert again.exit_code == 2
    assert "not empty" in again.stderr

    dumped = runner.invoke(cli, ["idl", str(COUNTER_PATH)])
    assert dumped.exit_code == 0, dumped.stderr
    payload = json.loads(dumped.stdout)
    assert {item["name"] for item in payload["instructions"]} == {"initialize", "increment"}
