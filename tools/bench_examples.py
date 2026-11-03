"""Measure LiteSVM compute units for the six examples.

Usage (from the repo root):

    .\\.venv\\Scripts\\python.exe tools\\bench_examples.py

The script builds every example with the SBF platform tools, runs one
representative instruction per program in LiteSVM, and writes
``docs/benchmarks.md`` from the measurements. Numbers are transaction CU as
reported by solders; they include the transaction overhead, not just the
program entrypoint. Re-run on your machine instead of trusting these numbers.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
PROGRAM_ID = "F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU"
FAUCET = 50_000_000


def _toolchain() -> Any:
    from pythsol.compiler import toolchain
    from pythsol.compiler.diagnostics import PysolError

    try:
        found = toolchain.locate_platform_tools(None)
    except PysolError:
        found = None
    if found is not None:
        return found
    sdk = ROOT / "Spikes" / "tools" / "platform-tools-1.58"
    if not sdk.is_dir():
        raise SystemExit("no platform-tools; set PYTHSOL_SBF_SDK")
    os.environ.setdefault("PYTHSOL_SBF_SDK", str(sdk))
    return toolchain.locate_platform_tools(None)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build(name: str, out: Path) -> tuple[Path, Any]:
    from pythsol.client.gen import render_client
    from pythsol.compiler import toolchain
    from pythsol.compiler.pipeline import emit_program
    from pythsol.runtime import RUNTIME_INCLUDE_DIR

    source_path = EXAMPLES / name / "programs" / f"{name}.py"
    source = source_path.read_text(encoding="utf-8")
    generated = emit_program(source, source_path)
    if not generated.ok or generated.generated is None:
        detail = "\n".join(d.render() for d in generated.diagnostics)
        raise SystemExit(f"{name} did not compile: {detail}")
    c_path = out / f"{name}.c"
    c_path.write_text(generated.c_text, encoding="utf-8", newline="\n")
    so_path = toolchain.compile_to_sbf(
        _toolchain(), c_path, out, include_dirs=(RUNTIME_INCLUDE_DIR,)
    )
    client_path = out / f"{name}_client.py"
    client_path.write_text(render_client(generated.generated), encoding="utf-8", newline="\n")
    return so_path, _load(client_path, f"{name}_client")


class Harness:
    def __init__(self, name: str, out: Path) -> None:
        from solders.keypair import Keypair
        from solders.litesvm import LiteSVM
        from solders.pubkey import Pubkey

        self.Keypair = Keypair
        self.Pubkey = Pubkey
        self.so_path, self.client = _build(name, out)
        self.svm = LiteSVM()
        self.program_id = Pubkey.from_string(PROGRAM_ID)
        self.svm.add_program(self.program_id, self.so_path.read_bytes())
        self.payer = Keypair()
        self.svm.airdrop(self.payer.pubkey(), FAUCET)

    def keypair(self) -> Any:
        key = self.Keypair()
        self.svm.airdrop(key.pubkey(), FAUCET)
        return key

    def pda(self, seed: str) -> tuple[Any, int]:
        return self.Pubkey.find_program_address([seed.encode()], self.program_id)

    def send(self, ix: Any, signers: list[Any]) -> Any:
        from solders.message import Message
        from solders.transaction import Transaction
        from solders.transaction_metadata import FailedTransactionMetadata

        self.svm.expire_blockhash()
        blockhash = self.svm.latest_blockhash()
        message = Message.new_with_blockhash([ix], signers[0].pubkey(), blockhash)
        result = self.svm.send_transaction(Transaction(signers, message, blockhash))
        if isinstance(result, FailedTransactionMetadata):
            raise SystemExit(f"transaction failed: {result}")
        return result

    def measure(self, ix: Any, signers: list[Any]) -> int:
        result = self.send(ix, signers)
        value = result.compute_units_consumed
        return int(value() if callable(value) else value)


def bench_counter(out: Path) -> int:
    h = Harness("counter", out)
    counter, bump = h.pda("counter")
    h.send(h.client.initialize(h.program_id, h.payer.pubkey(), counter, bump), [h.payer])
    return h.measure(
        h.client.increment(h.program_id, h.payer.pubkey(), counter, 5),
        [h.payer],
    )


def bench_ledger(out: Path) -> int:
    h = Harness("ledger", out)
    ledger, bump = h.pda("ledger")
    h.send(h.client.initialize(h.program_id, h.payer.pubkey(), ledger, bump), [h.payer])
    return h.measure(
        h.client.deposit(h.program_id, h.payer.pubkey(), ledger, 1, 5),
        [h.payer],
    )


def bench_vault(out: Path) -> int:
    h = Harness("vault", out)
    vault, bump = h.pda("vault")
    h.send(h.client.initialize(h.program_id, h.payer.pubkey(), vault, bump), [h.payer])
    return h.measure(
        h.client.deposit(h.program_id, h.payer.pubkey(), vault, 1_000),
        [h.payer],
    )


def bench_escrow(out: Path) -> int:
    h = Harness("escrow", out)
    taker = h.keypair()
    escrow, bump = h.pda("escrow")
    h.send(
        h.client.make(h.program_id, h.payer.pubkey(), escrow, taker.pubkey(), bump, 1_000),
        [h.payer],
    )
    return h.measure(
        h.client.take(h.program_id, taker.pubkey(), h.payer.pubkey(), escrow, 400),
        [taker, h.payer],
    )


def bench_multisig(out: Path) -> int:
    h = Harness("multisig", out)
    first, second, third, dest = (h.keypair() for _ in range(4))
    treasury, bump = h.pda("treasury")
    h.send(
        h.client.initialize(
            h.program_id,
            h.payer.pubkey(),
            treasury,
            first.pubkey(),
            second.pubkey(),
            third.pubkey(),
            2,
            bump,
        ),
        [h.payer],
    )
    h.send(h.client.fund(h.program_id, h.payer.pubkey(), treasury, 1_000), [h.payer])
    h.send(h.client.approve(h.program_id, first.pubkey(), treasury, 0), [first])
    h.send(h.client.approve(h.program_id, second.pubkey(), treasury, 1), [second])
    return h.measure(
        h.client.release(h.program_id, second.pubkey(), treasury, dest.pubkey(), 1, 400),
        [second, dest],
    )


def bench_poll(out: Path) -> int:
    h = Harness("poll", out)
    voters = [h.keypair() for _ in range(4)]
    poll, bump = h.pda("poll")
    h.send(
        h.client.initialize(
            h.program_id,
            h.payer.pubkey(),
            poll,
            voters[0].pubkey(),
            voters[1].pubkey(),
            voters[2].pubkey(),
            voters[3].pubkey(),
            bump,
        ),
        [h.payer],
    )
    return h.measure(
        h.client.vote(h.program_id, voters[0].pubkey(), poll, 0, True),
        [voters[0]],
    )


BENCHMARKS = {
    "counter": ("increment(by=5)", bench_counter),
    "ledger": ("deposit(slot=1, amount=5)", bench_ledger),
    "vault": ("deposit(amount=1000)", bench_vault),
    "escrow": ("take(price=400)", bench_escrow),
    "multisig": ("release(slot=1, amount=400) after 2 approvals", bench_multisig),
    "poll": ("vote(slot=0, choice=True)", bench_poll),
}


def main() -> int:
    import tempfile

    from solders import __version__ as solders_version

    rows: list[tuple[str, str, int]] = []
    with tempfile.TemporaryDirectory(prefix="pythsol-bench-") as tmp:
        for name, (label, fn) in BENCHMARKS.items():
            rows.append((name, label, fn(Path(tmp))))

    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [
        "# Compute-unit benchmarks",
        "",
        "Generated by `tools/bench_examples.py`. These are **measured** LiteSVM",
        "transaction CU on the machine that ran the script — they include",
        "transaction overhead, not just the program entrypoint. Re-run the",
        "script rather than comparing across machines or toolchains.",
        "",
        f"- Date: {stamp}",
        f"- solders: {solders_version}",
        "- Toolchain: Agave/Anza platform-tools (resolved by `pythsol doctor`)",
        "- Program ID: `" + PROGRAM_ID + "`",
        "",
        "| Program | Measured instruction | CU |",
        "| --- | --- | ---: |",
    ]
    lines.extend(f"| {name} | `{label}` | {cu:,} |" for name, label, cu in rows)
    lines += [
        "",
        "The vault/escrow/multisig rows move lamports; the rest write account",
        "state. Setup instructions (initialize, fund, approve, make) are not",
        "included in the measured row.",
        "",
    ]
    target = ROOT / "docs" / "benchmarks.md"
    target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("\n".join(lines))
    print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
