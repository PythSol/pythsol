"""Header-only SBF runtime linked into every emitted program.

The generated C does ``#include "pythsol_rt.h"``; builds pass
:const:`RUNTIME_INCLUDE_DIR` to clang via ``-I``.
"""

from __future__ import annotations

from pathlib import Path

#: Name of the runtime header the emitter includes.
HEADER_NAME = "pythsol_rt.h"

#: Directory to pass as ``-I`` so ``#include "pythsol_rt.h"`` resolves.
RUNTIME_INCLUDE_DIR = Path(__file__).resolve().parent

__all__ = ["HEADER_NAME", "RUNTIME_INCLUDE_DIR"]
