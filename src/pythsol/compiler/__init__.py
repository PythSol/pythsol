"""PythSol compiler — pipeline modules.

Phase 1 exposes `toolchain` (SBF toolchain discovery). Phase 2 adds the front-end
(parse/subset/type-check); Phase 3 adds ProgramModel/IDL/C emitter.
"""

from __future__ import annotations

from pythsol.compiler.diagnostics import PS4010, PysolError
from pythsol.compiler.toolchain import (
    ToolchainPaths,
    compile_to_sbf,
    find_cargo_build_sbf,
    find_clang,
    find_lld,
    find_solana_cli,
    locate_platform_tools,
    sbpf_compile_args,
    sbpf_link_args,
)

__all__ = [
    "PS4010",
    "PysolError",
    "ToolchainPaths",
    "compile_to_sbf",
    "find_cargo_build_sbf",
    "find_clang",
    "find_lld",
    "find_solana_cli",
    "locate_platform_tools",
    "sbpf_compile_args",
    "sbpf_link_args",
]
