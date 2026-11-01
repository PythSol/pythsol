"""Typed DSL surface that programs import from.

This file is intentionally *importable only as types*: the compiler parses the
import with `ast` and never executes it, while mypy/pyright use it to
type-check programs (`py.typed` marker lives beside the package). Phase 3 adds
the actual runtime semantics — this slice is what Phase 2 accepts.

Every program may import:
  * width types:  u8,u16,u32,u64,u128 and i8..i128
  * atoms:        bool, Pubkey, Signer, SystemProgram
  * wrappers:     Mut[T], Init[T], InitIfNeeded[T], Zeroed[T], Account[T]
  * collections:  Option[T], Vec[T], FixedArray[T, N], FixedString[N]
  * decorators:   @instruction, @account, @struct, @event, @error, @enum
  * accounts:     TokenAccount (writable), TokenMint (read-only), no owner check
  * helpers:      require, emit, system_transfer, token_transfer,
                  token2022_transfer, ata_create
  * `ProgramError` base class
"""

from __future__ import annotations

from typing import Any, Generic, TypeAlias, TypeVar

__version__ = "0.1.0"

__all__ = [
    "Account",
    "Address",
    "CloseTo",
    "FixedArray",
    "FixedString",
    "HasOne",
    "Init",
    "InitIfNeeded",
    "Mut",
    "Option",
    "Owner",
    "ProgramError",
    "Pubkey",
    "Seeds",
    "Signer",
    "SystemProgram",
    "TokenAccount",
    "TokenMint",
    "Vec",
    "Zeroed",
    "account",
    "ata_create",
    "emit",
    "enum",
    "error",
    "event",
    "i8",
    "i16",
    "i32",
    "i64",
    "i128",
    "instruction",
    "require",
    "struct",
    "system_transfer",
    "token2022_transfer",
    "token_transfer",
    "u8",
    "u16",
    "u32",
    "u64",
    "u128",
]

_T = TypeVar("_T")
_N = TypeVar("_N")

# widths ---------------------------------------------------------------
u8: TypeAlias = int
u16: TypeAlias = int
u32: TypeAlias = int
u64: TypeAlias = int
u128: TypeAlias = int
i8: TypeAlias = int
i16: TypeAlias = int
i32: TypeAlias = int
i64: TypeAlias = int
i128: TypeAlias = int


# atoms ----------------------------------------------------------------
class Pubkey:
    """An opaque 32-byte on-chain identity."""

    key: Pubkey


class Signer(Pubkey):
    """Binding contract: this account must be a required signer."""

    key: Pubkey


class SystemProgram:
    """Anchor `system_program` stand-in used as a `@account Permissioned type`."""

    program_id: Pubkey


class TokenAccount:
    """A writable SPL token account. The program does not check its owner."""


class TokenMint:
    """A read-only mint. The program does not check its owner."""


class ProgramError:
    """Base class of `@error` program errors."""

    message: str | None = None


# wrappers -------------------------------------------------------------
class Mut(Generic[_T]):
    """Flag: this instruction can write to the wrapped type."""

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...

    def __setattr__(self, name: str, value: Any) -> None:  # pragma: no cover
        ...


class Init(Mut[_T]):
    """Marks this instruction as the one that initializes the account."""


class InitIfNeeded(Mut[_T]):
    """New-account-or-existing? Runtime-conditional."""


class Zeroed(Mut[_T]):
    """The account must be zeroed before this instruction runs."""


class Account(Generic[_T]):
    """Read-only account wrapper."""

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...


class Seeds(Generic[_T, _N]):
    """``Seeds[Init[T], "seed"]`` — the PDA seed, instead of the account name.

    The second argument is a string literal. Type checkers treat that literal
    as a forward reference, so a program line carries ``type: ignore`` and
    ``noqa: F821``. Attribute access is untyped, like ``Mut``.
    """

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...

    def __setattr__(self, name: str, value: Any) -> None:  # pragma: no cover
        ...


class HasOne(Generic[_T, _N]):
    """``HasOne[Mut[T], "field"]`` — ``account.field`` equals that account's key."""

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...

    def __setattr__(self, name: str, value: Any) -> None:  # pragma: no cover
        ...


class CloseTo(Generic[_T, _N]):
    """``CloseTo[Mut[T], dest]`` — after a successful body, lamports move to ``dest``."""

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...

    def __setattr__(self, name: str, value: Any) -> None:  # pragma: no cover
        ...


class Address(Generic[_T, _N]):
    """``Address[Account[T], expected]`` — the account key equals a ``Pubkey`` argument."""

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...


class Owner(Generic[_T, _N]):
    """``Owner[Account[T], program]`` — ``account.owner`` equals that account's key."""

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...


# collections ----------------------------------------------------------
class Option(Generic[_T]):
    """Fixed-width optional value: a tag byte plus the inner value, always reserved.

    ``None`` clears the tag. Assigning a ``T`` sets it. ``.is_some`` reads the
    tag; ``.value`` reads the inner value and aborts when the tag is clear.
    This is not Borsh's short ``None`` (one zero byte). Later fields stay put.
    """

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...


class Vec(Generic[_T]):
    """Account-resizing vector (Anchor `Vec[T]`)."""

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...


class FixedArray(Generic[_T, _N]):
    """Fixed-length typed array. ``N`` in ``FixedArray[T, N]`` is an integer literal."""

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...


class FixedString(Generic[_N]):
    """Fixed-width string: a ``u32`` byte length plus ``N`` reserved bytes.

    Store a string literal whose UTF-8 form fits in ``N``. ``len`` reads the
    stored byte count. This is not Borsh's short string: the ``N`` bytes stay
    reserved so later fields do not move.
    """

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...


# decorators -----------------------------------------------------------
def instruction(func: Any) -> Any:
    """Mark a function as an instruction entry point."""
    return func


def account(value: Any) -> Any:
    """Mark a class as a program-local account layout."""
    return value


def error(value: Any) -> Any:
    """Mark a class as an on-chain error."""
    return value


def enum(value: Any) -> Any:
    """Mark a class as a one-byte unit enum (``Name = <declaration index>``)."""
    return value


def struct(value: Any) -> Any:
    """Mark a class as a fixed-layout value nested inside an account."""
    return value


def event(value: Any) -> Any:
    """Mark a class as a fixed-width value logged by ``emit``."""
    return value


def token_transfer(src: object, dest: object, authority: object, amount: int) -> None:
    """SPL Token Transfer (instruction 3) from ``src`` to ``dest``."""
    del src, dest, authority, amount


def token2022_transfer(src: object, dest: object, authority: object, amount: int) -> None:
    """Token-2022 Transfer (instruction 3). Same accounts as ``token_transfer``."""
    del src, dest, authority, amount


def ata_create(payer: object, ata: object, owner: object, mint: object) -> None:
    """Create an associated token account (idempotent). Uses the SPL Token program."""
    del payer, ata, owner, mint


def system_transfer(src: object, dest: object, lamports: int) -> None:
    """Move lamports with a System-program transfer CPI.

    ``src`` and ``dest`` are a ``Signer`` or a ``Mut`` account, and they must
    differ. The generated client appends the System program account.
    """
    del src, dest, lamports


def emit(value: object) -> None:
    """Log one ``@event``. The compiler lowers the call; this stub does not.

    Write ``emit(Name(field, ...))`` with one positional argument per field,
    in declaration order. The on-chain log is the 8-byte event discriminator
    (``sha256("event:Name")[..8]``) followed by the packed fields.
    """
    del value


class InstructionError(ProgramError):
    """Recommended base for @error classes used via `require(cond, cls.name)`."""


def require(condition: bool, err: object) -> None:
    """Fail the instruction immediately if the condition is false.

    The compiler front-end reads calls to this helper statically; `err` must be
    a member of an ``@error`` class (e.g. ``require(cond, MyErr.Bad)``). The
    static check is what enforces that; the Python signature stays permissive
    so the decorator surface type-checks with plain mypy/pyright.
    """

    if condition is not True:  # pragma: no cover
        raise err  # type: ignore[misc]  # DSL stub: real semantics live in the compiled C.
