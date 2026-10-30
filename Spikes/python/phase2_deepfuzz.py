"""Dev helper: deep fuzz sweep of the Phase 2 front-end with a code histogram."""

from __future__ import annotations

import ast
import random
import sys
from collections import Counter

sys.path.insert(0, "tests")

import test_phase2_fuzz as fz  # noqa: E402

from pythsol.compiler import front
from pythsol.compiler.diagnostics import PS9000


def main() -> None:
    histogram: Counter[str] = Counter()
    ps9000_seeds: list[int] = []
    clean = 0
    for seed in range(3000):
        rng = random.Random(seed)
        tree = fz._module_for(rng)
        diags = front.check_tree(tree, file=f"d{seed}.py")
        for d in diags:
            histogram[d.code] += 1
            if d.code == PS9000:
                ps9000_seeds.append(seed)
        if not diags:
            clean += 1
        # text path
        try:
            src = ast.unparse(tree)
        except Exception:
            continue
        t_diags = front.check_source(src, file=f"t{seed}.py")
        for d in t_diags:
            histogram["TEXT:" + d.code] += 1
            if d.code == PS9000 and seed not in ps9000_seeds:
                ps9000_seeds.append(seed)
    print("clean:", clean)
    print("PS9000 seeds:", ps9000_seeds[:20])
    for code, count in sorted(histogram.items()):
        print(f"{code}: {count}")


if __name__ == "__main__":
    main()
