"""Phase 1 acceptance: toolchain discovery, doctor, C->SBF spike.

The toolchain-based tests are marked `toolchain` and skip when no usable SBF
clang is locally runnable (Windows WDAC blocks unsigned clang; see
docs/decisions/ADR-0006-toolchain-platform-tools.md). They always run in the
GitHub Actions Linux job.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from pythsol.cli.commands.doctor import (
    CheckResult,
    DoctorReport,
    check_platform_tools,
    run_doctor,
)
from pythsol.compiler import toolchain
from pythsol.compiler.diagnostics import PysolError

# ---------------------------------------------------------------------------
# doctor (pure, no subprocess)
# ---------------------------------------------------------------------------


def test_doctor_report_placeholder() -> None:
    report = DoctorReport()
    report.add(CheckResult("fake-check", True, "does not need a toolchain"))
    assert report.ok


def test_doctor_skips_rpc_network_probe() -> None:
    report = run_doctor(do_rpc=False)
    names = {r.name for r in report.checks}
    assert "RPC reachable" in names
    rpc = next(r for r in report.checks if r.name == "RPC reachable")
    assert rpc.ok and "skipped" in rpc.detail


def test_doctor_reports_platform_tools(monkeypatch: pytest.MonkeyPatch) -> None:  # nosec B101
    monkeypatch.delenv("PYTHSOL_SBF_SDK", raising=False)
    monkeypatch.delenv("PYSOL_SBF_SDK", raising=False)
    res = check_platform_tools(None)
    assert isinstance(res, CheckResult)
    assert res.fix_cmd is not None or res.ok


def test_doctor_env_override_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHSOL_SBF_SDK", str(Path("definitely/not/a/real/sdk")))
    with pytest.raises(PysolError):
        toolchain.locate_platform_tools(None)


# ---------------------------------------------------------------------------
# toolchain discovery with a stubbed SDK dir
# ---------------------------------------------------------------------------


def _mk_fake_sdk(tmp_path: Path) -> Path:
    """Craft a fake unpacked platform-tools dir with stub clang + lld."""
    sdk = tmp_path / "v1.58" / "platform-tools"
    (sdk / "llvm" / "bin").mkdir(parents=True)
    clang = sdk / "llvm" / "bin" / ("clang.exe" if os.name == "nt" else "clang")
    lld = sdk / "llvm" / "bin" / ("ld.lld.exe" if os.name == "nt" else "ld.lld")
    clang.write_bytes(b"dummy clang")
    lld.write_bytes(b"dummy lld")
    return sdk


def test_locate_platform_tools_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk = _mk_fake_sdk(tmp_path)
    monkeypatch.setenv("PYTHSOL_SBF_SDK", str(sdk))
    tc = toolchain.locate_platform_tools(None)
    assert tc is not None
    assert tc.clang.is_file()
    assert tc.lld.is_file()
    assert tc.from_env is True


def test_locate_platform_tools_env_raises_for_bad_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHSOL_SBF_SDK", str(tmp_path / "does-not-exist"))
    with pytest.raises(PysolError):
        toolchain.locate_platform_tools(None)


def test_locate_platform_tools_default_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk = _mk_fake_sdk(tmp_path)
    monkeypatch.delenv("PYTHSOL_SBF_SDK", raising=False)
    monkeypatch.delenv("PYSOL_SBF_SDK", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # type: ignore[arg-type, attr-defined]
    # `find_clang` searches under `~/.cache/solana`, so bake the fake SDK there.
    (tmp_path / ".cache" / "solana").mkdir(parents=True, exist_ok=True)
    shutil.copytree(sdk, tmp_path / ".cache" / "solana" / sdk.name)
    tc = toolchain.locate_platform_tools(None)
    assert tc is not None


# ---------------------------------------------------------------------------
# C -> SBF spike (toolchain gated)
# ---------------------------------------------------------------------------


def _sbf_clang_available() -> Any:
    try:
        return toolchain.locate_platform_tools(None)
    except PysolError:
        return None


_tc = _sbf_clang_available()


@pytest.mark.toolchain
def test_hello_compiles_and_litesvm_reports_success(tmp_path: Path) -> None:
    pytest.importorskip("solders")
    if _tc is None:
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    source = Path(__file__).parents[1] / "Spikes" / "c" / "hello.c"
    so = toolchain.compile_to_sbf(_tc, source, tmp_path)
    assert so.is_file() and so.stat().st_size > 0
    spike = pytest.importorskip("Spikes.python.cn_litesvm_hello")
    ok, _logs = spike.run_hello_in_litesvm(so, spike.DEFAULT_PROGRAM_ID)
    assert ok
