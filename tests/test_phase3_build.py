"""Phase 3 tests: the ``pythsol build`` command (CLI → C → .so → IDL → manifest).

Marked ``toolchain``: needs the SBF platform-tools. Verifies (TRD §18):

* the CLI produces counter.c / counter.so / counter.json / manifest.json;
* two consecutive builds into *different* directories give byte-identical
  ``.so`` files (build determinism);
* manifest hashes match the actual files.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from pythsol.cli.commands.build import build as build_cmd

_PROGRAM = Path(__file__).parents[1] / "examples" / "counter" / "programs" / "counter.py"


def _tools_anywhere() -> bool:
    """Point PYTHSOL_SBF_SDK at the local spike SDK when nothing else exists."""
    from pythsol.compiler import toolchain
    from pythsol.compiler.diagnostics import PysolError

    try:
        found = toolchain.locate_platform_tools(None)
    except PysolError:
        found = None
    if found is not None:
        return True
    sdk = Path(__file__).parents[1] / "Spikes" / "tools" / "platform-tools-1.58"
    if not sdk.is_dir():
        return False
    os.environ.setdefault("PYTHSOL_SBF_SDK", str(sdk))
    try:
        return toolchain.locate_platform_tools(None) is not None
    except PysolError:
        return False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def toolchain_ready() -> None:
    if not _tools_anywhere():
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")


def _run_build(out: Path) -> dict[str, Any]:
    result = CliRunner().invoke(build_cmd, [str(_PROGRAM), "--out", str(out)])
    assert result.exit_code == 0, f"build failed:\n{result.output}"
    manifest_path = out / "manifest.json"
    assert manifest_path.is_file()
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert (out / manifest["files"]["so"]).is_file()
    assert (out / manifest["files"]["c"]).is_file()
    assert (out / manifest["files"]["idl"]).is_file()
    return manifest


@pytest.mark.toolchain
def test_build_artifacts_and_deterministic_so(tmp_path: Path, toolchain_ready: None) -> None:
    """Two consecutive builds produce byte-identical ELF outputs."""
    out_first = tmp_path / "build1"
    out_second = tmp_path / "build2"
    manifest_first = _run_build(out_first)
    manifest_second = _run_build(out_second)

    so_first = out_first / manifest_first["files"]["so"]
    so_second = out_second / manifest_second["files"]["so"]
    assert _sha256(so_first) == _sha256(so_second), (
        "two consecutive builds must be byte-deterministic (TRD §18 Phase 3)"
    )


@pytest.mark.toolchain
def test_manifest_hashes_and_fields(tmp_path: Path, toolchain_ready: None) -> None:
    out = tmp_path / "build3"
    manifest = _run_build(out)

    assert manifest["program"] == "counter"
    assert manifest["entrypoint"] == "entrypoint"
    assert manifest["generator"].startswith("pythsol ")
    assert manifest["source"].endswith("counter.py")

    for key in ("c", "idl", "so"):
        expected = _sha256(out / manifest["files"][key])
        assert manifest["sha256"][key] == expected, f"sha256[{key}] must match the file"

    toolchain_info = manifest["toolchain"]
    # `arch` records the clang -mcpu SBF version accepted by this toolchain
    # (e.g. "generic" for platform-tools <= 1.58; v1..v4 for newer ones).
    assert toolchain_info["arch"] in ("generic", "v1", "v2", "v3", "v4"), manifest["toolchain"]
    assert isinstance(toolchain_info["clang"], str) and toolchain_info["clang"]


@pytest.mark.toolchain
def test_build_emits_valid_idl(tmp_path: Path, toolchain_ready: None) -> None:
    from pythsol.compiler.idl import validate_idl

    out = tmp_path / "build4"
    manifest = _run_build(out)
    idl = json.loads((out / manifest["files"]["idl"]).read_text(encoding="utf-8"))
    assert validate_idl(idl) == []
    assert {instr["name"] for instr in idl["instructions"]} == {
        "initialize",
        "increment",
    }


@pytest.mark.unit
def test_build_rejects_bad_programs_without_toolchain(tmp_path: Path) -> None:
    """A compile error exits non-zero and prints diagnostics, before any SBF work."""
    source = tmp_path / "broken.py"
    source.write_text(
        "from pythsol import Init, Signer, account, instruction, u64\n"
        "\n"
        "@account\n"
        "class Cnt:\n"
        "    n: u64\n"
        "\n"
        "@instruction\n"
        "def make(authority: Signer, cnt: Init[Cnt]) -> None:\n"
        "    cnt.n = 0\n",
        encoding="utf-8",
        newline="\n",
    )
    result = CliRunner().invoke(build_cmd, [str(source), "--out", str(tmp_path / "out")])
    assert result.exit_code == 1
    assert "PS5003" in result.output, "the emitter diagnostic must reach the CLI"
    assert not (tmp_path / "out" / "broken.so").exists()
