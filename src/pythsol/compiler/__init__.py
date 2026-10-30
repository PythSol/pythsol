"""PythSol compiler — front-end and toolchain modules.

Pipeline: ``parse → subset → resolve → typecheck`` produce
:class:`~pythsol.compiler.diagnostics.Diagnostic` objects; ``toolchain`` then
compiles the generated C (Phase 3) to native SBF with clang + ld.lld.
"""

from __future__ import annotations

from pythsol.compiler.diagnostics import PS4010, Diagnostic, PysolError
from pythsol.compiler.front import check_source, check_tree
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
    "Diagnostic",
    "PysolError",
    "ToolchainPaths",
    "check_source",
    "check_tree",
    "compile_to_sbf",
    "find_cargo_build_sbf",
    "find_clang",
    "find_lld",
    "find_solana_cli",
    "locate_platform_tools",
    "sbpf_compile_args",
    "sbpf_link_args",
]
