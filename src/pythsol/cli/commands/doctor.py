"""`pythsol doctor` — diagnose the local environment.

Checks are read-only and side-effect free. Private keys are never read or
printed: we only stat the keypair file to see whether it exists (TR-SEC-01).
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen  # nosec B310 — only ever hits an opted-in RPC URL

import click

from pythsol.compiler import toolchain
from pythsol.compiler.diagnostics import PysolError

#: Default RPC endpoint; `doctor` only does a HEAD /
DEFAULT_RPC_URL = "https://api.devnet.solana.com"

#: Standard CLI fix command per missing check (TRD §7.2 doctor).
SOLANA_API_INSTALL_CMD = 'sh -c "$(curl -sSfL https://release.anza.xyz/stable/install)"'
PLATFORM_TOOLS_INSTALL_CMD = (
    "solana-install update   # installs Agave + platform-tools (clang/lld) under ~/.cache/solana"
)
KEYPAIR_GEN_CMD = "solana-keygen new --no-bip39-passphrase"


@dataclass(frozen=True)
class CheckResult:
    """One recorded ✓ / ✗ line of `pythsol doctor`."""

    name: str
    ok: bool
    detail: str
    fix_cmd: str | None = None

    def render(self) -> str:
        mark = "✓" if self.ok else "✗"
        body = f"{mark} {self.name}"
        if self.detail:
            body = f"{body} {self.detail}" if self.ok else f"{body} ({self.detail})"
        if not self.ok and self.fix_cmd:
            body = f"{body}\n  → fix: {self.fix_cmd}"
        return body

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail, "fix_cmd": self.fix_cmd}


@dataclass
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, res: CheckResult) -> None:
        self.checks.append(res)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.checks)

    def render(self) -> str:
        return "\n".join(r.render() for r in self.checks)

    def to_json(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": [r.to_json() for r in self.checks]}


# ---------------------------------------------------------------------------
# Individual checks (kept small so tests can stub each one)
# ---------------------------------------------------------------------------


def check_python_version() -> CheckResult:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 11) and sys.version_info < (3, 14)
    fix = None if ok else "pipx install pythsol  # needs Python 3.11-3.13"
    return CheckResult("Python", ok, version, fix)


def check_platform_tools(sdk: str | None = None) -> CheckResult:
    try:
        tc = toolchain.locate_platform_tools(sdk)
    except PysolError as err:
        return CheckResult("platform-tools", False, err.message, PLATFORM_TOOLS_INSTALL_CMD)
    if tc is None:
        return CheckResult(
            "platform-tools",
            False,
            "no Agave/Anza platform-tools with `sbf` clang found",
            PLATFORM_TOOLS_INSTALL_CMD,
        )
    return CheckResult("platform-tools", True, tc.describe(), None)


def check_clang_lld(tc: toolchain.ToolchainPaths) -> CheckResult:
    """Make sure the located clang/lld actually respond to `--version`."""
    ok = _query_ok(str(tc.clang), ["--version"]) and _query_ok(str(tc.lld), ["--version"])
    detail = "clang and ld.lld answer --version" if ok else "clang or ld.lld failed to run"
    fix = None if ok else PLATFORM_TOOLS_INSTALL_CMD
    return CheckResult("clang/lld sanity", ok, detail, fix)


def _query_ok(binary: str, args: list[str], timeout_s: float = 30.0) -> bool:
    try:
        proc = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def check_solana_cli() -> CheckResult:
    path = toolchain.find_solana_cli()
    ok = path is not None
    detail = f"solana at {path}" if ok else "not found on PATH"
    return CheckResult("solana CLI", ok, detail, None if ok else SOLANA_API_INSTALL_CMD)


def check_cargo_build_sbf() -> CheckResult:
    path = toolchain.find_cargo_build_sbf()
    ok = path is not None
    detail = f"cargo-build-sbf at {path}" if ok else "not found on PATH"
    return CheckResult("cargo-build-sbf", ok, detail, None if ok else PLATFORM_TOOLS_INSTALL_CMD)


def check_keypair(path: str | None = None) -> CheckResult:
    """The keypair file must exist; we never read or log its contents."""
    p = toolchain.default_solana_keypair() if path is None else Path(path).expanduser()
    ok = p.is_file()
    detail = str(p) if ok else f"not found at {p}"
    fix = None if ok else KEYPAIR_GEN_CMD
    return CheckResult("solana keypair file", ok, detail, fix)


def check_rpc(
    url: str | None = None,
    *,
    enabled: bool = True,
    timeout_s: float = 5.0,
) -> CheckResult:
    """HEAD the RPC health endpoint. Never sends or stores a key."""
    if not enabled:
        return CheckResult("RPC reachable", True, "skipped (--no-rpc)", None)
    target = (url or DEFAULT_RPC_URL).rstrip("/")
    try:
        with urlopen(
            Request(target, method="HEAD", headers={"User-Agent": "pythsol-doctor/0.1"}),
            timeout=timeout_s,
        ) as resp:
            status = getattr(resp, "status", resp.getcode())
            ok = 200 <= int(status) < 500
        detail = target
    except Exception as err:
        return CheckResult("RPC reachable", False, f"{target}: {err}", None)
    return CheckResult("RPC reachable", ok, detail, None)


def run_doctor(
    *,
    rpc: str | None = None,
    do_rpc: bool = True,
    sdk: str | None = None,
) -> DoctorReport:
    """Build the full report (pure, no I/O beyond what is stated)."""
    report = DoctorReport()
    report.add(check_python_version())
    tc_ok = False
    try:
        tc = toolchain.locate_platform_tools(sdk)
        tc_ok = tc is not None and tc.clang.is_file()
    except PysolError:
        tc_ok = False
        tc = None
    report.add(check_platform_tools(sdk))
    if tc_ok and tc is not None:
        report.add(check_clang_lld(tc))
    report.add(check_solana_cli())
    report.add(check_cargo_build_sbf())
    report.add(check_keypair())
    report.add(check_rpc(rpc, enabled=do_rpc))
    return report


@click.command(name="doctor")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.option("--rpc", default=None, metavar="URL", help="Override RPC URL.")
@click.option("--no-rpc", is_flag=True, default=False, help="Skip the RPC network probe.")
@click.option("--sdk", default=None, metavar="DIR", help="Override platform-tools discovery.")
def doctor(
    as_json: bool,
    rpc: str | None,
    no_rpc: bool,
    sdk: str | None,
) -> None:
    """Diagnose the local environment (toolchain, solana CLI, keypair, RPC)."""
    report = run_doctor(rpc=rpc, do_rpc=not no_rpc, sdk=sdk)
    if as_json:
        click.echo(json.dumps(report.to_json(), indent=2))
    else:
        click.echo(report.render())
    sys.exit(0 if report.ok else 1)
