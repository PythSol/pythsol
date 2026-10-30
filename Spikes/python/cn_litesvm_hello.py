"""LiteSVM spike: load a compiled SBF `.so` and call it in-process.

The Python bindings we verified live under `solders.litesvm` (solders >= 0.27).
This module keeps the spike small so the CI toolchain test can:
1. compile `Spikes/c/hello.c` with clang/lld,
2. add the result as a program,
3. build a transaction that calls it,
4. report success when the transaction lands without an error.

The spike is intentionally self-contained and is skipped locally when the SBF
toolchain is unavailable (Windows WDAC blocks unsigned clang, see
docs/decisions/ADR-0006-toolchain-platform-tools.md).
"""

from __future__ import annotations

from pathlib import Path

from pythsol.compiler import toolchain
from pythsol.compiler.diagnostics import PysolError

#: Deriving a fixed program id keeps the spike deterministic and easy to reason about.
DEFAULT_PROGRAM_ID = "F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU"  # base58, unfunded
FAUCET_LAMPORTS = 50_000_000


def build_program_hello(source: Path, out_dir: Path) -> Path:
    """Compile the C spike to an SBF `.so` (or raise when the toolchain is absent)."""
    tc = toolchain.locate_platform_tools(None)
    if tc is None:
        raise PysolError(
            code="PS4010",
            message="No SBF platform-tools found; cannot compile the Phase 1 spike locally.",
            fix=(
                "run `pythsol doctor`; install Anza platform-tools with "
                "`solana-install update`. CI Linux runners are the supported path."
            ),
        )
    return toolchain.compile_to_sbf(tc, source, out_dir)


def run_hello_in_litesvm(so_path: Path, program_id: str) -> tuple[bool, list[str]]:
    """Load `so_path` into LiteSVM and call it.

    Returns (success, program_logs).
    """
    if not so_path.is_file():
        raise FileNotFoundError(so_path)
    from solders.litesvm import LiteSVM  # nosec B417 — verified in Phase 1 ADR
    from solders.keypair import Keypair
    from solders.instruction import Instruction
    from solders.message import Message
    from solders.transaction import Transaction

    svm = LiteSVM()
    prog_pk = _pk(program_id)
    svm.add_program(prog_pk, so_path.read_bytes())

    payer = Keypair()  # fresh, ephemeral; keys never leave this process
    svm.airdrop(payer.pubkey(), FAUCET_LAMPORTS)

    # A no-arg, no-account instruction is enough to prove the loader runs our code.
    ix = Instruction(
        program_id=prog_pk,
        accounts=[],
        data=b"",
    )
    blockhash = svm.latest_blockhash()
    msg = Message.new_with_blockhash([ix], payer.pubkey(), blockhash)
    tx = Transaction([payer], msg, blockhash)
    result = svm.send_transaction(tx)
    from solders.transaction_metadata import FailedTransactionMetadata  # nosec B417

    ok = not isinstance(result, FailedTransactionMetadata)
    logs = result.logs() if hasattr(result, "logs") else []
    return ok, list(logs)


def _pk(program_id: str):  # noqa: ANN001 — the solders type takes the same shape in both files
    from solders.pubkey import Pubkey

    return Pubkey.from_string(program_id)
