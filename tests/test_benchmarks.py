"""The measured CU numbers have a generous ceiling so a regression fails CI."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tools" / "bench_examples.py"
CEILING = 20_000


def _bench() -> Any:
    spec = importlib.util.spec_from_file_location("bench_examples", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ready() -> bool:
    from pythsol.compiler import toolchain
    from pythsol.compiler.diagnostics import PysolError

    try:
        return toolchain.locate_platform_tools(None) is not None
    except PysolError:
        pass
    sdk = ROOT / "Spikes" / "tools" / "platform-tools-1.58"
    if sdk.is_dir():
        import os

        os.environ.setdefault("PYTHSOL_SBF_SDK", str(sdk))
        try:
            return toolchain.locate_platform_tools(None) is not None
        except PysolError:
            return False
    return False


@pytest.mark.toolchain
def test_every_example_stays_under_the_cu_ceiling(tmp_path: Path) -> None:
    pytest.importorskip("solders")
    if not _ready():
        pytest.skip("no runnable SBF platform-tools on this machine (see ADR-0006)")
    module = _bench()
    for name, (label, run) in module.BENCHMARKS.items():
        out = tmp_path / name
        out.mkdir()
        cu = run(out)
        assert cu < CEILING, f"{name}: {label} used {cu} CU (ceiling {CEILING})"
