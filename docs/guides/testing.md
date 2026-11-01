# Testing a PythSol program

`pythsol test` builds the program named in `pysol.toml`, then runs pytest.
The runner is LiteSVM. Install the extra that provides pytest and solders:

```bash
pip install -e ".[test]"
```

`pythsol init` writes `tests/test_program.py`. That file calls instructions
by keyword. It does not pack bytes and it does not import the compiler.

```python
def test_increment(program, payer):
    opened = program.initialize(authority=payer)
    counter = opened.account("counter")
    program.increment(authority=payer, counter=counter, by=5)
    assert program.fetch("Counter", counter)["count"] == 5
```

`program` fills an `Init` account with the PDA for its seed (the literal, or
the snake_case account name). A single `bump` argument is filled from that
derivation. Pass a keypair for each `Signer`. `program.keypair()` returns a
new keypair with an airdrop on the same LiteSVM. `program.fetch` decodes with
the generated client.

`expect_error` fails the test unless the instruction returns that custom
error. Names match the `@error` class. The on-chain code is `6000 + index`,
not the integer written next to the name.

```python
with program.expect_error("Unauthorized"):
    program.increment(authority=stranger, counter=counter, by=1)
```

A second `pythsol test` of an unchanged program prints
`build: cache hit (skipped clang)` and still runs pytest. Set
`PYTHSOL_NO_CACHE=1` to force clang. Set `PYTHSOL_CACHE` to choose the
directory.

`--localnet` starts `solana-test-validator` and runs `solana program deploy`
when both binaries are installed. The pytest fixtures stay on LiteSVM either
way. If the Solana CLI is missing, the command exits 1 before the build and
prints the Anza install line.

The plugin reads `PYTHSOL_TEST_SO`, `PYTHSOL_TEST_SOURCE`, and
`PYTHSOL_TEST_CLIENT`, which `pythsol test` sets. Running pytest yourself
needs those variables, or a reinstall so the `pytest11` entry point loads.
The `pythsol test` subprocess disables plugin autoload and passes
`-p pythsol.testing.plugin`, so it does not depend on that reinstall.
