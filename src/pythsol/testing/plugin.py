"""Pytest plugin: ``svm``, ``program``, ``payer``, ``accounts``, and ``send``.

``pythsol test`` sets ``PYTHSOL_TEST_SO``, ``PYTHSOL_TEST_CLIENT``, and
``PYTHSOL_TEST_SOURCE``. A test then calls instructions by keyword:

```python
def test_increment(program, payer):
    opened = program.initialize(authority=payer)
    counter = opened.account("counter")
    program.increment(authority=payer, counter=counter, by=5)
    assert program.fetch("Counter", counter)["count"] == 5
```

``Init`` accounts and a ``bump`` argument are filled in. The signer must be a
keypair. Failures raise with the program logs, including ``(file.py:line)``.
"""

from __future__ import annotations

import importlib.util
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from pythsol.testing import DEFAULT_PROGRAM_ID

FAUCET_LAMPORTS = 50_000_000

_CUSTOM = re.compile(r"Custom\((\d+)\)")
_HEX = re.compile(r"custom program error: 0x([0-9a-fA-F]+)")
_CU = re.compile(r"consumed (\d+) of")
_SOLDERS: dict[str, Any] = {}


def pytest_configure(config: pytest.Config) -> None:
    """Register the marker used by template tests."""
    config.addinivalue_line("markers", "pythsol: test drives a PythSol program in LiteSVM")


@dataclass(frozen=True)
class PythsolTarget:
    """A built program the fixtures load."""

    source: Path
    so: Path
    client: Path
    program_id: str = DEFAULT_PROGRAM_ID


@dataclass
class CallResult:
    """One ``send``: logs, compute units, and the accounts the call used."""

    ok: bool
    logs: list[str]
    compute_units: int | None
    error_code: int | None
    accounts: dict[str, Any] = field(default_factory=dict)

    def account(self, name: str) -> Any:
        """Pubkey passed for the account parameter ``name``."""
        if name not in self.accounts:
            known = ", ".join(sorted(self.accounts))
            raise KeyError(f"no account {name!r} on this call ({known})")
        return self.accounts[name]


class ProgramFailed(AssertionError):  # noqa: N818
    """The instruction returned an error and the test did not expect one."""


def _solders() -> dict[str, Any]:
    if _SOLDERS:
        return _SOLDERS
    from solders.keypair import Keypair
    from solders.litesvm import LiteSVM
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction
    from solders.transaction_metadata import FailedTransactionMetadata

    _SOLDERS.update(
        {
            "Keypair": Keypair,
            "LiteSVM": LiteSVM,
            "Message": Message,
            "Pubkey": Pubkey,
            "Transaction": Transaction,
            "Failed": FailedTransactionMetadata,
        }
    )
    return _SOLDERS


def _need_solders() -> None:
    try:
        _solders()
    except ImportError:
        if os.environ.get("PYTHSOL_TEST_SO"):
            pytest.fail("solders is required for pythsol test; pip install 'pythsol[test]'")
        pytest.skip("solders is not installed")


def _is_keypair(value: object) -> bool:
    return callable(getattr(value, "pubkey", None)) and callable(
        getattr(value, "sign_message", None)
    )


def _as_pubkey(value: Any) -> Any:
    pubkey = getattr(value, "pubkey", None)
    if callable(pubkey):
        return pubkey()
    return value


def _logs(result: Any) -> list[str]:
    try:
        logs = getattr(result, "logs", None)
        if callable(logs):
            logs = logs()
        else:
            meta = getattr(result, "meta", None)
            meta = meta() if callable(meta) else meta
            logs = getattr(meta, "logs", None)
            logs = logs() if callable(logs) else logs
        return [str(entry) for entry in (logs or [])]
    except Exception:
        return []


def _failed(result: Any) -> bool:
    if isinstance(result, _solders()["Failed"]):
        return True
    err = getattr(result, "err", None)
    if callable(err):
        err = err()
    return err is not None


def _error_code(result: Any) -> int | None:
    err = getattr(result, "err", None)
    if err is None:
        return None
    if callable(err):
        err = err()
    if err is None:
        return None
    text = str(err)
    digits = _CUSTOM.search(text)
    if digits:
        return int(digits.group(1), 10)
    hexa = _HEX.search(text)
    if hexa:
        return int(hexa.group(1), 16)
    return None


def _compute_units(result: Any, logs: list[str]) -> int | None:
    meta = getattr(result, "meta", None)
    if callable(meta):
        try:
            meta = meta()
        except Exception:
            meta = None
    for obj in (result, meta):
        if obj is None:
            continue
        for attr in ("compute_units_consumed", "compute_units"):
            value = getattr(obj, attr, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    continue
            if isinstance(value, int):
                return value
    for line in logs:
        match = _CU.search(line)
        if match:
            return int(match.group(1))
    return None


def _load_client(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(f"pythsol_client_{path.stem}_{id(path)}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load client {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LoadedProgram:
    """One LiteSVM plus the generated client for a built program."""

    def __init__(self, svm: Any, payer: Any, target: PythsolTarget) -> None:
        from pythsol.compiler.model import ProgramModel
        from pythsol.compiler.modules import read_sibling_modules
        from pythsol.compiler.pipeline import emit_program

        text = target.source.read_text(encoding="utf-8")
        modules, module_files = read_sibling_modules(target.source)
        generated = emit_program(
            text,
            target.source,
            modules=modules,
            module_files=module_files,
        )
        if not generated.ok or generated.generated is None:
            rendered = "\n".join(item.render() for item in generated.diagnostics)
            pytest.fail(f"program did not check:\n{rendered}")
        model: ProgramModel = generated.generated
        self.svm = svm
        self.payer = payer
        self.target = target
        self.model = model
        self.name = model.name
        self.client = _load_client(target.client)
        self.program_id = _solders()["Pubkey"].from_string(target.program_id)
        self.addresses: dict[str, Any] = {}
        self.instruction_names = tuple(instr.snake_name for instr in model.instructions)
        self._errors = {err.name: err.code for err in model.errors}
        self._expect: int | None = None
        self._last: CallResult | None = None

    def keypair(self) -> Any:
        """A new funded keypair on this LiteSVM."""
        kp = _solders()["Keypair"]()
        self.svm.airdrop(kp.pubkey(), FAUCET_LAMPORTS)
        return kp

    def fetch(self, account: str, address: Any) -> dict[str, Any]:
        """Decode ``account`` at ``address`` with the generated client."""
        from pythsol.compiler.model import snake_case

        found = self.svm.get_account(address)
        if found is None or not bytes(found.data):
            raise AssertionError(f"{account} at {address} is empty")
        fn = getattr(self.client, f"decode_{snake_case(account)}")
        decoded: dict[str, Any] = fn(bytes(found.data))
        return decoded

    def send_ix(self, ix: Any, signers: list[Any]) -> CallResult:
        """Send a solders instruction. ``signers[0]`` pays the fee."""
        if not signers:
            raise TypeError("send needs at least one signer")
        expire = getattr(self.svm, "expire_blockhash", None)
        if callable(expire):
            expire()
        blockhash = self.svm.latest_blockhash()
        message = _solders()["Message"].new_with_blockhash([ix], signers[0].pubkey(), blockhash)
        tx = _solders()["Transaction"](signers, message, blockhash)
        raw = self.svm.send_transaction(tx)
        return self._result(raw, {})

    @contextmanager
    def expect_error(self, name: str | int) -> Iterator[None]:
        """Fail unless the next instruction returns this custom error."""
        expected = name if isinstance(name, int) else self._resolve_error(name)
        if self._expect is not None:
            raise RuntimeError("expect_error cannot be nested")
        self._expect = expected
        self._last = None
        try:
            yield
        except Exception:
            raise
        else:
            last = self._last
            got = None if last is None else last.error_code
            logs = "" if last is None else "\n".join(last.logs)
            if last is None or last.ok or last.error_code != expected:
                raise AssertionError(f"expected error {name} ({expected}), got {got}\n{logs}")
        finally:
            self._expect = None

    def __getattr__(self, name: str) -> Any:
        instr = self._instruction(name)
        if instr is None:
            raise AttributeError(name)

        def call(**kwargs: Any) -> CallResult:
            return self._invoke(instr, kwargs)

        return call

    def _instruction(self, name: str) -> Any:
        for instr in self.model.instructions:
            if instr.name == name or instr.snake_name == name:
                return instr
        return None

    def _resolve_error(self, name: str) -> int:
        if name in self._errors:
            return self._errors[name]
        for err_name, code in self._errors.items():
            if name == err_name or name.endswith("." + err_name):
                return code
        known = ", ".join(sorted(self._errors))
        raise KeyError(f"unknown error {name!r} ({known})")

    def _invoke(self, instr: Any, kwargs: dict[str, Any]) -> CallResult:
        from pythsol.compiler.model import snake_case

        account_names = {param.name for param in instr.account_params}
        data_names = {param.name for param in instr.data_params}
        unknown = set(kwargs) - account_names - data_names
        if unknown:
            raise TypeError(f"unknown argument {sorted(unknown)[0]}")
        pubkeys: dict[str, Any] = {}
        signers: list[Any] = []
        seen: set[str] = set()
        bumps: list[int] = []
        used: dict[str, Any] = {}
        for param in instr.account_params:
            if param.name in kwargs:
                value = kwargs[param.name]
                if param.kind == "signer" and not _is_keypair(value):
                    raise TypeError(f"{param.name} must be a keypair")
                if _is_keypair(value) and param.kind == "signer":
                    identity = str(value.pubkey())
                    if identity not in seen:
                        seen.add(identity)
                        signers.append(value)
                pubkey = _as_pubkey(value)
            elif param.is_init or param.seed:
                seed = param.seed or snake_case(param.account)
                pubkey, bump = _solders()["Pubkey"].find_program_address(
                    [seed.encode()],
                    self.program_id,
                )
                bumps.append(int(bump))
            else:
                raise TypeError(f"missing account {param.name}")
            pubkeys[param.name] = pubkey
            used[param.name] = pubkey
        values: list[Any] = []
        for param in instr.data_params:
            if param.name in kwargs:
                value = kwargs[param.name]
                values.append(_as_pubkey(value) if _is_keypair(value) else value)
            elif param.name == "bump" and len(bumps) == 1:
                values.append(bumps[0])
            else:
                raise TypeError(f"missing argument {param.name}")
        if not signers:
            raise TypeError("pass a keypair for the signer")
        fn = getattr(self.client, instr.snake_name)
        ix = fn(self.program_id, *[pubkeys[param.name] for param in instr.account_params], *values)
        raw = self._send_raw(ix, signers)
        result = self._result(raw, used)
        self.addresses.update(used)
        self._last = result
        if not result.ok and self._expect is None:
            raise ProgramFailed(self._failure_text(result))
        return result

    def _send_raw(self, ix: Any, signers: list[Any]) -> Any:
        expire = getattr(self.svm, "expire_blockhash", None)
        if callable(expire):
            expire()
        blockhash = self.svm.latest_blockhash()
        message = _solders()["Message"].new_with_blockhash([ix], signers[0].pubkey(), blockhash)
        tx = _solders()["Transaction"](signers, message, blockhash)
        return self.svm.send_transaction(tx)

    def _result(self, raw: Any, accounts: dict[str, Any]) -> CallResult:
        logs = _logs(raw)
        ok = not _failed(raw)
        return CallResult(
            ok=ok,
            logs=logs,
            compute_units=_compute_units(raw, logs),
            error_code=None if ok else _error_code(raw),
            accounts=dict(accounts),
        )

    def _failure_text(self, result: CallResult) -> str:
        body = "\n".join(result.logs)
        return f"program failed with {result.error_code}\n{body}"


@pytest.fixture(scope="module")
def pythsol_target() -> PythsolTarget:
    """Built artifacts. ``pythsol test`` sets the environment this reads."""
    so = os.environ.get("PYTHSOL_TEST_SO")
    source = os.environ.get("PYTHSOL_TEST_SOURCE")
    client = os.environ.get("PYTHSOL_TEST_CLIENT")
    if not so or not source or not client:
        pytest.skip("PYTHSOL_TEST_SO is not set; run pythsol test")
    program_id = os.environ.get("PYTHSOL_PROGRAM_ID") or DEFAULT_PROGRAM_ID
    return PythsolTarget(Path(source), Path(so), Path(client), program_id)


@pytest.fixture
def svm(pythsol_target: PythsolTarget) -> Any:
    """A fresh LiteSVM with the program loaded."""
    _need_solders()
    vm = _solders()["LiteSVM"]()
    program_id = _solders()["Pubkey"].from_string(pythsol_target.program_id)
    vm.add_program(program_id, pythsol_target.so.read_bytes())
    return vm


@pytest.fixture
def payer(svm: Any) -> Any:
    """A funded fee-payer keypair."""
    _need_solders()
    kp = _solders()["Keypair"]()
    svm.airdrop(kp.pubkey(), FAUCET_LAMPORTS)
    return kp


@pytest.fixture
def program(svm: Any, payer: Any, pythsol_target: PythsolTarget) -> LoadedProgram:
    """Instruction helpers bound to ``svm``."""
    _need_solders()
    return LoadedProgram(svm, payer, pythsol_target)


@pytest.fixture
def accounts(program: LoadedProgram) -> dict[str, Any]:
    """Account name to pubkey, filled in as instructions run."""
    return program.addresses


@pytest.fixture
def send(program: LoadedProgram) -> Any:
    """``send(ix, signers)`` for a hand-built instruction."""
    return program.send_ix
