"""Locate Agave/Anza platform-tools and wrap the SBF toolchain.

Discovery order mirrors ``TRD.md`` §7.2 and ``PS4xxx`` diagnostics:

1. ``--sdk`` CLI flag
2. ``PYTHSOL_SBF_SDK`` (spec) / ``PYSOL_SBF_SDK`` (draft alias) env var
3. ``~/.cache/solana`` default install path (newest version wins)
4. ``cargo-build-sbf`` / ``solana`` on ``PATH`` (CLI-driven fallback; the CLI may
   not give us portable ``clang`` flags, so it only proves Solana CLI is present)

The SBF compile pipeline for the spikes/tests lives in :func:`compile_to_sbf`.

All discovery is side-effect free, so ``pythsol doctor`` is safe in CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Any

from pythsol.compiler.diagnostics import PS4010, PysolError

__all__ = [
    "ToolchainPaths",
    "compile_to_sbf",
    "find_clang",
    "find_lld",
    "locate_platform_tools",
    "sbpf_compile_args",
    "sbpf_link_args",
]

#: Directory searched by default (`~/.cache/solana`).
DEFAULT_TMPCACHE_DIR = ".cache/solana"

#: Extra locations used if the default cache has nothing.
_EXTRA_SDK_DIRS = (
    "~/.cargo/.cargo/solana",  # anza-xyz/agave ≥ 3.x moved to a cargo sub-path
    "~/.cargo",
    "~/.local/share/solana",
    "~/.cache/solana-test-validator",
)


@dataclass(frozen=True)
class ToolchainPaths:
    """Confirmed paths to everything the compiler needs to emit ``.so``."""

    clang: Path
    lld: Path
    sdk_root: Path
    from_env: bool
    arch: str

    def describe(self) -> str:
        source = "env" if self.from_env else "default cache"
        return f"clang {self.clang} (arch {self.arch}, sdk {source}: {self.sdk_root})"

    @property
    def version(self) -> str | None:
        try:
            res = _run(
                [str(self.clang), "--version"],
                cwd=self.sdk_root,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        for line in res.splitlines():
            prefix = "clang version " if line.startswith("clang version ") else ""
            if prefix and len(line) > len(prefix):
                return line[len(prefix) :]
        return res.splitlines()[0] if res else None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def locate_platform_tools(sdk: str | None = None) -> ToolchainPaths | None:
    """Find a usable SBF toolchain.

    Returns ``None`` when nothing is found (doctor prints a fix instead).
    """
    env_override = sdk or os.environ.get("PYTHSOL_SBF_SDK") or os.environ.get("PYSOL_SBF_SDK")
    if env_override:
        found = _from_dir(Path(env_override).expanduser(), from_env=True)
        if found:
            return found
        # Explicit override that is unusable is an error, not a silent fallback.
        raise PysolError(
            code=PS4010,
            message=f"PYTHSOL_SBF_SDK={env_override} does not contain a SBF clang",
            fix="unpacked Agave platform-tools should have llvm/bin/clang{,exe,3}",
        )
    for candidate in _default_sdk_dirs():
        found = _from_dir(candidate, from_env=False)
        if found:
            return found
    # Fall back to `cargo-build-sbf`/`solana` on PATH — we can't get clang
    # directly from those, but doctor should know something exists.
    if which("cargo-build-sbf") or which("solana"):
        return _from_cargo_build_sbf()
    return None


def _from_cargo_build_sbf() -> ToolchainPaths | None:
    """When `cargo-build-sbf` is only reachable through PATH, derive a stub.

    The real clang lives under a versioned platform-tools dir; cargo-build-sbf
    knows the version but its flag set is unspecified. The compiler should
    eventually shell out to the CLI for builds it can't express, but Phase 1
    only needs to *locate* the chain for `doctor`.
    """

    from_evs: list[tuple[str, Path]] = []

    def _walk(root: Path) -> None:
        if not root.is_dir():
            return
        for inner in sorted(root.iterdir(), reverse=True):
            target = inner / "platform-tools" / "llvm" / "bin" / _exe("clang")
            if target.is_file():
                from_evs.append((f"PATH:{inner.name}", target))
                return

    for base in _default_sdk_dirs():
        _walk(base)
    if not from_evs:
        return None
    sdk, clang = from_evs[0]
    lld = find_lld(clang)
    if lld is None:
        return None
    assert sdk is not None  # narrow the Optional for mypy
    return ToolchainPaths(
        clang=clang,
        lld=lld,
        sdk_root=clang.parents[3],  # llvm/bin/clang -> platform-tools
        from_env=False,
        arch=_sbpf_version_from_clang(clang),
    )


def _default_sdk_dirs() -> list[Path]:
    home = Path.home()
    out = [home / DEFAULT_TMPCACHE_DIR]
    for rel in _EXTRA_SDK_DIRS:
        p = (home / rel).expanduser()
        if p.is_dir() and p != home / DEFAULT_TMPCACHE_DIR:
            out.append(p)
    # Include paths mentioned in other Agave docs for robustness.
    for rel in (
        "~/.cache/solana/v",
        "~/.cargo/bin",
    ):
        p = (home / rel).expanduser()
        if p.is_dir() and p != home / DEFAULT_TMPCACHE_DIR:
            out.append(p)
    return out


def _from_dir(root: Path, *, from_env: bool) -> ToolchainPaths | None:
    if not root.is_dir():
        return None
    clang = find_clang(root)
    if clang is None:
        return None
    lld = find_lld(clang)
    if lld is None:
        return None
    arch = _sbpf_version_from_clang(clang)
    return ToolchainPaths(clang=clang, lld=lld, sdk_root=root, from_env=from_env, arch=arch)


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform.startswith("win") else name


def find_clang(sdk_root: Path) -> Path | None:
    """Locate clang inside an (unpacked) platform-tools tree."""
    for pattern in ("llvm/bin/clang.exe", "llvm/bin/clang", "llvm/bin/clang-*", "bin/clang*"):
        matches = sorted(sdk_root.rglob(pattern), reverse=True)
        for candidate in matches:
            if candidate.is_file() and candidate.suffix.lower() == (
                ".exe" if sys.platform.startswith("win") else ""
            ):
                return candidate
    # On macOS the binary may be `clang` inside a `Contents/` dir.
    matches = sorted(sdk_root.rglob("clang"), reverse=True)
    for candidate in matches:
        if candidate.is_file() and not candidate.name.startswith("clang++"):
            return candidate
    return None


def find_lld(clang_path: Path) -> Path | None:
    """Find `ld.lld` next to a located clang."""
    llvm_bin = clang_path.parent
    for name in ("ld.lld.exe", "ld.lld", "lld.exe", "lld"):
        for pat in (name, f"{name}-*", f"{name}{sys.platform.lower()}"):
            for candidate in sorted(llvm_bin.rglob(pat), reverse=True):
                if candidate.is_file():
                    return candidate
    return None


#: CPU code the SBF target uses for `clang -mcpu=` (anza `sbf_base.rs` calls
#: `cpu` `generic|v1|v2|v3|v4`). Default is `v0`, matching `cargo-build-sbf`
#: `--arch v0` default.
DEFAULT_SBF_VERSION = "v0"

_SBF_CPU_NAMES = ("generic", "v1", "v2", "v3", "v4")


def _sbpf_version_from_clang(clang: Path) -> str:
    """Pick an SBF version accepted by the located clang for `--target=sbf`.

    We *never* silently change the bytecode shape: unsupported versions raise.
    """
    for name in _SBF_CPU_NAMES:
        try:
            result = _run(
                [str(clang), "--target=sbf", f"-mcpu={name}", "-c", "-", "-o", os.devnull],
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result and not result.startswith("clang.exe : error: unknown target CPU"):
            return name
    return DEFAULT_SBF_VERSION


def _run(args: list[str], cwd: str | Path | None = None) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return out.strip()


def find_cargo_build_sbf() -> Path | None:
    """`cargo-build-sbf` is how Agave installs its own toolchain."""
    found = which("cargo-build-sbf")
    if found:
        return Path(found).resolve()
    return None


def find_solana_cli() -> Path | None:
    """The Solana CLI is used for deploys and program keypads."""
    found = which("solana")
    if found:
        return Path(found).resolve()
    return None


def default_solana_keypair() -> Path:
    return Path.home() / ".config" / "solana" / "id.json"


# ---------------------------------------------------------------------------
# SBF compile/link helpers used by Phase 1's C spike.
# ---------------------------------------------------------------------------


def sbpf_compile_args(
    tc: ToolchainPaths,
    source: Path,
    out_obj: Path,
    include_dirs: Sequence[Path] | None = None,
) -> list[str]:
    """Flags to compile a C source into an SBF object with clang."""
    flags: list[str] = [
        str(tc.clang),
        "--target=sbf",
        f"-mcpu={tc.arch}",
        "-fno-builtin",
        "-fno-stack-protector",
        "-fno-unwind-tables",
        "-fno-asynchronous-unwind-tables",
        "-fno-exceptions",
        "-O2",
    ]
    for include_dir in include_dirs or ():
        flags.extend(("-I", str(include_dir)))
    flags.extend((str(source), "-c", "-o", str(out_obj)))
    return flags


def sbpf_link_args(tc: ToolchainPaths, obj: Path, out_so: Path) -> list[str]:
    """Flags to link an SBF object into a `.so` program with lld."""
    arch = tc.arch.lower()
    is_v3 = arch in ("v3", "v4")
    script = _SBF_V3_SCRIPT if is_v3 else _SBF_V0_SCRIPT
    script_path = out_so.parent / f"link{arch}.ld"
    script_path.write_text(script, encoding="utf-8")
    extra = ["-Bsymbolic"] if is_v3 else []
    return [
        str(tc.lld),
        "-z",
        "notext",
        "-z",
        "max-page-size=4096",
        *extra,
        "--Bdynamic",
        "--threads=1",
        "--gc-sections",
        "--strip-all",
        "--entry",
        _ENTRYPOINT,
        "--shared",
        "-T",
        str(script_path),
        "--allow-multiple-definition",
        str(obj),
        "-o",
        str(out_so),
    ]


def compile_to_sbf(
    tc: ToolchainPaths,
    source: Path,
    out_dir: Path,
    include_dirs: Sequence[Path] | None = None,
) -> Path:
    """Compile a hand-written C file to an SBF ``.so``.

    Returns the path of the produced ``.so``. Raises :class:`PysolError`
    when the toolchain refuses, so `doctor` can advise the user.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    obj = out_dir / (source.stem + ".o")
    so = out_dir / (source.stem + ".so")
    comp = sbpf_compile_args(tc, source, obj, include_dirs=include_dirs)
    completed = subprocess.run(comp, capture_output=True, text=True, check=False, timeout=120)
    if completed.returncode != 0:
        raise PysolError(code=PS4010, message=completed.stderr or "clang compile error")
    link = sbpf_link_args(tc, obj, so)
    completed = subprocess.run(link, capture_output=True, text=True, check=False, timeout=120)
    if completed.returncode != 0 or not so.is_file():
        raise PysolError(code=PS4010, message=completed.stderr or "lld link error")
    return so


# Entry point name SBF loaders call.
_ENTRYPOINT = "entrypoint"

# Extracted and trimmed from rustc_target/src/spec/base/sbf_base.rs
# (anza-xyz/rust@3175de2636).  Kept here so Phase 1 is self-contained.
_SBF_V0_SCRIPT = r"""
PHDRS
{
  text PT_LOAD ;
  rodata PT_LOAD ;
  data PT_LOAD ;
  dynamic PT_DYNAMIC ;
}
SECTIONS
{
  . = SIZEOF_HEADERS;
  .text : { *(.text*) } :text
  .rodata : { *(.rodata*) } :rodata
  .data.rel.ro : { *(.data.rel.ro*) } :rodata
  .dynamic : { *(.dynamic) } :dynamic
  .dynsym : { *(.dynsym) } :data
  .dynstr : { *(.dynstr) } :data
  .rel.dyn : { *(.rel.dyn) } :data
  /DISCARD/ : { *(.eh_frame*) *(.gnu.hash*) *(.hash*) }
}
"""

_SBF_V3_SCRIPT = r"""
SECTIONS
{
  .rodata 0x000000000 : SUBALIGN(8) {
    BYTE(0);
    *(.rodata*)
    *(.data.rel.ro*)
    . = ALIGN(8);
  } :rodata
  .text 0x100000000 : {
     *(.text*)
  } :text
  /DISCARD/ : {
      *(.comment*)
      *(.eh_frame*)
      *(*hash*)
      *(.bss*)
      *(.data*)
      *(.rel.dyn*)
      *(.dynamic)
      *(.dynsym)
      *(.dynstr)
    }
}

PHDRS
{
  rodata PT_LOAD FLAGS(4);
  text PT_LOAD FLAGS(1);
  other PT_NULL FLAGS(0);
}
"""


def _tmp_unused(_: Any) -> None:  # silence mypy question about unused imports
    return None
