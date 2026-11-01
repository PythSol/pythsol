"""IDL client and `pythsol port` skeletons."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pythsol.cli.main import cli
from pythsol.client.from_idl import render_client_from_idl
from pythsol.client.gen import render_client
from pythsol.client.port import render_port
from pythsol.compiler.front import check_source
from pythsol.compiler.idl import build_idl
from pythsol.compiler.pipeline import emit_program

ROOT = Path(__file__).parents[1]
COUNTER = ROOT / "examples" / "counter" / "programs" / "counter.py"
VAULT = ROOT / "examples" / "vault" / "programs" / "vault.py"


def _idl(path: Path) -> dict[str, object]:
    generated = emit_program(path.read_text(encoding="utf-8"), path)
    assert generated.ok and generated.generated is not None
    return build_idl(generated.generated)


def _assert_no_compiler_import(text: str) -> None:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "pythsol" not in alias.name
        if isinstance(node, ast.ImportFrom):
            assert node.module is None or "pythsol" not in (node.module or "")


def test_counter_idl_records_cpi_flags() -> None:
    idl = _idl(COUNTER)
    metadata = idl["metadata"]
    assert isinstance(metadata, dict)
    cpi = metadata["pythsol"]["cpi"]  # type: ignore[index]
    assert cpi["initialize"]["system"] is True
    assert cpi["initialize"]["pays"] is True
    assert cpi["increment"]["system"] is False


def test_client_from_idl_matches_the_model_client() -> None:
    pytest.importorskip("solders")
    from solders.pubkey import Pubkey

    generated = emit_program(COUNTER.read_text(encoding="utf-8"), COUNTER)
    assert generated.generated is not None
    model_src = render_client(generated.generated)
    idl_src = render_client_from_idl(build_idl(generated.generated))
    _assert_no_compiler_import(idl_src)
    left: dict[str, object] = {}
    right: dict[str, object] = {}
    exec(model_src, left)  # test-only: generated client has no pythsol import
    exec(idl_src, right)
    assert left["_DISC_INITIALIZE"] == right["_DISC_INITIALIZE"]
    program_id = Pubkey.new_unique()
    authority = Pubkey.new_unique()
    counter = Pubkey.new_unique()
    built_left = left["initialize"](program_id, authority, counter, 7)  # type: ignore[operator]
    built_right = right["initialize"](program_id, authority, counter, 7)  # type: ignore[operator]
    assert bytes(built_left.data) == bytes(built_right.data)  # type: ignore[attr-defined]
    assert len(built_left.accounts) == len(built_right.accounts)  # type: ignore[arg-type]
    for account_left, account_right in zip(
        built_left.accounts,  # type: ignore[attr-defined]
        built_right.accounts,  # type: ignore[attr-defined]
        strict=True,
    ):
        assert account_left.pubkey == account_right.pubkey
        assert account_left.is_signer == account_right.is_signer
        assert account_left.is_writable == account_right.is_writable
    bumped = left["increment"](program_id, authority, counter, 5)  # type: ignore[operator]
    other = right["increment"](program_id, authority, counter, 5)  # type: ignore[operator]
    assert bytes(bumped.data) == bytes(other.data)  # type: ignore[attr-defined]
    assert len(bumped.accounts) == 2  # type: ignore[attr-defined]


def test_port_counter_and_vault_check() -> None:
    for path in (COUNTER, VAULT):
        text = render_port(_idl(path))  # type: ignore[arg-type]
        diagnostics = check_source(text, file=f"{path.stem}_port.py")
        assert diagnostics == [], "\n".join(item.render() for item in diagnostics)
        assert "pass" in text
        assert "TODO" in text


def test_port_command_writes_a_file(tmp_path: Path) -> None:
    idl_path = tmp_path / "counter.json"
    idl_path.write_text(json.dumps(_idl(COUNTER)), encoding="utf-8")
    dest = tmp_path / "ported.py"
    result = CliRunner().invoke(cli, ["port", str(idl_path), "-o", str(dest)])
    assert result.exit_code == 0, result.stderr
    assert "TODO" in result.output
    assert dest.is_file()
    missing = CliRunner().invoke(cli, ["port", str(tmp_path / "nope.json")])
    assert missing.exit_code == 2
