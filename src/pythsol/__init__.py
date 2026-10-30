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
  * decorators:   @instruction, @account, @error
  * helpers:      require(cond, error), emit(...)
  * `ProgramError` base class
"""

from __future__ import annotations

from typing import Any, Generic, TypeAlias, TypeVar

__version__ = "0.1.0"

__all__ = [
    "Account",
    "FixedArray",
    "FixedString",
    "Init",
    "InitIfNeeded",
    "Mut",
    "Option",
    "ProgramError",
    "Pubkey",
    "Signer",
    "SystemProgram",
    "Vec",
    "Zeroed",
    "account",
    "error",
    "i8",
    "i16",
    "i32",
    "i64",
    "i128",
    "instruction",
    "require",
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


# collections ----------------------------------------------------------
class Option(Generic[_T]):
    """Anchor `Option[T]` equivalent."""

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...


class Vec(Generic[_T]):
    """Account-resizing vector (Anchor `Vec[T]`)."""

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...


class FixedArray(Generic[_T, _N]):
    """Fixed-length typed array."""

    def __getattribute__(self, name: str) -> Any:  # pragma: no cover
        ...


class FixedString(Generic[_N]):
    """Fixed-length string."""

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
