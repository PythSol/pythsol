"""Project files written by `pythsol init`.

Program sources live in :mod:`pythsol.cli.template_programs` so a scaffold
does not depend on the ``examples/`` tree being installed.
"""

from __future__ import annotations

from importlib.resources import files

__all__ = ["TEMPLATES", "program_source", "program_test_source", "project_files"]

TEMPLATES: tuple[str, ...] = ("counter", "ledger", "vault", "escrow", "multisig", "poll")

_PYSOL = """\
[project]
name = "{name}"
python = ">=3.11"

[[programs]]
name = "{name}"
entry = "programs/{name}.py"

[build]
sbpf = "v0"
heap_kib = 32
out_dir = "target/pythsol"
"""

_PYPROJECT = """\
[project]
name = "{name}"
version = "0.1.0"
description = "Solana program written with PythSol"
requires-python = ">=3.11"
dependencies = ["pythsol"]
"""

_README = """\
# {name}

PythSol program. From this directory:

```bash
pythsol check programs/{name}.py
pythsol build programs/{name}.py
pythsol idl programs/{name}.py
```

`pythsol build` writes a native SBF `.so`, an Anchor-style IDL, and
`{name}_client.py` (solders instruction builders). `pythsol test` builds
again (a cache hit skips clang) and runs `tests/` on LiteSVM.
"""


def program_source(template: str) -> str:
    """Return the embedded program source for ``template``."""
    resource = files("pythsol.cli.template_programs").joinpath(f"{template}.py")
    return resource.read_text(encoding="utf-8")


_COUNTER_TEST = """\
def test_increment(program, payer):
    opened = program.initialize(authority=payer)
    counter = opened.account("counter")
    program.increment(authority=payer, counter=counter, by=5)
    state = program.fetch("Counter", counter)
    assert state["count"] == 5


def test_unauthorized(program, payer):
    opened = program.initialize(authority=payer)
    counter = opened.account("counter")
    stranger = program.keypair()
    with program.expect_error("Unauthorized"):
        program.increment(authority=stranger, counter=counter, by=1)
"""

_LEDGER_TEST = """\
def test_deposit(program, payer):
    opened = program.initialize(authority=payer)
    ledger = opened.account("ledger")
    program.deposit(authority=payer, ledger=ledger, slot=1, amount=5)
    state = program.fetch("Ledger", ledger)
    assert state["total"] == 5
"""

_VAULT_TEST = """\
def test_deposit_and_close(program, payer):
    opened = program.initialize(authority=payer)
    vault = opened.account("vault")
    program.deposit(authority=payer, vault=vault, amount=1000)
    state = program.fetch("Vault", vault)
    assert state["balance"] == 1000
    program.close(authority=payer, vault=vault)
"""

_ESCROW_TEST = """\
def test_make_and_take(program, payer):
    taker = program.keypair()
    opened = program.make(maker=payer, taker=taker, amount=1000)
    escrow = opened.account("escrow")
    program.take(taker=taker, maker=payer, escrow=escrow, price=400)
"""

_MULTISIG_TEST = """\
def test_two_of_three(program, payer):
    first = program.keypair()
    second = program.keypair()
    third = program.keypair()
    dest = program.keypair()
    opened = program.initialize(
        authority=payer,
        first=first.pubkey(),
        second=second.pubkey(),
        third=third.pubkey(),
        threshold=2,
    )
    treasury = opened.account("treasury")
    program.fund(donor=payer, treasury=treasury, amount=1000)
    program.approve(owner=first, treasury=treasury, slot=0)
    program.approve(owner=second, treasury=treasury, slot=1)
    program.release(owner=second, treasury=treasury, dest=dest, slot=1, amount=400)
    assert program.fetch("Treasury", treasury)["paid"] == 400


def test_one_approval_is_not_enough(program, payer):
    first = program.keypair()
    second = program.keypair()
    third = program.keypair()
    dest = program.keypair()
    opened = program.initialize(
        authority=payer,
        first=first.pubkey(),
        second=second.pubkey(),
        third=third.pubkey(),
        threshold=2,
    )
    treasury = opened.account("treasury")
    program.fund(donor=payer, treasury=treasury, amount=1000)
    program.approve(owner=first, treasury=treasury, slot=0)
    with program.expect_error("NotApproved"):
        program.release(owner=second, treasury=treasury, dest=dest, slot=1, amount=400)
"""

_POLL_TEST = """\
def test_one_vote_per_key(program, payer):
    voters = [program.keypair() for _ in range(4)]
    opened = program.initialize(
        authority=payer,
        first=voters[0].pubkey(),
        second=voters[1].pubkey(),
        third=voters[2].pubkey(),
        fourth=voters[3].pubkey(),
    )
    poll = opened.account("poll")
    program.vote(voter=voters[0], poll=poll, slot=0, choice=True)
    program.vote(voter=voters[3], poll=poll, slot=3, choice=False)
    state = program.fetch("Poll", poll)
    assert state["yes"] == 1
    assert state["no"] == 1
    with program.expect_error("AlreadyVoted"):
        program.vote(voter=voters[0], poll=poll, slot=0, choice=True)
"""

_TEMPLATE_TESTS = {
    "counter": _COUNTER_TEST,
    "ledger": _LEDGER_TEST,
    "vault": _VAULT_TEST,
    "escrow": _ESCROW_TEST,
    "multisig": _MULTISIG_TEST,
    "poll": _POLL_TEST,
}


def program_test_source(template: str) -> str:
    """Pytest source for ``template``. It uses plugin fixtures only."""
    try:
        return _TEMPLATE_TESTS[template]
    except KeyError as exc:
        raise ValueError(f"unknown template {template}") from exc


def project_files(name: str, template: str) -> dict[str, str]:
    """Relative path → file text for a new project."""
    return {
        "pysol.toml": _PYSOL.format(name=name),
        "pyproject.toml": _PYPROJECT.format(name=name),
        "README.md": _README.format(name=name),
        f"programs/{name}.py": program_source(template),
        "tests/test_program.py": program_test_source(template),
    }
