"""Product CLI: wallet, faucet, deploy dry-run, verify, profile, docs, config."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from pythsol.cli.cache import artifact_key
from pythsol.cli.commands.deploy import deploy_argv
from pythsol.cli.commands.profile import profile_rows
from pythsol.cli.commands.verify import dump_argv, file_sha256
from pythsol.cli.config import load_config
from pythsol.cli.main import cli

ROOT = Path(__file__).parents[1]
COUNTER = ROOT / "examples" / "counter" / "programs" / "counter.py"


def _assert_no_compiler_import(text: str) -> None:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "pythsol" not in alias.name
        if isinstance(node, ast.ImportFrom):
            assert node.module is None or "pythsol" not in (node.module or "")


def test_help_lists_product_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for name in (
        "test",
        "deploy",
        "faucet",
        "wallet",
        "client",
        "cpi",
        "port",
        "verify",
        "profile",
        "docs",
        "serve",
        "idl-publish",
    ):
        assert name in result.output


def test_each_command_help_exits_zero() -> None:
    runner = CliRunner()
    commands = [
        ["test", "--help"],
        ["deploy", "--help"],
        ["faucet", "--help"],
        ["wallet", "--help"],
        ["wallet", "new", "--help"],
        ["client", "--help"],
        ["port", "--help"],
        ["verify", "--help"],
        ["profile", "--help"],
        ["docs", "--help"],
        ["serve", "--help"],
        ["idl-publish", "--help"],
    ]
    for args in commands:
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, args


def test_test_without_a_program_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["test"])
    assert result.exit_code == 2
    assert "pysol.toml" in result.stderr


def test_localnet_without_validator_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pythsol.cli.commands.test_cmd.shutil.which", lambda _name: None)
    result = CliRunner().invoke(cli, ["test", "--localnet"])
    assert result.exit_code == 1
    assert "solana-test-validator" in result.stderr


def test_config_round_trip(tmp_path: Path) -> None:
    (tmp_path / "pysol.toml").write_text(
        '[project]\nname = "app"\n\n[[programs]]\nname = "app"\n'
        'entry = "programs/app.py"\n\n[build]\nout_dir = "target/pythsol"\n',
        encoding="utf-8",
    )
    loaded = load_config(tmp_path / "pysol.toml")
    assert loaded.name == "app"
    assert loaded.programs[0].entry == (tmp_path / "programs" / "app.py").resolve()
    assert loaded.out_dir == (tmp_path / "target" / "pythsol").resolve()


def test_cache_key_changes_with_c_text() -> None:
    header = b"header"
    first = artifact_key(c_text="int a;", clang_version="1", arch="generic", runtime_header=header)
    second = artifact_key(c_text="int b;", clang_version="1", arch="generic", runtime_header=header)
    assert first != second


def test_wallet_new_hides_secret_and_chmods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("solders")
    modes: list[int] = []
    real = os.chmod

    def spy(path: Path, mode: int) -> None:
        modes.append(mode)
        real(path, mode)

    monkeypatch.setattr("pythsol.cli.commands.wallet.os.chmod", spy)
    dest = tmp_path / "id.json"
    created = CliRunner().invoke(cli, ["wallet", "new", "--outfile", str(dest)])
    assert created.exit_code == 0, created.stderr
    assert "[" not in created.output
    assert 0o600 in modes
    assert dest.read_text(encoding="utf-8").strip().startswith("[")
    if os.name != "nt":
        assert dest.stat().st_mode & 0o077 == 0
    again = CliRunner().invoke(cli, ["wallet", "new", "--outfile", str(dest)])
    assert again.exit_code == 1
    address = CliRunner().invoke(cli, ["wallet", "address", "--keypair", str(dest)])
    assert address.exit_code == 0
    assert "[" not in address.output
    assert address.output.strip()


def test_faucet_refuses_mainnet_and_posts_devnet(monkeypatch: pytest.MonkeyPatch) -> None:
    refused = CliRunner().invoke(cli, ["faucet", "--pubkey", "Pubkey111", "--url", "mainnet-beta"])
    assert refused.exit_code == 1
    assert "mainnet" in refused.stderr
    calls: dict[str, object] = {}

    def fake(url: str, method: str, params: list[object], timeout: float = 20.0) -> dict[str, str]:
        calls["url"] = url
        calls["method"] = method
        calls["params"] = params
        return {"result": "sig"}

    monkeypatch.setattr("pythsol.cli.commands.faucet.post_json", fake)
    posted = CliRunner().invoke(cli, ["faucet", "--pubkey", "Pubkey111", "--amount", "1"])
    assert posted.exit_code == 0, posted.stderr
    assert calls["method"] == "requestAirdrop"
    assert calls["params"] == ["Pubkey111", 1_000_000_000]
    assert "api.devnet.solana.com" in str(calls["url"])


def test_deploy_dry_run_and_mainnet_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    so = tmp_path / "prog.so"
    so.write_bytes(b"\x7fELF-test")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("deploy must not run")

    monkeypatch.setattr("pythsol.cli.commands.deploy.subprocess.run", boom)
    dry = CliRunner().invoke(
        cli,
        ["deploy", "--so", str(so), "--dry-run", "--url", "devnet", "--keypair", str(so)],
    )
    assert dry.exit_code == 0, dry.stderr
    assert "solana program deploy" in dry.output
    assert "estimated rent" in dry.output
    blocked = CliRunner().invoke(cli, ["deploy", "--so", str(so), "--url", "mainnet-beta"])
    assert blocked.exit_code == 1
    assert "--yes" in blocked.stderr
    missing = CliRunner().invoke(cli, ["deploy", "--dry-run"])
    assert missing.exit_code == 2


def test_deploy_argv_shape(tmp_path: Path) -> None:
    so = tmp_path / "prog.so"
    argv = deploy_argv(
        so, "http://127.0.0.1:8899", keypair=None, program_keypair=tmp_path / "id.json"
    )
    assert argv[:4] == ["solana", "program", "deploy", str(so)]
    assert "--program-id" in argv


def test_verify_match_and_mismatch(tmp_path: Path) -> None:
    left = tmp_path / "a.so"
    right = tmp_path / "b.so"
    left.write_bytes(b"same")
    right.write_bytes(b"same")
    match = CliRunner().invoke(cli, ["verify", "--left", str(left), "--right", str(right)])
    assert match.exit_code == 0
    assert "MATCH" in match.output
    assert file_sha256(left) in match.output
    right.write_bytes(b"other")
    mismatch = CliRunner().invoke(cli, ["verify", "--left", str(left), "--right", str(right)])
    assert mismatch.exit_code == 3
    assert "MISMATCH" in mismatch.stderr
    usage = CliRunner().invoke(cli, ["verify"])
    assert usage.exit_code == 2
    assert "solana" in " ".join(dump_argv("Addr", "http://127.0.0.1:8899", tmp_path / "d.so"))


def test_profile_reads_locations_and_total(tmp_path: Path) -> None:
    logs = tmp_path / "logs.txt"
    logs.write_text(
        "Program log: require (counter.py:51)\nProgram X consumed 110 of 200000 compute units\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(cli, ["profile", "--logs", str(logs)])
    assert result.exit_code == 0, result.stderr
    assert "counter.py:51" in result.output
    assert "110 of 200000 CU" in result.output
    rows = profile_rows(logs.read_text(encoding="utf-8"))
    assert ("counter.py:51", "logged") in rows


def test_docs_prints_the_reference() -> None:
    result = CliRunner().invoke(cli, ["docs"])
    assert result.exit_code == 0
    assert "pythsol test" in result.output
    assert "Vec" in result.output


def test_serve_refuses_a_public_host() -> None:
    result = CliRunner().invoke(cli, ["serve", "--host", "0.0.0.0"])
    assert result.exit_code == 2


def test_init_writes_a_plugin_test(tmp_path: Path) -> None:
    dest = tmp_path / "app"
    created = CliRunner().invoke(cli, ["init", str(dest), "--template", "counter", "--name", "app"])
    assert created.exit_code == 0, created.stderr
    text = (dest / "tests" / "test_program.py").read_text(encoding="utf-8")
    assert "program.initialize" in text
    assert "struct.pack" not in text
    assert "pythsol.compiler" not in text
    tree = ast.parse(text)
    assert isinstance(tree, ast.Module)


def test_client_from_source_does_not_import_the_compiler(tmp_path: Path) -> None:
    dest = tmp_path / "counter_client.py"
    result = CliRunner().invoke(cli, ["client", str(COUNTER), "-o", str(dest)])
    assert result.exit_code == 0, result.stderr
    text = dest.read_text(encoding="utf-8")
    _assert_no_compiler_import(text)
    assert "def initialize" in text
    assert "def increment" in text
